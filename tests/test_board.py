"""Tests for the chess rules core (board.py)."""

import unittest

from chess_pgn_mcp.board import Position, START_FEN, IllegalMove, ParseError, square_index, square_name


class TestFen(unittest.TestCase):
    def test_start_round_trip(self):
        pos = Position.from_fen(START_FEN)
        self.assertEqual(pos.to_fen(), START_FEN)

    def test_parse_kiwipete(self):
        fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
        pos = Position.from_fen(fen)
        self.assertEqual(pos.to_fen(), fen)
        moves = pos.generate_legal_moves()
        self.assertEqual(len(moves), 48)  # known perft-1 node count

    def test_bad_fen_rejected(self):
        with self.assertRaises(ParseError):
            Position.from_fen("not a fen")
        with self.assertRaises(ParseError):
            Position.from_fen("9/8/8/8/8/8/8/8 w - - 0 1")
        with self.assertRaises(ParseError):
            Position.from_fen("8/8/8/8/8/8/8/8 w - - 0 1")  # missing kings


class TestMoveGeneration(unittest.TestCase):
    def test_start_has_20_moves(self):
        pos = Position.from_fen(START_FEN)
        self.assertEqual(len(pos.generate_legal_moves()), 20)

    def test_en_passant_capture(self):
        # black pawn e4 may capture the white pawn that just double-pushed to f4
        fen = "rnbqkbnr/pppppppp/8/8/4pP2/8/PPPPP1PP/RNBQKBNR b KQkq f3 0 1"
        pos = Position.from_fen(fen)
        moves = [m for m in pos.generate_legal_moves() if m.is_en_passant]
        self.assertEqual(len(moves), 1)
        self.assertEqual(square_name(moves[0].origin), "e4")
        self.assertEqual(square_name(moves[0].target), "f3")
        after = pos.apply(moves[0])
        self.assertEqual(after.piece_at(square_index("f4")), "")  # pawn removed
        self.assertEqual(after.piece_at(square_index("f3")), "p")

    def test_en_passant_position_key_normalized(self):
        # an ep target the opponent cannot exploit must be '-' in the position key
        fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        pos = Position.from_fen(fen)
        self.assertTrue(pos.position_key().endswith(" -"), pos.position_key())


class TestSan(unittest.TestCase):
    def replay(self, sans: str):
        pos = Position.from_fen(START_FEN)
        for token in sans.split():
            pos = pos.apply(pos.parse_san(token))
        return pos

    def test_fools_mate_ends_game(self):
        pos = self.replay("f3 e5 g4 Qh4#")
        self.assertEqual(pos.generate_legal_moves(), [])
        self.assertTrue(pos.white_to_move)
        self.assertEqual(
            pos.to_fen().split()[0], "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR"
        )

    def test_castling_both_sides(self):
        pos = self.replay(
            "e4 e5 Nf3 Nc6 Bc4 Bc5 O-O Nf6 c3 d5 exd5 Nxd5 d4 exd4 cxd4 Bd6 Nc3 O-O"
        )
        self.assertEqual(
            [square_name(pos.king_square(w)) for w in (True, False)], ["g1", "g8"]
        )
        self.assertEqual(pos.piece_at(square_index("f1")), "R")
        self.assertEqual(pos.piece_at(square_index("f8")), "r")

    def test_bare_knight_move_is_ambiguous(self):
        pos = Position.from_fen("k7/8/8/8/8/5N2/8/1N2K3 w - - 0 1")
        with self.assertRaises(IllegalMove):
            pos.parse_san("Nd2")
        self.assertEqual(square_name(pos.parse_san("Nbd2").origin), "b1")
        self.assertEqual(square_name(pos.parse_san("Nfd2").origin), "f3")

    def test_promotion(self):
        pos = Position.from_fen("8/P7/8/8/8/7k/8/7K w - - 0 1")
        move = pos.parse_san("a8=Q")
        after = pos.apply(move)
        self.assertEqual(after.piece_at(square_index("a8")), "Q")

    def test_generated_san_round_trip(self):
        sans = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3"
        pos = Position.from_fen(START_FEN)
        for token in sans.split():
            move = pos.parse_san(token)
            self.assertEqual(pos.san_for(move), token, (pos.to_fen(), token))
            pos = pos.apply(move)

    def test_illegal_moves_rejected(self):
        pos = Position.from_fen(START_FEN)
        with self.assertRaises(IllegalMove):
            pos.parse_san("Ke4")
        with self.assertRaises(IllegalMove):
            pos.parse_san("Ne5")


if __name__ == "__main__":
    unittest.main()
