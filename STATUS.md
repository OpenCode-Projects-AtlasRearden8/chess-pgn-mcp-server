# STATUS.md — Chess PGN MCP Server

Last updated: 2026-11-03 · Maintained by Asdale Dynamics, LLC

## What was built

A local-first **MCP server** (stdio JSON-RPC, protocol `2024-11-05`) that serves
a personal chess game library of PGN files. **Education-only**: no chess engine,
no opening book, no network calls — Python 3.9+ / standard library only.

Modules (`chess_pgn_mcp/`):

- `board.py` — readable chess-rules core: FEN round-trip, legal move generation
  (incl. castling with safety checks, en passant, promotion), SAN parsing/generation
  with disambiguation, position keys.
- `pgn.py` — lightweight PGN parser: headers with escapes, comments `{}` and `;`,
  nested variations, NAGs, move numbers, multi-game files, honest error messages.
- `library.py` — the local library: store/validate PGNs, tag, search
  (player/color/opening/result/tag), per-player stats, position lookup by FEN,
  filtered export, index auto-rebuild from PGN files.
- `server.py` — MCP protocol server exposing ten tools.
- `__main__.py` — CLI (`python3 -m chess_pgn_mcp [--library DIR] [--selftest] [--version]`).

### MCP tools

`store_pgn`, `tag_game`, `search_games`, `get_game`, `player_stats`,
`lookup_position`, `export_games`, `list_tags`, `library_info`, `delete_game`.

## How to run it

```bash
python3 -m unittest discover -s tests -v   # run the test suite
python3 -m chess_pgn_mcp --selftest        # seed a temp library from samples/
python3 -m chess_pgn_mcp --library /path   # start the MCP server on stdio
```

Library default: `$CHESS_PGN_LIBRARY_DIR` or `~/.chess_pgn_library`.
Sample games in `samples/` (Morphy Opera Game, fool's mate, scholar's mate,
knight-shuffle draw, multi-game file).

## Verification results

- `python3 -m unittest discover -s tests` — **60/60 tests pass** across four
  modules (board, PGN parser, library, MCP protocol + stdio round-trip).
- `python3 -m pyflakes chess_pgn_mcp tests` — clean (no unused imports/variables).
- Pyflakes/py_compile all clean.
- End-to-end smoke test: real server process fed five JSON-RPC messages on stdin;
  `initialize`, `store_pgn`, `player_stats`, `lookup_position`, `export_games`
  all returned correct results; the exported file appeared in
  `<library>/exports/smoke.pgn`.
- Board engine validated against the "Kiwipete" position (48 legal moves at
  depth 1) and the full Morphy Opera Game replayed to a confirmed checkmate.

## Known gaps / limitations

- **Exact position matching only**: position lookup is identity of
  `placement + side + castling + ep`; there is no transposition detection.
- **No half-move counter in keys**: halfmove/fullmove are ignored for lookups
  (intended — they don't change the position) but two side-movetexts that reach
  a position with different castling rights are treated as different positions.
- **MCP surface is the practical subset**: tools only; no resources/prompts.
- **Index rebuild drops nothing — except tags**: tags are persisted into the
  PGN headers (`LibraryTags`), so a rebuilt index keeps them, but manual edits
  to stored PGN files that remove that header lose the tags on rebuild.
- **Performance**: whole-file parsing and a per-game position index; aimed at
  personal-library sizes (thousands of games), not database scale.
- **Source-of-truth caveat**: stored PGNs are re-rendered from the parsed game
  when tags change (normalizing whitespace/notation); original files are not
  kept byte-for-byte once re-rendered.

## Privacy & scope

No secrets, no API keys, no personal data. Everything stays in the local
library folder. Education-only — never medical advice, never chess advice.
