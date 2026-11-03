"""Lightweight PGN parser: headers, movetext, comments, variations, NAGs.

Produced for the Chess PGN MCP Server by Asdale Dynamics, LLC.
Standard library only; parses what real-world PGN files actually contain.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple, Optional

from .board import Position, START_FEN, Move

TAG_RE = re.compile(r'^\[\s*([A-Za-z0-9_]+)\s+"((?:[^"\\]|\\.)*)"\s*\]$')
MOVE_NO_RE = re.compile(r"^\d+\.{1,3}")
RESULT_RE = re.compile(r"^(1-0|0-1|1/2-1/2|\*)$")

RESULTS = ("1-0", "0-1", "1/2-1/2", "*")


class Game:
    """One PGN game: headers plus a validated, replayed move sequence."""

    __slots__ = ("headers", "plies", "result", "start_fen")

    def __init__(self, headers: dict, start_fen: Optional[str] = None):
        self.headers: dict = dict(headers)
        if start_fen and start_fen != START_FEN:
            self.headers.setdefault("SetUp", "1")
            self.headers["FEN"] = start_fen
        self.start_fen: str = start_fen or self.headers.get("FEN") or START_FEN
        self.plies: List["Ply"] = []
        self.result: str = self.headers.get("Result", "*")

    def add_ply(self, number: int, san: str, move: Move, fen_before: str, fen_after: str,
                key_before: str, player: str) -> None:
        self.plies.append(
            Ply(number, san, move, fen_before, fen_after, key_before, player)
        )

    @property
    def white(self) -> str:
        return self.headers.get("White", "?")

    @property
    def black(self) -> str:
        return self.headers.get("Black", "?")

    @property
    def opening(self) -> str:
        return self.headers.get("Opening", "")

    def to_pgn(self) -> str:
        """Render the game to PGN text from its stored headers and SAN moves."""
        order = [
            "Event", "Site", "Date", "Round", "White", "Black", "Result",
            "WhiteElo", "BlackElo", "ECO", "Opening", "Variation",
            "TimeControl", "SetUp", "FEN",
        ]
        head = []
        for tag in order:
            if tag in self.headers:
                head.append('[%s "%s"]' % (tag, _escape(self.headers[tag])))
        for tag, value in self.headers.items():
            if tag not in order and isinstance(value, str):
                head.append('[%s "%s"]' % (tag, _escape(value)))

        tokens = []
        for ply in self.plies:
            if ply.player == "white":
                tokens.append("%d." % ply.number)
            tokens.append(ply.san)
        text = " ".join(tokens)
        lines = ["\n".join(head), "", _wrap(text), self.result, ""]
        return "\n".join(lines)


class Ply(NamedTuple):
    """One move of a game, with the position it created."""

    number: int
    san: str
    move: Move
    fen_before: str
    fen_after: str
    key_before: str  # position key *before* the move (side to move)
    player: str  # "white" or "black"


_WRAPPED_WIDTH = 78


def _wrap(text: str) -> str:
    words = text.split(" ")
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 > _WRAPPED_WIDTH and current:
            lines.append(current)
            current = word
        else:
            current = word if not current else current + " " + word
    if current:
        lines.append(current)
    return "\n".join(lines)


def _unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def parse_pgn(text: str) -> List[Game]:
    """Parse a PGN file (possibly many games) into Game objects.

    Comments, NAGs ($n), nested variations, move numbers and results inside
    movetext are handled. Raises ValueError with useful context on bad input.
    """
    games: List[Game] = []
    headers: Optional[dict] = None
    movelines: List[str] = []

    def finish():
        nonlocal headers, movelines
        if headers is None:
            return
        raw = " ".join(movelines).strip()
        if not raw:
            raise ValueError("game with headers but no moves: %r" % headers.get("Event", ""))
        games.append(_parse_movetext(headers, raw))
        headers = None
        movelines = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        tag_match = TAG_RE.match(stripped)
        if tag_match:
            if headers is not None and movelines:
                finish()
            if headers is None:
                headers = {}
            name, value = tag_match.groups()
            if name not in headers:  # first occurrence of a tag wins
                headers[name] = _unescape(value)
        else:
            if headers is None:
                raise ValueError(
                    "line %d: movetext before any header: %r" % (lineno, stripped)
                )
            movelines.append(stripped)
    finish()
    if not games:
        raise ValueError("no games found in PGN text")
    return games


def _strip_comments_and_variations(movetext: str) -> str:
    """Remove {comments}, ;line-comments and nested (variations)."""
    out = []
    i, n = 0, len(movetext)
    depth = 0
    while i < n:
        c = movetext[i]
        if c == "{":
            end = movetext.find("}", i + 1)
            if end == -1:
                raise ValueError("unterminated comment")
            i = end + 1
        elif c == ";":
            end = movetext.find("\n", i)
            i = n if end == -1 else end + 1
        elif c == "(":
            depth += 1
            i += 1
        elif c == ")":
            if depth == 0:
                raise ValueError("unbalanced ')' in movetext")
            depth -= 1
            i += 1
        else:
            if depth == 0:
                out.append(c)
            i += 1
    if depth:
        raise ValueError("unbalanced '(' in movetext")
    return "".join(out)


def _tokenize(movetext: str) -> List[str]:
    cleaned = _strip_comments_and_variations(movetext)
    nags = re.compile(r"\$\d+")
    tokens = []
    for raw in cleaned.split():
        token = MOVE_NO_RE.sub("", raw, count=1)
        token = nags.sub("", token)
        token = token.lstrip(".")
        if not token or RESULT_RE.match(token):
            continue
        tokens.append(token)
    return tokens


def _result_of(movetext: str) -> str:
    cleaned = _strip_comments_and_variations(movetext)
    for raw in reversed(cleaned.split()):
        if RESULT_RE.match(raw):
            return raw
        token = MOVE_NO_RE.sub("", raw, count=1)
        if token and RESULT_RE.match(token):
            return token
    return "*"


def _parse_movetext(headers: dict, raw: str) -> Game:
    game = Game(dict(headers))
    result = _result_of(raw)
    if result != "*":
        game.result = result
    tokens = _tokenize(raw)
    if not tokens:
        raise ValueError("no moves found: %r" % headers.get("Event", ""))
    try:
        position = Position.from_fen(game.start_fen)
    except Exception as err:
        raise ValueError("bad FEN for game %r: %s" % (headers.get("Event", ""), err))
    white = position.white_to_move
    number = position.fullmove
    for token in tokens:
        move = position.parse_san(token)
        canonical = position.san_for(move)
        fen_before = position.to_fen()
        key_before = position.position_key()
        after = position.apply(move)
        game.add_ply(
            number,
            canonical,
            move,
            fen_before,
            after.to_fen(),
            key_before,
            "white" if white else "black",
        )
        position = after
        if white:
            white = False
        else:
            white = True
            number += 1
    game.headers.setdefault("Result", game.result)
    return game
