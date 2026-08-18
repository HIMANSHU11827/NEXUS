import asyncio
import json

import apps.api as server


class _Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def test_mcp_create_and_delete_keep_yaml_and_registry_json_in_sync(tmp_path, monkeypatch):
    config_path = tmp_path / "settings.yml"
    mcp_path = tmp_path / "mcp_servers.json"
    config = {}

    monkeypatch.setattr(server, "_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(server, "_MCP_SERVERS_PATH", str(mcp_path))
    monkeypatch.setattr(server, "_load_nexus_config", lambda: config)
    monkeypatch.setattr(server, "_save_nexus_config", lambda value: config.update(value))
    monkeypatch.setattr(server, "_clear_runtime", lambda _reason: {})

    created = asyncio.run(server.create_mcp(_Request({
        "name": "filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/workspace"],
        "description": "workspace files",
        "active": True,
    })))
    assert created["status"] == "success"
    assert config["mcp_servers"]["filesystem"]["command"] == "npx"
    stored = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert stored["servers"][0]["name"] == "filesystem"
    assert stored["servers"][0]["args"][-1] == "C:/workspace"

    deleted = server.delete_mcp("filesystem")
    assert deleted == {"status": "success", "id": "filesystem"}
    assert config["mcp_servers"] == {}
    assert json.loads(mcp_path.read_text(encoding="utf-8"))["servers"] == []
