"""MCP stdio server for the local chess PGN library.

Part of the Chess PGN MCP Server by Asdale Dynamics, LLC.
Speaks newline-delimited JSON-RPC 2.0 (Model Context Protocol) on stdin/stdout.

Protocol methods: initialize, ping, tools/list, tools/call.
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

from .board import START_FEN, IllegalMove, ParseError
from .library import Library, LibraryError, RESULTS

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "chess-pgn-mcp-server"
SERVER_VERSION = "1.0.0"

DEFAULT_LIBRARY_DIR = os.path.join(
    os.path.expanduser("~"), ".chess_pgn_library"
)


def default_library_dir() -> str:
    return os.environ.get("CHESS_PGN_LIBRARY_DIR") or DEFAULT_LIBRARY_DIR


# --------------------------------------------------------------- tool schemas

def _schema(properties: dict, required: List[str]) -> dict:
    schema = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


FILTER_PROP = {
    "opening": {"type": "string", "description": "Opening name or part of one (e.g. 'Sicilian')"},
    "result": {"type": "string", "enum": list(RESULTS[:3]), "description": "Game result filter"},
    "tag": {"type": "string", "description": "Library tag filter"},
}

PLAYER_PROPS = {
    "player": {"type": "string", "description": "Player name (matches White or Black)"},
    "color": {
        "type": "string",
        "enum": ["white", "black"],
        "description": "Restrict the player to one color (player required)",
    },
}

GAME_FILTER_PROPS = {
    **PLAYER_PROPS,
    **FILTER_PROP,
}

TOOLS = [
    {
        "name": "store_pgn",
        "description": (
            "Validate and store PGN text (one or more games) in the local "
            "library, optionally tagging them. Returns game ids and summaries."
        ),
        "inputSchema": _schema(
            {
                "pgn": {"type": "string", "description": "Full PGN text, may contain several games"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            ["pgn"],
        ),
    },
    {
        "name": "tag_game",
        "description": "Add and/or remove tags on a stored game.",
        "inputSchema": _schema(
            {
                "game_id": {"type": "string"},
                "add_tags": {"type": "array", "items": {"type": "string"}},
                "remove_tags": {"type": "array", "items": {"type": "string"}},
            },
            ["game_id"],
        ),
    },
    {
        "name": "search_games",
        "description": "Search stored games by player, color, opening, result, and/or tag.",
        "inputSchema": _schema(
            {**GAME_FILTER_PROPS, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}},
            [],
        ),
    },
    {
        "name": "get_game",
        "description": "Full record for one game: headers, tags, move list with FENs, PGN text.",
        "inputSchema": _schema({"game_id": {"type": "string"}}, ["game_id"]),
    },
    {
        "name": "player_stats",
        "description": "Per-player stats: game counts, wins/losses/draws, top openings and opponents.",
        "inputSchema": _schema({"player": {"type": "string"}}, ["player"]),
    },
    {
        "name": "lookup_position",
        "description": (
            "Find stored games that contain a position (by FEN; only placement, "
            "side to move, castling, and en-passant fields matter)."
        ),
        "inputSchema": _schema({"fen": {"type": "string"}}, ["fen"]),
    },
    {
        "name": "export_games",
        "description": (
            "Export matching games as PGN text; optionally save the collection "
            "inside the library's exports folder."
        ),
        "inputSchema": _schema(
            {
                **GAME_FILTER_PROPS,
                "file_name": {
                    "type": "string",
                    "description": "Optional file to save under <library>/exports/",
                },
            },
            [],
        ),
    },
    {
        "name": "list_tags",
        "description": "List all tags in the library with counts.",
        "inputSchema": _schema({}, []),
    },
    {
        "name": "library_info",
        "description": "Library location, game count, and tag summary.",
        "inputSchema": _schema({}, []),
    },
    {
        "name": "delete_game",
        "description": "Remove a game from the library (its PGN file is deleted too).",
        "inputSchema": _schema({"game_id": {"type": "string"}}, ["game_id"]),
    },
]


class ChessServer:
    """JSON-RPC 2.0 / MCP handler bound to a Library."""

    def __init__(self, library: Library):
        self.library = library
        self.initialized = False

    # -------------------------------------------------------------- dispatch

    def handle(self, message: str) -> Optional[dict]:
        """Handle one JSON-RPC message; returns the response dict or None."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return _error_response(None, -32700, "parse error")
        if not isinstance(data, dict):
            return _error_response(None, -32600, "invalid request")
        method = data.get("method")
        msg_id = data.get("id")
        params = data.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested == PROTOCOL_VERSION else PROTOCOL_VERSION
            self.initialized = True
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            return self._call_tool(msg_id, params)
        if method.startswith("notifications/"):
            return None
        return _error_response(msg_id, -32601, "method not found: %s" % method)

    def _call_tool(self, msg_id, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = self._tool_handlers().get(name)
        if handler is None:
            return _error_response(msg_id, -32602, "unknown tool: %s" % name)
        try:
            result = handler(args)
            content = [{"type": "text", "text": _to_text(result)}]
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"content": content, "isError": False}}
        except (LibraryError, IllegalMove, ParseError) as tool_error:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": "Error: %s" % tool_error}],
                    "isError": True,
                },
            }
        except Exception as unexpected:  # tool boundary; never crash the server
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": "Error: %r" % unexpected}],
                    "isError": True,
                },
            }

    # ------------------------------------------------------------ tool impls

    def _tool_handlers(self):
        return {
            "store_pgn": self._tool_store,
            "tag_game": self._tool_tag,
            "search_games": self._tool_search,
            "get_game": self._tool_get,
            "player_stats": self._tool_stats,
            "lookup_position": self._tool_lookup,
            "export_games": self._tool_export,
            "list_tags": self._tool_list_tags,
            "library_info": self._tool_info,
            "delete_game": self._tool_delete,
        }

    def _tool_store(self, args: dict) -> dict:
        count = self.library.store_pgn(args["pgn"], args.get("tags") or [])
        return {"stored": count, "library_total": len(self.library.index["games"])}

    def _tool_tag(self, args: dict) -> dict:
        return self.library.tag_game(
            args["game_id"], add=args.get("add_tags") or [], remove=args.get("remove_tags") or []
        )

    def _tool_search(self, args: dict) -> dict:
        games = self.library.search(
            player=args.get("player"),
            color=args.get("color"),
            opening=args.get("opening"),
            result=args.get("result"),
            tag=args.get("tag"),
            limit=args.get("limit", 50),
        )
        return {"found": len(games), "games": games}

    def _tool_get(self, args: dict) -> dict:
        return self.library.get_game(args["game_id"])

    def _tool_stats(self, args: dict) -> dict:
        return self.library.player_stats(args["player"])

    def _tool_lookup(self, args: dict) -> dict:
        hits = self.library.lookup_position(args["fen"]) if args.get("fen") else []
        if not args.get("fen"):
            raise LibraryError("fen is required (use START_FEN for from-scratch games: %s)" % START_FEN)
        return {"found": len(hits), "games": hits}

    def _tool_export(self, args: dict) -> dict:
        n, saved = self.library.export_games(
            player=args.get("player"),
            color=args.get("color"),
            opening=args.get("opening"),
            result=args.get("result"),
            tag=args.get("tag"),
            file_name=args.get("file_name"),
        )
        out = {"exported": n}
        if saved:
            out["saved_to"] = saved
        return out

    def _tool_list_tags(self, args: dict) -> dict:
        return {"tags": self.library.list_tags()}

    def _tool_info(self, args: dict) -> dict:
        return self.library.info()

    def _tool_delete(self, args: dict) -> dict:
        if not args.get("game_id"):
            raise LibraryError("game_id is required")
        self.library.delete_game(args["game_id"])
        return {"deleted": args["game_id"]}


def _error_response(msg_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id if msg_id is not None else None,
        "error": {"code": code, "message": message},
    }


def _to_text(result) -> str:
    return json.dumps(result, indent=1, ensure_ascii=False, default=str)


def serve(library: Optional[Library] = None, stdin=None, stdout=None) -> None:
    """Read JSON-RPC messages line by line; write responses and flush."""
    library = library or Library(default_library_dir())
    server = ChessServer(library)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        response = server.handle(line)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
