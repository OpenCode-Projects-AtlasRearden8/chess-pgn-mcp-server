# Chess PGN MCP Server

A local-first **MCP server** for your own chess game library: store and tag PGNs,
open games by player / opening / result, get per-player stats, look up positions,
and export filtered collections.

By **Asdale Dynamics, LLC** (Dylan Asdale's beginner-friendly AI hub,
[dylanasdale.github.io](https://dylanasdale.github.io)). Part of the Massive AI
Manual's "agents and MCP" family — a small, understandable MCP server you can
actually read, in plain English.

> **Education-only.** This is a study and library tool. It is not a chess engine,
> not a rating system, and it will not give you opening advice or tell you the
> "best move". No chess-engine dependency, no opening book, no AI model — just a
> friendly librarian for your PGN files.

## Why you might like it

- **Nothing to install**: Python 3.9+ and the standard library only. Really.
- **Nothing leaves your machine**: games live in plain `.pgn` files on disk, one
  folder, one index file. No accounts, no keys, no cloud.
- **Readable on purpose**: a lightweight PGN parser and a readable chess-rules
  core (`chess_pgn_mcp/board.py` — move generation, FEN, SAN) written to be
  studied, not feared.

## Requirements

- Python 3.9 or newer. That's the list.

## How to run it

```bash
# quick self-test: seed a temporary library from samples/ and print a summary
python3 -m chess_pgn_mcp --selftest

# start the MCP server (talks JSON-RPC over stdio)
python3 -m chess_pgn_mcp

# choose where your library lives
python3 -m chess_pgn_mcp --library /path/to/my-chess-library
# or set CHESS_PGN_LIBRARY_DIR in your environment
```

With no `--library` and no environment variable, games are stored in
`~/.chess_pgn_library`.

### Point an MCP client at it

Most MCP clients (Claude Desktop, and anything speaking the Model Context
Protocol) take a small config entry like this:

```json
{
  "mcpServers": {
    "chess-pgn": {
      "command": "python3",
      "args": ["-m", "chess_pgn_mcp"],
      "env": { "CHESS_PGN_LIBRARY_DIR": "/home/you/my-chess-library" },
      "cwd": "/path/to/chess-pgn-mcp-server"
    }
  }
}
```

The server speaks newline-delimited JSON-RPC 2.0 (stdio transport, protocol
version `2024-11-05`).

## The tools

| Tool | What it does |
| --- | --- |
| `store_pgn` | Validate and store PGN text (one file per game), optionally tagged |
| `tag_game` | Add or remove tags (`quick-mate`, `flowers-by-lasker`…) |
| `search_games` | Find games by player, color, opening, result, and/or tag |
| `get_game` | Full record: headers, tags, move list with FENs, PGN text |
| `player_stats` | Games, wins/losses/draws by color, favorite openings and opponents |
| `lookup_position` | "Which of my games contained this position?" (by FEN) |
| `export_games` | Export matching games as PGN text or save under `exports/` |
| `list_tags` | All tags with counts |
| `library_info` | Where the library is and what's in it |
| `delete_game` | Remove a game (its PGN file goes too) |

### Filtering works the same everywhere

`search_games` and `export_games` share the filter arguments:

- `player` — matches White or Black (case-insensitive substring)
- `color` — `"white"` or `"black"` (requires `player`)
- `opening` — substring of the `Opening` header
- `result` — `1-0`, `0-1`, or `1/2-1/2`
- `tag` — a library tag

Example export: *"all games tagged `classic` that Morphy won as White"*

```json
{ "player": "morphy", "color": "white", "result": "1-0", "tag": "classic", "file_name": "morphy-classic" }
```

## What it stores, and where

```
your-library/
├── index.json        # metadata, tags, and the position index (plain JSON)
├── games/            # one .pgn file per game (originals stay editable)
└── exports/          # filtered collections saved via export_games
```

Store errors are honest: an illegal move or a broken header means the game is
rejected with a message you can actually act on. If `index.json` is ever lost or
truncated, the library rebuilds it from the `.pgn` files (tag changes are also
written back into the PGN files, so nothing is trapped in the JSON).

## Samples and tests

`samples/` holds ready-to-try PGNs: the famous Morphy Opera Game (1858), a
fool's mate, a scholar's mate, a knight-shuffle draw, and a multi-game file.
The test suite replays every sample move by move and checks it all the way to
the final position.

```bash
python3 -m unittest discover -s tests -v
```

## Under the hood (for the curious)

- `board.py` — a small chess-rules core: FEN parsing/generation, pseudo-legal
  and legal move generation, en passant, castling with all its corner cases,
  promotion, SAN parsing and generation (including disambiguation). Validated
  against the standard "Kiwipete" test position.
- `pgn.py` — a lightweight PGN parser: headers with escape handling, comments,
  nested variations, NAGs, move numbers, and multi-game files.
- `library.py` — the local library: storage, tags, search, stats, position
  index, exports.
- `server.py` — the MCP protocol server (JSON-RPC 2.0 over stdio, ten tools).

## Known limitations

- No transposition table: position lookup is exact (`placement + side to move +
  castling + en passant`), not "same idea, moved a pawn differently".
- Large multi-game PGN files parse whole-file; modest size expected.
- The MCP surface is the practical subset (initialize / ping / tools/call); no
  resources or prompts are exposed.

## License

MIT — see `LICENSE`. **Copyright (c) 2026 Asdale Dynamics, LLC.** Built with
plain-English AI education in mind: *The Massive AI Manual* and
[dylanasdale.github.io](https://dylanasdale.github.io).
