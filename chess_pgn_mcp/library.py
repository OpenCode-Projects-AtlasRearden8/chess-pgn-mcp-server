"""Local PGN game library: store, tag, search, stats, position lookup, export.

Part of the Chess PGN MCP Server by Asdale Dynamics, LLC.
All data is stored locally as plain files, nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Dict, List, Optional, Tuple

from .pgn import Game, parse_pgn

RESULTS = ("1-0", "0-1", "1/2-1/2", "*")

INDEX_VERSION = 1


class LibraryError(ValueError):
    """Raised for invalid input or missing games."""


class Library:
    """A folder holding PGN files plus an index.json for fast searching.

    Layout::

        <root>/
            index.json      -- metadata, tags, and the position index
            games/<id>.pgn  -- the original PGN, one file per game
            exports/        -- filtered collections written here
    """

    def __init__(self, root: str):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.games_dir = os.path.join(self.root, "games")
        self.exports_dir = os.path.join(self.root, "exports")
        self.index_path = os.path.join(self.root, "index.json")
        os.makedirs(self.games_dir, exist_ok=True)
        os.makedirs(self.exports_dir, exist_ok=True)
        self.index: dict = {"version": INDEX_VERSION, "games": []}
        self._load()

    # ---------------------------------------------------------------- storage

    def _load(self) -> None:
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as fh:
                    self.index = json.load(fh)
            except (OSError, json.JSONDecodeError):
                self._rebuild_index()
        if self.index.get("version") != INDEX_VERSION or "games" not in self.index:
            self._rebuild_index()

    def _save(self) -> None:
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.index, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, self.index_path)

    def _rebuild_index(self) -> None:
        """Re-derive index.json from the games folder (crash recovery)."""
        games = []
        if os.path.isdir(self.games_dir):
            for name in sorted(os.listdir(self.games_dir)):
                if not name.endswith(".pgn"):
                    continue
                path = os.path.join(self.games_dir, name)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        text = fh.read()
                    parsed = parse_pgn(text)
                    if len(parsed) != 1:
                        raise LibraryError("game file must hold exactly one game")
                    raw_tags = parsed[0].headers.get("LibraryTags", "")
                    tags = [t for t in raw_tags.split("|") if t]
                    games.append(_entry_from_game(os.path.splitext(name)[0], parsed[0], tags))
                except (OSError, ValueError):
                    continue
        self.index = {"version": INDEX_VERSION, "games": games}
        self._save()

    # ------------------------------------------------------------ store / tags

    def store_pgn(self, pgn: str, tags: Optional[List[str]] = None) -> List[dict]:
        """Parse, validate, and store PGN text (one or more games)."""
        if not pgn or not pgn.strip():
            raise LibraryError("no PGN text provided")
        try:
            parsed = parse_pgn(pgn)
        except ValueError as err:
            raise LibraryError("invalid PGN: %s" % err)
        stored = []
        for game in parsed:
            game_id = "g" + uuid.uuid4().hex[:10]
            normal_tags = [_norm_tag(t) for t in (tags or []) if t]
            if normal_tags:
                game.headers["LibraryTags"] = "|".join(normal_tags)
            path = os.path.join(self.games_dir, game_id + ".pgn")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(game.to_pgn())
            entry = _entry_from_game(game_id, game, normal_tags)
            self.index["games"].append(entry)
            stored.append(_summarize(entry))
        self._save()
        return stored

    def delete_game(self, game_id: str) -> bool:
        entry = self._entry(game_id)
        path = os.path.join(self.games_dir, game_id + ".pgn")
        if os.path.exists(path):
            os.remove(path)
        self.index["games"].remove(entry)
        self._save()
        return True

    def tag_game(self, game_id: str, add: Optional[List[str]] = None,
                 remove: Optional[List[str]] = None) -> dict:
        entry = self._entry(game_id)
        current = entry["tags"]
        for tag in add or []:
            tag = _norm_tag(tag)
            if tag and tag not in current:
                current.append(tag)
        for tag in remove or []:
            tag = _norm_tag(tag)
            current[:] = [t for t in current if t != tag]
        entry["headers"]["LibraryTags"] = "|".join(current) or ""
        self._rewrite_pgn(entry)
        self._save()
        return _summarize(entry)

    def _rewrite_pgn(self, entry: dict) -> None:
        """Refresh a stored PGN file from its index headers (tags can change)."""
        path = os.path.join(self.games_dir, entry["id"] + ".pgn")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        try:
            parsed = parse_pgn(text)
            parsed[0].headers.update(entry["headers"])
            if entry["result"] in RESULTS and entry["result"] != "*":
                parsed[0].headers["Result"] = entry["result"]
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(parsed[0].to_pgn())
        except ValueError:
            pass  # leave the file untouched if it can no longer be parsed

    # ------------------------------------------------------------- searching

    def search(
        self,
        player: Optional[str] = None,
        color: Optional[str] = None,
        opening: Optional[str] = None,
        result: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """Find games by player, side, opening, result and/or tag."""
        if color and color not in ("white", "black"):
            raise LibraryError("color must be 'white' or 'black'")
        if result is not None and result not in RESULTS and result != "any":
            raise LibraryError("result must be one of %s" % (", ".join(RESULTS)))
        matches = []
        for entry in self.index["games"]:
            if not _entry_matches(entry, player, color, opening, result, tag):
                continue
            matches.append(entry)
            if len(matches) >= max(1, limit):
                break
        return [_summarize(e) for e in matches]

    def player_stats(self, player: str) -> dict:
        player_l = player.strip().lower()
        if not player_l:
            raise LibraryError("player name is required")
        games = [
            e
            for e in self.index["games"]
            if (e["white"].strip().lower() == player_l)
            or (e["black"].strip().lower() == player_l)
        ]
        stats = {
            "player": player,
            "games": len(games),
            "as_white": 0,
            "as_black": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "undecided": 0,
            "total_plies": 0,
            "avg_plies": 0.0,
            "openings": {},
            "opponents": {},
            "wins_by_opening": {},
        }
        for entry in games:
            white = entry["white"].strip()
            black = entry["black"].strip()
            as_white = white.lower() == player_l
            if as_white:
                stats["as_white"] += 1
            else:
                stats["as_black"] += 1
            result = entry["result"]
            if result == "1-0":
                outcome = "win" if as_white else "loss"
            elif result == "0-1":
                outcome = "loss" if as_white else "win"
            elif result == "1/2-1/2":
                outcome = "draw"
            else:
                outcome = "undecided"
            outcome = {
                "win": "wins",
                "loss": "losses",
                "draw": "draws",
                "undecided": "undecided",
            }[outcome]
            stats[outcome] += 1
            stats["total_plies"] += entry["plies"]
            opening = entry["opening"]
            if opening:
                stats["openings"][opening] = stats["openings"].get(opening, 0) + 1
                if outcome == "win":
                    stats["wins_by_opening"][opening] = (
                        stats["wins_by_opening"].get(opening, 0) + 1
                    )
            opponent = black if as_white else white
            stats["opponents"][opponent] = stats["opponents"].get(opponent, 0) + 1
        if stats["games"]:
            stats["avg_plies"] = round(stats["total_plies"] / stats["games"], 1)
        for key in ("openings", "opponents", "wins_by_opening"):
            stats[key] = dict(
                sorted(stats[key].items(), key=lambda kv: kv[1], reverse=True)
            )
        return stats

    def lookup_position(self, fen: str) -> List[dict]:
        """Games where this exact position occurs (placement, side, castling, ep)."""
        norm = _normalize_fen(fen)
        hits = []
        for entry in self.index["games"]:
            where = [
                p
                for p in entry["positions"]
                if p["key"] == norm
            ]
            if where:
                hits.append(
                    {
                        "game_id": entry["id"],
                        "white": entry["white"],
                        "black": entry["black"],
                        "event": entry["headers"].get("Event", ""),
                        "opening": entry["opening"],
                        "tags": entry["tags"],
                        "ply_moves": where[0]["moves"],
                        "move_number": where[0]["number"],
                        "count": len(where),
                    }
                )
        return hits

    def export_games(
        self,
        player: Optional[str] = None,
        color: Optional[str] = None,
        opening: Optional[str] = None,
        result: Optional[str] = None,
        tag: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> Tuple[int, Optional[str]]:
        """Export matching games as PGN text; optionally save into exports/."""
        entries = [
            e
            for e in self.index["games"]
            if _entry_matches(e, player, color, opening, result, tag)
        ]
        parts = []
        for entry in entries:
            path = os.path.join(self.games_dir, entry["id"] + ".pgn")
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    parts.append(fh.read().strip())
            except OSError:
                continue
        text = "\n\n".join(parts) + ("\n" if parts else "")
        saved = None
        if file_name:
            safe = _safe_filename(file_name)
            if not safe:
                raise LibraryError("bad export file name")
            saved = os.path.join(self.exports_dir, safe)
            with open(saved, "w", encoding="utf-8") as fh:
                fh.write(text)
        return len(entries), saved

    def list_tags(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.index["games"]:
            for tag in entry["tags"]:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (kv[0].lower(), kv[0])))

    def info(self) -> dict:
        return {
            "library_dir": self.root,
            "game_count": len(self.index["games"]),
            "tags": self.list_tags(),
        }

    def get_game(self, game_id: str) -> dict:
        """Full game record incl. per-move SAN/FEN listing (for game previews)."""
        entry = self._entry(game_id)
        path = os.path.join(self.games_dir, game_id + ".pgn")
        pgn_text = ""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                pgn_text = fh.read()
        summary = _summarize(entry)
        summary["pgn"] = pgn_text.strip()
        summary["moves"] = [
            {"num": p["number"], "player": p["player"], "san": p["moves"], "fen": p["fen"]}
            for p in entry["positions"]
            if p["player"] != "end"
        ]
        return summary

    def _entry(self, game_id: str) -> dict:
        for entry in self.index["games"]:
            if entry["id"] == game_id:
                return entry
        raise LibraryError("no game with id %r" % game_id)


# ------------------------------------------------------------------- helpers


def _entry_from_game(game_id: str, game: Game, tags: List[str]) -> dict:
    positions = []
    for ply in game.plies:
        positions.append(
            {
                "key": ply.key_before,
                "fen": ply.fen_before,
                "number": ply.number,
                "moves": ply.san,
                "player": ply.player,
            }
        )
    # Index the final position too (lookup should find *the position after* 17.Rd8#).
    from .board import Position

    if game.plies:
        final = Position.from_fen(game.plies[-1].fen_after)
        positions.append(
            {
                "key": final.position_key(),
                "fen": final.to_fen(),
                "number": game.plies[-1].number,
                "moves": "",
                "player": "end",
            }
        )
    return {
        "id": game_id,
        "headers": dict(game.headers),
        "white": game.white,
        "black": game.black,
        "result": game.result,
        "opening": game.opening,
        "plies": len(game.plies),
        "start_fen": game.start_fen,
        "final_fen": game.plies[-1].fen_after if game.plies else game.start_fen,
        "tags": [_norm_tag(t) for t in tags if t],
        "positions": positions,
    }


def _norm_tag(tag: str) -> str:
    return re.sub(r"\s+", "-", str(tag).strip().lower())[:64]


def _summarize(entry: dict) -> dict:
    return {
        "game_id": entry["id"],
        "white": entry["white"],
        "black": entry["black"],
        "result": entry["result"],
        "opening": entry["opening"],
        "event": entry["headers"].get("Event", ""),
        "date": entry["headers"].get("Date", ""),
        "plies": entry["plies"],
        "tags": list(entry["tags"]),
    }


def _entry_matches(
    entry: dict,
    player: Optional[str],
    color: Optional[str],
    opening: Optional[str],
    result: Optional[str],
    tag: Optional[str],
) -> bool:
    if player:
        needle = player.strip().lower()
        side_ok = needle in entry["white"].strip().lower() or needle in entry["black"].strip().lower()
        if not side_ok:
            return False
    if color:
        if not player:
            raise LibraryError("color filter requires a player")
        side = entry["white"].strip().lower() if color == "white" else entry["black"].strip().lower()
        if not (player.strip().lower() in side or side in player.strip().lower()):
            return False
    if opening:
        if opening.strip().lower() not in entry["opening"].lower():
            return False
    if result and result != "any" and entry["result"] != result:
        return False
    if tag:
        if _norm_tag(tag) not in entry["tags"]:
            return False
    return True


def _normalize_fen(fen: str) -> str:
    """Position key for a user-supplied FEN (placement/side/castling/ep only)."""
    from .board import Position

    fen = fen.strip()
    parts = fen.split()
    while len(parts) < 6:
        if len(parts) == 1:
            parts.append("w")
        elif len(parts) == 2:
            parts.append("-")
        elif len(parts) == 3:
            parts.append("-")
        else:
            parts.append("0")
    if len(parts) > 6:
        parts = parts[:6]
    pos = Position.from_fen(" ".join(parts))
    return pos.position_key()


def _safe_filename(name: str) -> str:
    if not name or "\x00" in name:
        return ""
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")
    return (stem[:96] + ".pgn") if stem else ""
