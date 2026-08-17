import json
from unittest.mock import patch

import pytest

from extensions.mcp.core.catalog.scripts.catalog import MCPServerCatalog, MCPServerDef


def test_mcp_catalog_persists_env_references_without_expanding_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecretvalue123456")
    catalog = MCPServerCatalog(tmp_path)

    catalog.register(
        MCPServerDef(
            name="github",
            description="GitHub MCP",
            command="node",
            env={"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        )
    )

    saved = json.loads((tmp_path / "mcp_config.json").read_text(encoding="utf-8"))
    assert saved["servers"]["github"]["env"] == {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    assert "ghp_supersecretvalue" not in json.dumps(saved)


def test_mcp_catalog_rejects_literal_secret_env_values(tmp_path):
    catalog = MCPServerCatalog(tmp_path)

    with pytest.raises(ValueError, match="looks like a secret"):
        catalog.register(
            MCPServerDef(
                name="github",
                description="GitHub MCP",
                command="node",
                env={"GITHUB_TOKEN": "ghp_supersecretvalue123456"},
            )
        )


def test_mcp_catalog_resolves_env_references_only_when_starting(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "runtime-token")
    catalog = MCPServerCatalog(tmp_path)
    catalog.register(
        MCPServerDef(
            name="github",
            description="GitHub MCP",
            command="node",
            env={"GITHUB_TOKEN": "${GITHUB_TOKEN}", "NODE_ENV": "production"},
        )
    )

    with patch("extensions.mcp.core.catalog.scripts.catalog.subprocess.Popen") as popen:
        popen.return_value.pid = 123
        catalog.start_server("github")

    env = popen.call_args.kwargs["env"]
    assert env["GITHUB_TOKEN"] == "runtime-token"
    assert env["NODE_ENV"] == "production"
