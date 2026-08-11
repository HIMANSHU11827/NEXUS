import json

from tools.nexus_tools.registry import ToolRegistry


def test_mcp_lifecycle_callbacks_remain_bound_to_each_server(tmp_path, monkeypatch):
    class FakeClient:
        instances = []

        def __init__(self, command, args):
            self.command = command
            self.args = args
            self.degraded_cb = None
            self.recover_cb = None
            self.tool_defs = [{
                "name": f"{command}_tool",
                "description": command,
                "inputSchema": {"type": "object", "properties": {}},
            }]
            self.__class__.instances.append(self)

        def start(self):
            return True

        def health_probe(self):
            return "healthy"

        def list_tools(self):
            return list(self.tool_defs)

        def stop(self):
            return None

    monkeypatch.setattr("mcp.client.MCPClient", FakeClient)
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(json.dumps({
        "servers": [
            {"name": "alpha", "command": "alpha", "args": []},
            {"name": "beta", "command": "beta", "args": []},
        ],
    }), encoding="utf-8")

    registry = object.__new__(ToolRegistry)
    registry.root = str(tmp_path)
    registry._tools = {}
    registry._mcp_clients = []
    registry._sync_to_nate = lambda *_args: None

    assert registry.init_mcp_tools(str(config_path)) == 2
    alpha, beta = FakeClient.instances
    assert set(registry._tools) == {"alpha_tool", "beta_tool"}

    alpha.degraded_cb()
    assert set(registry._tools) == {"beta_tool"}

    alpha.recover_cb(alpha.tool_defs)
    assert set(registry._tools) == {"alpha_tool", "beta_tool"}
