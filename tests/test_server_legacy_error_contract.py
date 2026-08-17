import pytest
from fastapi import HTTPException

import apps.api


def test_tool_inventory_fallback_returns_public_error_only(monkeypatch):
    class FailingRegistry:
        def __init__(self, _root):
            raise RuntimeError("registry path=C:\\private\\tools token=sk-live-tools")

    monkeypatch.setattr("tools.nexus_tools.registry.ToolRegistry", FailingRegistry)

    payload = server.list_tools()

    assert payload["error"] == "Tool inventory unavailable"
    assert "sk-live-tools" not in str(payload)


def test_workspace_directory_listing_returns_public_error_only(monkeypatch, tmp_path):
    secret_error = "permission path=C:\\private\\workspace"

    def fail_listdir(_target):
        raise OSError(secret_error)

    monkeypatch.setattr(server.os, "listdir", fail_listdir)

    with pytest.raises(HTTPException) as raised:
        server._list_workspace_files_sync(str(tmp_path), str(tmp_path))

    assert raised.value.status_code == 500
    assert raised.value.detail == "Workspace directory listing unavailable"
    assert secret_error not in raised.value.detail
