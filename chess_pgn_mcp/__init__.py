"""Chess PGN MCP Server -- local chess game library over MCP.

By Asdale Dynamics, LLC. MIT licensed; education-only, no chess engine.
"""

from .board import Position, Move, IllegalMove, ParseError, START_FEN, square_name, square_index
from .pgn import Game, Ply, parse_pgn
from .library import Library, LibraryError
from .server import serve, ChessServer, default_library_dir

__version__ = "1.0.0"

__all__ = [
    "Position", "Move", "IllegalMove", "ParseError", "START_FEN",
    "square_name", "square_index", "Game", "Ply", "parse_pgn",
    "Library", "LibraryError", "serve", "ChessServer", "default_library_dir",
    "__version__",
]
