import json
import os
import tempfile
import unittest


class TestNexusMCPServer(unittest.TestCase):
    def test_initialize_and_tool_list(self):
        from integrations.mcp_server import handle_request

        init = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "nexus-code-graph")

        tools = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in tools["result"]["tools"]}
        self.assertIn("nexus_code_graph_build", names)
        self.assertIn("nexus_code_graph_symbol_context", names)

    def test_code_graph_tool_call_over_mcp(self):
        from integrations.mcp_server import handle_request

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "pkg"), exist_ok=True)
            with open(os.path.join(tmp, "pkg", "core.py"), "w", encoding="utf-8") as f:
                f.write("def run():\n    return 1\n")
            with open(os.path.join(tmp, "pkg", "use.py"), "w", encoding="utf-8") as f:
                f.write("from pkg.core import run\n\ndef main():\n    return run()\n")

            build = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "nexus_code_graph_build",
                        "arguments": {"root": tmp},
                    },
                }
            )
            build_payload = json.loads(build["result"]["content"][0]["text"])
            self.assertGreaterEqual(build_payload["nodes"], 1)

            context = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "nexus_code_graph_symbol_context",
                        "arguments": {"root": tmp, "symbol": "run"},
                    },
                }
            )
            payload = json.loads(context["result"]["content"][0]["text"])
            self.assertEqual(payload["symbol"], "run")
            self.assertTrue(payload["matches"])


if __name__ == "__main__":
    unittest.main()
