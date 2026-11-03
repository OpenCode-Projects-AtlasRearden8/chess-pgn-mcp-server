"""Tests for the library layer (library.py), using sample PGN files."""

import os
import shutil
import tempfile
import unittest

from chess_pgn_mcp.library import Library, LibraryError, _normalize_fen, _safe_filename

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
SAMPLE_ORDER = ["morphy_opera_game.pgn", "fools_mate.pgn", "scholars_mate.pgn"]


def read_sample(name: str) -> str:
    with open(os.path.join(SAMPLES, name), "r", encoding="utf-8") as fh:
        return fh.read()


class LibraryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="chesslib-test-")
        self.library = Library(self.tmp)
        for name in SAMPLE_ORDER:
            self.library.store_pgn(read_sample(name), tags=["sample"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def find(self, *args, **kwargs):
        games = self.library.search(*args, **kwargs)
        return [g["game_id"] for g in games]


class TestStoreAndTag(LibraryTestCase):
    def test_store_counts_and_pgn_files(self):
        self.assertEqual(len(self.library.index["games"]), 3)
        entry = self.library.index["games"][0]
        path = os.path.join(self.library.games_dir, entry["id"] + ".pgn")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn('[White "Paul Morphy"]', fh.read())

    def test_store_rejects_bad_pgn(self):
        with self.assertRaises(LibraryError):
            self.library.store_pgn("this is not chess at all")
        with self.assertRaises(LibraryError):
            self.library.store_pgn('[Event "x"]\n\n1. Ne6 Illegal!\n')

    def test_store_multi_game_text(self):
        text = read_sample("multi_game.pgn")
        stored = self.library.store_pgn(text, tags=["demo"])
        self.assertEqual(len(stored), 2)

    def test_tags_normalized_and_searchable(self):
        self.library.store_pgn(read_sample("fools_mate.pgn"), tags=["Quick Mate", "chess caller"])
        # only the newly stored copy carries these tags
        self.assertEqual(len(self.find(tag="quick-mate")), 1)
        self.assertEqual(len(self.find(tag="chess-caller")), 1)
        counts = self.library.list_tags()
        self.assertEqual(counts.get("quick-mate"), 1)

    def test_add_and_remove_tags(self):
        game_id = self.find()[0]
        self.library.tag_game(game_id, add=["favorite"], remove=["sample"])
        entry = self.library._entry(game_id)
        self.assertIn("favorite", entry["tags"])
        self.assertNotIn("sample", entry["tags"])

    def test_delete_game(self):
        game_id = self.find()[0]
        self.assertTrue(self.library.delete_game(game_id))
        self.assertRaises(LibraryError, self.library._entry, game_id)
        self.assertEqual(len(self.library.index["games"]), 2)

    def test_rebuild_index_recovers(self):
        game_id = self.find()[0]
        self.library.tag_game(game_id, add=["favorite"])
        with open(self.library.index_path, "r", encoding="utf-8") as fh:
            broken = fh.read()
        with open(self.library.index_path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        recovered = Library(self.tmp)
        self.assertEqual(len(recovered.index["games"]), 3)
        self.assertIn("favorite", recovered._entry(game_id)["tags"])
        _ = broken


class TestSearch(LibraryTestCase):
    def test_search_by_player(self):
        self.assertEqual(len(self.find(player="morphy")), 3)
        self.assertEqual(len(self.find(player="Sample Player")), 2)
        self.assertEqual(self.find(player="nobody"), [])

    def test_search_by_color(self):
        whites = self.find(player="morphy", color="white")
        blacks = self.find(player="morphy", color="black")
        self.assertEqual(len(whites), 2)
        self.assertEqual(len(blacks), 1)
        self.assertRaises(LibraryError, self.library.search, color="white")

    def test_search_by_opening_and_result(self):
        self.assertEqual(len(self.find(opening="Philidor")), 1)
        self.assertEqual(len(self.find(result="1-0")), 2)
        self.assertEqual(len(self.find(result="0-1")), 1)
        self.assertRaises(ValueError, self.library.search, result="guess")

    def test_combined_filters(self):
        self.assertEqual(len(self.find(player="morphy", color="white", result="1-0")), 2)
        self.assertEqual(len(self.find(player="morphy", color="black", result="0-1")), 1)
        self.assertEqual(len(self.find(player="morphy", color="black", result="1-0")), 0)

    def test_get_game_record(self):
        game_id = self.find(opening="Philidor")[0]
        record = self.library.get_game(game_id)
        self.assertEqual(len(record["moves"]), 33)
        self.assertEqual(record["moves"][0]["san"], "e4")
        self.assertIn('[Opening "Philidor Defence"]', record["pgn"])


class TestStats(LibraryTestCase):
    def test_morphy_stats(self):
        stats = self.library.player_stats("Paul Morphy")
        self.assertEqual(stats["games"], 3)
        self.assertEqual(stats["as_white"], 2)
        self.assertEqual(stats["as_black"], 1)
        self.assertEqual(stats["wins"], 3)
        self.assertEqual(stats["losses"], 0)
        self.assertEqual(stats["draws"], 0)
        self.assertEqual(stats["openings"]["Philidor Defence"], 1)
        self.assertEqual(stats["opponents"]["Sample Player"], 2)
        avg = (33 + 4 + 7) / 3.0
        self.assertLess(abs(stats["avg_plies"] - avg), 0.05)

    def test_stats_empty_player(self):
        self.assertEqual(self.library.player_stats("Nobody")["games"], 0)
        self.assertRaises(LibraryError, self.library.player_stats, "   ")


class TestPositionLookup(LibraryTestCase):
    def test_start_position_hits_all_games(self):
        hits = self.library.lookup_position(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )
        self.assertEqual(len(hits), 3)
        self.assertTrue(all(h["move_number"] == 1 for h in hits))
        self.assertEqual({h["ply_moves"] for h in hits}, {"e4", "f3"})

    def test_position_after_1e4(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        hits = self.library.lookup_position(fen)
        self.assertEqual(len(hits), 2)  # opera game and scholar's mate
        self.assertEqual(set(h["move_number"] for h in hits), {1})
        self.assertEqual(set(h["ply_moves"] for h in hits), {"e5"})

    def test_final_mate_position(self):
        fen = _normalize_fen("1n1Rkb1r/p4ppp/4q3/4p1B1/4P3/8/PPP2PPP/2K5 b k - 0 1")
        hits = self.library.lookup_position(fen)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["opening"], "Philidor Defence")
        self.assertEqual(hits[0]["ply_moves"], "")  # end position: no next move

    def test_partial_fen_accepted(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq"
        self.assertEqual(len(self.library.lookup_position(fen)), 2)


class TestExport(LibraryTestCase):
    def test_export_all_and_filtered(self):
        count, saved = self.library.export_games()
        self.assertEqual(count, 3)
        self.assertIsNone(saved)
        count, saved = self.library.export_games(player="morphy", color="white", file_name="morphy wins")
        self.assertEqual(count, 2)
        self.assertTrue(saved and saved.endswith(".pgn"))
        with open(saved, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("[Event "), 2)
        self.assertIn('1-0', text.split('\n')[-2])

    def test_export_no_matches(self):
        count, saved = self.library.export_games(player="ghost")
        self.assertEqual(count, 0)
        self.assertIsNone(saved)

    def test_export_bad_filename(self):
        self.assertRaises(LibraryError, self.library.export_games, file_name="bad\x00name")

    def test_safe_filename(self):
        self.assertEqual(_safe_filename("My Games: 2026!"), "My-Games-2026.pgn")


if __name__ == "__main__":
    unittest.main()
