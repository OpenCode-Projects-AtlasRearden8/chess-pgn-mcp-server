"""Tests for the PGN parser (pgn.py)."""

import os
import unittest

from chess_pgn_mcp.pgn import parse_pgn, _tokenize
from chess_pgn_mcp.board import START_FEN

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def read_sample(name: str) -> str:
    with open(os.path.join(SAMPLES, name), "r", encoding="utf-8") as fh:
        return fh.read()


class TestTokenizer(unittest.TestCase):
    def test_comments_variations_and_nags(self):
        tokens = _tokenize("1.e4 {hello (hi) there} 1...e5 2. Nf3$5 (2. d4 exd4) 2...Nc6 1-0")
        self.assertEqual(tokens, ["e4", "e5", "Nf3", "Nc6"])

    def test_line_comments(self):
        tokens = _tokenize("1. e4 ; e5 as a line comment\n1... e5")
        self.assertEqual(tokens, ["e4", "e5"])


class TestParse(unittest.TestCase):
    def test_single_game(self):
        games = parse_pgn(read_sample("morphy_opera_game.pgn"))
        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game.white, "Paul Morphy")
        self.assertEqual(game.result, "1-0")
        self.assertEqual(len(game.plies), 33)

    def test_positions_replay(self):
        game = parse_pgn(read_sample("morphy_opera_game.pgn"))[0]
        self.assertEqual(game.plies[0].fen_before, START_FEN)
        self.assertEqual(
            game.plies[-1].fen_after.split()[0],
            "1n1Rkb1r/p4ppp/4q3/4p1B1/4P3/8/PPP2PPP/2K5",
        )

    def test_move_numbers_and_players(self):
        game = parse_pgn(read_sample("fools_mate.pgn"))[0]
        self.assertEqual([p.number for p in game.plies], [1, 1, 2, 2])
        self.assertEqual([p.player for p in game.plies] == ["white", "black"] * 2, True)

    def test_multiple_games_and_unfinished_result(self):
        text = read_sample("multi_game.pgn") + "\n" + read_sample("morphy_opera_game.pgn")
        games = parse_pgn(text)
        self.assertEqual(len(games), 3)
        self.assertEqual(games[0].result, "1/2-1/2")
        self.assertEqual(games[1].result, "*")
        self.assertEqual(games[2].result, "1-0")

    def test_result_from_movetext_is_used(self):
        text = '[Event "X"]\n[Result "*"]\n\n1. e4 e5 1-0\n'
        game = parse_pgn(text)[0]
        self.assertEqual(game.result, "1-0")

    def test_escapes_in_headers(self):
        text = '[Event "The \\"Massive\\" AI Manual Open"]\n[Result "*"]\n\n1. e4 e5 *\n'
        game = parse_pgn(text)[0]
        self.assertEqual(game.headers["Event"], 'The "Massive" AI Manual Open')

    def test_round_trip_to_pgn(self):
        for name in os.listdir(SAMPLES):
            if not name.endswith(".pgn"):
                continue
            games = parse_pgn(read_sample(name))
            for game in games:
                again = parse_pgn(game.to_pgn())
                self.assertEqual(len(again), 1)
                equal = [p.san for p in again[0].plies] == [p.san for p in game.plies]
                self.assertTrue(equal, name)

    def test_invalid_pgn_raises_with_context(self):
        text = '[Event "bad"]\n[Result "*"]\n\n1. e4 e5 2. Ke2?? Nf6zz\n'
        self.assertRaises(ValueError, parse_pgn, text)

    def test_no_games_raises(self):
        self.assertRaises(ValueError, parse_pgn, "")


if __name__ == "__main__":
    unittest.main()
