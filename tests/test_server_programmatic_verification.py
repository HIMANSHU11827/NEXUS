import asyncio
from types import SimpleNamespace

import apps.api as server


class _Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def test_programmatic_verification_endpoint_validates_workspace_and_returns_result(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))

    async def fake_run(root, commands, **kwargs):
        assert str(root) == str(tmp_path.resolve())
        assert commands == ["pytest -q"]
        return SimpleNamespace(to_dict=lambda: {"status": "passed", "success": True})

    monkeypatch.setattr(
        "nexus.main_agent.programmatic_verify.run_programmatic_verification", fake_run
    )
    result = asyncio.run(server.run_programmatic_verification(_Request({
        "commands": ["pytest -q"], "session_id": "s1",
    })))
    assert result == {"status": "passed", "success": True}


def test_programmatic_verification_endpoint_rejects_outside_root(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    try:
        asyncio.run(server.run_programmatic_verification(_Request({
            "commands": ["pytest -q"], "root": str(tmp_path.parent),
        })))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("outside verification root was accepted")


def test_programmatic_verification_endpoint_supports_safe_auto_recipe(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))

    async def fake_run(root, **kwargs):
        assert str(root) == str(tmp_path.resolve())
        return SimpleNamespace(to_dict=lambda: {"status": "passed", "recipe_source": "detected"})

    monkeypatch.setattr(
        "nexus.main_agent.programmatic_verify.run_detected_verification", fake_run
    )
    result = asyncio.run(server.run_programmatic_verification(_Request({"recipe": "auto"})))
    assert result == {"status": "passed", "recipe_source": "detected"}
