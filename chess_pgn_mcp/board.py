"""Lightweight chess board logic: FEN handling, move generation, SAN parsing.

Part of the Chess PGN MCP Server by Asdale Dynamics, LLC.
Standard library only. Education-only project; no chess engine, no external deps.
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

FILES = "abcdefgh"
RANKS = "87654321"  # index 0 is rank 8 (top of the board)


class Move(NamedTuple):
    """A move on the 64-square board (a8 = 0, h1 = 63)."""

    origin: int
    target: int
    promotion: Optional[str] = None  # one of "QRBN"
    is_castle: Optional[str] = None  # "K" kingside or "Q" queenside
    is_en_passant: bool = False


class IllegalMove(ValueError):
    """Raised when a SAN token cannot be matched to any legal move."""


class ParseError(ValueError):
    """Raised when a SAN token is not well-formed."""


def square_index(name: str) -> int:
    """'e4' -> 28."""
    file = FILES.index(name[0])
    rank = RANKS.index(name[1])
    return rank * 8 + file


def square_name(idx: int) -> str:
    return FILES[idx % 8] + RANKS[idx // 8]


def file_of(idx: int) -> int:
    return idx % 8


def rank_of(idx: int) -> int:
    return idx // 8


ROOK_DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))

KNIGHT_OFFSETS = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))
KING_OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

SAN_RE = re.compile(
    r"^(?P<pc>[KQRBN])?(?P<fromf>[a-h])?(?P<fromr>[1-8])?"
    r"(?P<cap>[x:])?(?P<to>[a-h][1-8])(?:=?\+?(?P<promo>[QRBNqrbn]))?$"
)

CASTLE_RE = re.compile(r"^(O-O-O|O-O|0-0-0|0-0)$")

ANNO_RE = re.compile(r"[+#?!]+$")


class Position:
    """A chess position.

    White pieces are uppercase (PNBRQK), black lowercase. Index i is
    rank RANKS[i // 8] and file FILES[i % 8] (a8 = 0, h1 = 63).
    """

    def __init__(self) -> None:
        self.squares: list = [""] * 64
        self.white_to_move = True
        self.castling: set = set()  # subset of {"K","Q","k","q"}
        self.ep: Optional[int] = None  # en-passant target square, or None
        self.halfmove = 0
        self.fullmove = 1

    # ---------------------------------------------------------------- FEN

    @classmethod
    def from_fen(cls, fen: str) -> "Position":
        parts = fen.split()
        if len(parts) != 6:
            raise ParseError("FEN must have 6 fields: %r" % fen)
        placement, side, castling, ep, halfmove, fullmove = parts
        pos = cls()
        rows = placement.split("/")
        if len(rows) != 8:
            raise ParseError("FEN placement must have 8 rows")
        for r, row in enumerate(rows):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif ch in "pnbrqkPNBRQK":
                    if f > 7:
                        raise ParseError("FEN row too long: %r" % row)
                    pos.squares[r * 8 + f] = ch
                    f += 1
                else:
                    raise ParseError("bad FEN character %r" % ch)
            if f != 8:
                raise ParseError("FEN row wrong length: %r" % row)
        if side not in ("w", "b"):
            raise ParseError("FEN side to move must be w or b")
        pos.white_to_move = side == "w"
        pos.castling = set(castling) & {"K", "Q", "k", "q"} if castling != "-" else set()
        pos.ep = None if ep == "-" else square_index(ep)
        try:
            pos.halfmove = int(halfmove)
            pos.fullmove = int(fullmove)
        except ValueError:
            raise ParseError("FEN counters must be integers")
        if pos.king_square(True) is None or pos.king_square(False) is None:
            raise ParseError("FEN must contain both kings")
        return pos

    def to_fen(self) -> str:
        rows = []
        for r in range(8):
            row = ""
            empty = 0
            for f in range(8):
                piece = self.squares[r * 8 + f]
                if piece:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += piece
                else:
                    empty += 1
            if empty:
                row += str(empty)
            rows.append(row)
        castling = "".join(c for c in "KQkq" if c in self.castling) or "-"
        ep = square_name(self.ep) if self.ep is not None else "-"
        return "%s %s %s %s %d %d" % (
            "/".join(rows),
            "w" if self.white_to_move else "b",
            castling,
            ep,
            self.halfmove,
            self.fullmove,
        )

    def position_key(self) -> str:
        """First four FEN fields; ep normalized to '-' when no ep capture is possible."""
        fields = self.to_fen().split()
        ep = fields[3]
        if ep != "-" and not any(m.is_en_passant for m in self.generate_legal_moves()):
            ep = "-"
        return " ".join(fields[:3] + [ep])

    # ------------------------------------------------------------ helpers

    def piece_at(self, idx: int) -> str:
        return self.squares[idx]

    def king_square(self, white: bool) -> Optional[int]:
        target = "K" if white else "k"
        for i, piece in enumerate(self.squares):
            if piece == target:
                return i
        return None

    def is_attacked(self, idx: int, by_white: bool) -> bool:
        """True if square ``idx`` is attacked by any piece of the given color."""
        r, f = rank_of(idx), file_of(idx)
        squares = self.squares

        if by_white:
            if r < 7:
                if f > 0 and squares[idx + 7] == "P":
                    return True
                if f < 7 and squares[idx + 9] == "P":
                    return True
        else:
            if r > 0:
                if f > 0 and squares[idx - 9] == "p":
                    return True
                if f < 7 and squares[idx - 7] == "p":
                    return True

        knight = "N" if by_white else "n"
        for dr, df in KNIGHT_OFFSETS:
            rr, ff = r + dr, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and squares[rr * 8 + ff] == knight:
                return True

        king = "K" if by_white else "k"
        for dr, df in KING_OFFSETS:
            rr, ff = r + dr, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and squares[rr * 8 + ff] == king:
                return True

        rook_queens = ("R", "Q") if by_white else ("r", "q")
        bishop_queens = ("B", "Q") if by_white else ("b", "q")
        for dirs, matches in ((ROOK_DIRS, rook_queens), (BISHOP_DIRS, bishop_queens)):
            for dr, df in dirs:
                rr, ff = r + dr, f + df
                while 0 <= rr < 8 and 0 <= ff < 8:
                    piece = squares[rr * 8 + ff]
                    if piece:
                        if piece in matches:
                            return True
                        break
                    rr += dr
                    ff += df
        return False

    def in_check(self, white: bool) -> bool:
        ks = self.king_square(white)
        if ks is None:
            raise ParseError("no %s king on the board" % ("white" if white else "black"))
        return self.is_attacked(ks, not white)

    def side_in_check(self) -> bool:
        return self.in_check(self.white_to_move)

    # --------------------------------------------------- move generation

    def _pawn_moves(self, idx: int, white: bool, out: list) -> None:
        step = -1 if white else 1
        start_rank = 6 if white else 1
        promo_rank = 0 if white else 7
        r, f = rank_of(idx), file_of(idx)

        one = (r + step) * 8 + f
        if not self.squares[one]:
            if r + step == promo_rank:
                for promo in "QRBN":
                    out.append(Move(idx, one, promotion=promo))
            else:
                out.append(Move(idx, one))
                if r == start_rank:
                    two = (r + 2 * step) * 8 + f
                    if not self.squares[two]:
                        out.append(Move(idx, two))

        for df in (-1, 1):
            ff, rr = f + df, r + step
            if not (0 <= ff < 8 and 0 <= rr < 8):
                continue
            target = rr * 8 + ff
            piece = self.squares[target]
            if piece and piece.isupper() != white:
                if rr == promo_rank:
                    for promo in "QRBN":
                        out.append(Move(idx, target, promotion=promo))
                else:
                    out.append(Move(idx, target))
            elif not piece and target == self.ep and self.ep is not None:
                out.append(Move(idx, target, is_en_passant=True))

    def generate_pseudo_moves(self) -> list:
        """All pseudo-legal moves for the side to move (king safety unverified)."""
        out: list = []
        white = self.white_to_move
        squares = self.squares
        for idx, piece in enumerate(squares):
            if not piece or piece.isupper() != white:
                continue
            kind = piece.upper()
            r, f = rank_of(idx), file_of(idx)

            if kind == "P":
                self._pawn_moves(idx, white, out)
            elif kind in ("N", "K"):
                offsets = KNIGHT_OFFSETS if kind == "N" else KING_OFFSETS
                for dr, df in offsets:
                    rr, ff = r + dr, f + df
                    if 0 <= rr < 8 and 0 <= ff < 8:
                        target = rr * 8 + ff
                        occupant = squares[target]
                        if not occupant or occupant.isupper() != white:
                            out.append(Move(idx, target))
            else:
                dirs = {"B": BISHOP_DIRS, "R": ROOK_DIRS, "Q": BISHOP_DIRS + ROOK_DIRS}[kind]
                for dr, df in dirs:
                    rr, ff = r + dr, f + df
                    while 0 <= rr < 8 and 0 <= ff < 8:
                        target = rr * 8 + ff
                        occupant = squares[target]
                        if not occupant:
                            out.append(Move(idx, target))
                        else:
                            if occupant.isupper() != white:
                                out.append(Move(idx, target))
                            break
                        rr += dr
                        ff += df

        self._add_castling_moves(out)
        return out

    def _add_castling_moves(self, out: list) -> None:
        white = self.white_to_move
        rank = 7 if white else 0
        rook, king = ("R", "K") if white else ("r", "k")
        back = rank * 8

        kingside_right = "K" if white else "k"
        queenside_right = "Q" if white else "q"
        ks = self.king_square(white)
        if ks != back + 4 or self.squares[ks] != king:
            return

        if kingside_right in self.castling and self.squares[back + 7] == rook:
            if not self.squares[back + 5] and not self.squares[back + 6]:
                if all(
                    not self.is_attacked(i, not white)
                    for i in (back + 4, back + 5, back + 6)
                ):
                    out.append(Move(ks, back + 6, is_castle="K"))

        if queenside_right in self.castling and self.squares[back] == rook:
            if all(not self.squares[i] for i in (back + 1, back + 2, back + 3)):
                if all(
                    not self.is_attacked(i, not white)
                    for i in (back + 2, back + 3, back + 4)
                ):
                    out.append(Move(ks, back + 2, is_castle="Q"))

    def apply(self, move: Move) -> "Position":
        """Return the position after playing ``move`` (legality not re-checked)."""
        if not (0 <= move.origin < 64 and 0 <= move.target < 64):
            raise IllegalMove("move indices out of range")

        white = self.white_to_move
        piece = self.squares[move.origin]
        if not piece:
            raise IllegalMove("empty origin square %s" % square_name(move.origin))
        if piece.isupper() != white:
            raise IllegalMove("it is not that side's turn")

        pos = Position()
        pos.squares = list(self.squares)

        captured = self.squares[move.target]
        if move.is_en_passant:
            victim = move.target + (8 if white else -8)
            captured = self.squares[victim]
            pos.squares[victim] = ""
        elif move.is_castle:
            back = (7 if white else 0) * 8
            if move.is_castle == "K":
                pos.squares[back + 7] = ""
                pos.squares[back + 5] = "R" if white else "r"
            else:
                pos.squares[back] = ""
                pos.squares[back + 3] = "R" if white else "r"

        pos.squares[move.origin] = ""
        if move.promotion:
            pos.squares[move.target] = move.promotion if white else move.promotion.lower()
        else:
            pos.squares[move.target] = piece

        # Castling rights: drop when king or a rook's home square is involved.
        rights = set(self.castling)
        if piece == "K":
            rights -= {"K", "Q"}
        elif piece == "k":
            rights -= {"k", "q"}
        for sq, lost in ((56, "Q"), (63, "K"), (0, "q"), (7, "k")):
            if move.origin == sq or move.target == sq:
                rights.discard(lost)
        pos.castling = rights

        pos.ep = None
        if piece in ("P", "p") and abs(move.target - move.origin) == 16:
            pos.ep = (move.origin + move.target) // 2

        pos.halfmove = 0 if (piece in ("P", "p") or captured) else self.halfmove + 1
        if not white:
            pos.fullmove = self.fullmove + 1
        pos.white_to_move = not white
        return pos

    def generate_legal_moves(self) -> list:
        """Pseudo-legal moves filtered so the mover's king is never left in check."""
        white = self.white_to_move
        legal = []
        for move in self.generate_pseudo_moves():
            if not self.apply(move).in_check(white):
                legal.append(move)
        return legal

    # ------------------------------------------------------------ SAN

    def parse_san(self, san: str) -> Move:
        """Resolve a SAN token (with any trailing +/#/!/? punctuation) to a legal move."""
        if not san:
            raise ParseError("empty SAN token")

        castle = CASTLE_RE.match(san)
        if castle:
            return self._parse_castle(castle.group(1))

        token = ANNO_RE.sub("", san)
        if token and token[-1] in "+#":
            token = token[:-1]
        match = SAN_RE.match(token)
        if not match:
            raise ParseError("cannot read SAN token %r" % san)

        sa = match.groupdict()
        target = square_index(sa["to"])
        piece_type = sa["pc"] or "P"
        promo = sa["promo"] and sa["promo"].upper()

        candidates = []
        for move in self.generate_legal_moves():
            if move.target != target or move.is_castle:
                continue
            moving = self.squares[move.origin].upper()
            if moving != piece_type:
                continue
            if (move.promotion or None) != (promo if move.promotion else None):
                if move.promotion and move.promotion != (promo or ""):
                    continue
            if sa["fromf"] and file_of(move.origin) != FILES.index(sa["fromf"]):
                continue
            if sa["fromr"] and rank_of(move.origin) != RANKS.index(sa["fromr"]):
                continue
            is_capture = bool(self.squares[move.target]) or move.is_en_passant
            if sa["cap"] and not is_capture:
                continue
            candidates.append((is_capture, move))

        if not candidates:
            raise IllegalMove("illegal move: %s (%s)" % (san, self.to_fen().split()[0]))
        exact = [m for cap, m in candidates if cap == bool(sa["cap"])] or [m for _, m in candidates]
        if len(exact) > 1:
            raise IllegalMove("ambiguous SAN: %s (%s)" % (san, self.to_fen().split()[0]))
        return exact[0]

    def _parse_castle(self, token: str) -> Move:
        kingside = token == "O-O" or token == "0-0"
        white = self.white_to_move
        ks = self.king_square(white)
        kingchar = "K" if white else "k"
        if ks is None or self.squares[ks] != kingchar:
            raise IllegalMove("castling without a king: %s" % token)
        legal = {m.is_castle: m for m in self.generate_legal_moves() if m.is_castle}
        want = "K" if kingside else "Q"
        if want not in legal:
            raise IllegalMove("illegal castling: %s (%s)" % (token, self.to_fen().split()[0]))
        return legal[want]

    def san_for(self, move: Move) -> str:
        """Standard algebraic notation for a legal move in this position."""
        if move.is_castle:
            suffix = self._check_suffix(move)
            return ("O-O" if move.is_castle == "K" else "O-O-O") + suffix

        piece = self.squares[move.origin]
        kind = piece.upper()
        is_capture = bool(self.squares[move.target]) or move.is_en_passant

        if kind == "P":
            text = FILES[file_of(move.origin)] + "x" if is_capture else ""
            if is_capture:
                text += square_name(move.target)
            else:
                text = square_name(move.target)
            if move.promotion:
                text += "=" + move.promotion
        else:
            text = kind
            cands = [
                m
                for m in self.generate_legal_moves()
                if m.target == move.target
                and m.is_castle is None
                and self.squares[m.origin].upper() == kind
                and m.origin != move.origin
            ]
            if cands:
                same_file = any(file_of(m.origin) == file_of(move.origin) for m in cands)
                same_rank = any(rank_of(m.origin) == rank_of(move.origin) for m in cands)
                if not same_file:
                    text += FILES[file_of(move.origin)]
                elif not same_rank:
                    text += RANKS[rank_of(move.origin)]
                else:
                    text += square_name(move.origin)
            if is_capture:
                text += "x"
            text += square_name(move.target)
            if move.promotion:
                text += "=" + move.promotion
        return text + self._check_suffix(move)

    def _check_suffix(self, move: Move) -> str:
        after = self.apply(move)
        if not after.side_in_check():
            return ""
        return "#" if not after.generate_legal_moves() else "+"
