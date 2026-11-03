"""Tests for the MCP server protocol and tools (server.py)."""

import io
import json
import os
import tempfile
import unittest

from chess_pgn_mcp.server import ChessServer, serve
from chess_pgn_mcp.library import Library

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

EXPECTED_TOOLS = {
    "store_pgn", "tag_game", "search_games", "get_game", "player_stats",
    "lookup_position", "export_games", "list_tags", "library_info", "delete_game",
}

OPERA_PGN = open(os.path.join(SAMPLES, "morphy_opera_game.pgn"), encoding="utf-8").read()


def make_server() -> ChessServer:
    tmp = tempfile.mkdtemp(prefix="chessmcp-test-")
    return ChessServer(Library(tmp))


class ProtocolTestCase(unittest.TestCase):
    def setUp(self):
        self.server = make_server()

    def _round_trip(self, message: dict, expect_id=True):
        response = self.server.handle(json.dumps(message))
        self.assertIsNotNone(response)
        self.assertEqual(response.get("jsonrpc"), "2.0")
        if expect_id:
            self.assertEqual(response.get("id"), message.get("id"))
        return response

    def call(self, tool: str, arguments: dict):
        return self._round_trip(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
             "params": {"name": tool, "arguments": arguments}}
        )["result"]


class TestProtocol(ProtocolTestCase):
    def test_initialize(self):
        response = self._round_trip(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )["result"]
        self.assertEqual(response["protocolVersion"], "2024-11-05")
        self.assertIn("tools", response["capabilities"])
        self.assertEqual(response["serverInfo"]["name"], "chess-pgn-mcp-server")

    def test_ping(self):
        response = self._round_trip({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(response["result"], {})

    def test_notifications_silence(self):
        self.assertIsNone(
            self.server.handle(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        )

    def test_unknown_method(self):
        response = self._round_trip({"jsonrpc": "2.0", "id": 3, "method": "wat/now"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_bad_json(self):
        response = self.server.handle("{nope")
        self.assertEqual(response["error"]["code"], -32700)

    def test_tools_listed_with_schemas(self):
        response = self._round_trip({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})["result"]
        names = {t["name"] for t in response["tools"]}
        self.assertEqual(names, EXPECTED_TOOLS)
        for tool in response["tools"]:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("description", tool)

    def test_unknown_tool(self):
        response = self._round_trip(
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "rocket_launch", "arguments": {}}}
        )
        self.assertEqual(response["error"]["code"], -32602)


class TestTools(ProtocolTestCase):
    def test_store_and_search(self):
        result = self.call("store_pgn", {"pgn": OPERA_PGN, "tags": ["romantic"]})
        self.assertFalse(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(len(payload["stored"]), 1)
        game_id = payload["stored"][0]["game_id"]

        result = self.call("search_games", {"player": "morphy"})
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["found"], 1)
        self.assertEqual(payload["games"][0]["game_id"], game_id)

    def test_store_pgn_error_is_reported(self):
        result = self.call("store_pgn", {"pgn": "[Event \"x\"]\n\n1. Ke3 g6\n"})
        self.assertTrue(result["isError"])
        self.assertIn("Error", result["content"][0]["text"])

    def test_player_stats(self):
        self.call("store_pgn", {"pgn": OPERA_PGN})
        result = self.call("player_stats", {"player": "Paul Morphy"})
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["wins"], 1)
        self.assertEqual(payload["games"], 1)

    def test_lookup_position(self):
        self.call("store_pgn", {"pgn": OPERA_PGN})
        result = self.call(
            "lookup_position",
            {"fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"},
        )
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["found"], 1)

    def test_export_with_and_without_file(self):
        self.call("store_pgn", {"pgn": OPERA_PGN})
        result = self.call("export_games", {"player": "morphy"})
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["exported"], 1)
        self.assertNotIn("saved_to", payload)

        result = self.call("export_games", {"player": "morphy", "file_name": "opera.pgn"})
        payload = json.loads(result["content"][0]["text"])
        self.assertIn("saved_to", payload)
        self.assertTrue(os.path.exists(payload["saved_to"]))

    def test_tag_and_delete_round_trip(self):
        stored = json.loads(self.call("store_pgn", {"pgn": OPERA_PGN})["content"][0]["text"])
        game_id = stored["stored"][0]["game_id"]
        result = self.call("tag_game", {"game_id": game_id, "add_tags": ["favorite"]})
        self.assertIn("favorite", json.loads(result["content"][0]["text"])["tags"])
        result = self.call("delete_game", {"game_id": game_id})
        self.assertEqual(json.loads(result["content"][0]["text"])["deleted"], game_id)
        result = self.call("search_games", {"player": "morphy"})
        self.assertEqual(json.loads(result["content"][0]["text"])["found"], 0)

    def test_lookup_missing_fen_is_error(self):
        result = self.call("lookup_position", {})
        self.assertTrue(result["isError"])


class TestStdioServe(ProtocolTestCase):
    def test_serve_round_trip(self):
        library = Library(tempfile.mkdtemp(prefix="chessmcp-serve-"))
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            "",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "store_pgn", "arguments": {"pgn": OPERA_PGN}}}),
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "player_stats", "arguments": {"player": "Paul Morphy"}}}),
        ]
        output = io.StringIO()
        serve(library, stdin=iter(lines), stdout=output)
        responses = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(responses), 4)
        self.assertEqual(responses[0]["id"], 1)
        tools = {t["name"] for t in responses[1]["result"]["tools"]}
        self.assertEqual(tools, EXPECTED_TOOLS)
        stored = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertEqual(stored["stored"][0]["white"], "Paul Morphy")
        stats = json.loads(responses[3]["result"]["content"][0]["text"])
        self.assertEqual(stats["wins"], 1)


if __name__ == "__main__":
    unittest.main()
