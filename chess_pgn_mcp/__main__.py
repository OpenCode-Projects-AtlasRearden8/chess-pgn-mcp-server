"""Run the MCP server: python -m chess_pgn_mcp [--library DIR] [--selftest]."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .library import Library
from .server import serve, default_library_dir


def _selftest(library_dir: str) -> int:
    """Quick demo: seed a fresh library from samples/ and print a summary."""
    samples_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
    library = Library(library_dir)
    loaded = 0
    if os.path.isdir(samples_dir):
        for name in sorted(os.listdir(samples_dir)):
            if not name.endswith(".pgn"):
                continue
            with open(os.path.join(samples_dir, name), "r", encoding="utf-8") as fh:
                text = fh.read()
            if text.strip():
                library.store_pgn(text, tags=["sample"])
                loaded += 1
    info = library.info()
    print("Chess PGN MCP Server self-test")
    print("  python:      %s" % sys.version.split()[0])
    print("  library dir: %s" % info["library_dir"])
    print("  sample files loaded: %s (library total: %s games)" % (loaded, info["game_count"]))
    print("  tags: %s" % (", ".join("%s=%d" % kv for kv in info["tags"].items()) or "none"))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="chess-pgn-mcp-server",
        description="Serve a local chess PGN library over MCP (stdio JSON-RPC).",
    )
    parser.add_argument("--library", default=None, help="library directory (default: $CHESS_PGN_LIBRARY_DIR or ~/.chess_pgn_library)")
    parser.add_argument("--version", action="version", version="chess-pgn-mcp-server " + __version__)
    parser.add_argument("--selftest", action="store_true", help="seed a temp library from samples/ and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest(os.path.join(os.environ.get("TMPDIR", "/tmp"), "chess-pgn-mcp-selftest"))

    library = Library(args.library or default_library_dir())
    serve(library)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
