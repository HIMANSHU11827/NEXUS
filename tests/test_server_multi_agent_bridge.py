import pytest


class _Agent:
    agent_id = "agent-1"
    task = "inspect the project"
    persona = "WORKER"
    status = "running"


class _Hive:
    def list_personas(self):
        return {"WORKER": "General worker"}

    async def spawn_hive(self, tasks):
        assert tasks == [("inspect the project", "WORKER")]
        return "hive-1", [_Agent()]


@pytest.mark.asyncio
async def test_multi_agent_endpoint_launches_real_hive(monkeypatch):
    import apps.api

    monkeypatch.setattr(server, "_get_hive_engine", lambda: _Hive())
    monkeypatch.setattr(server, "_persist_hive_manifest", lambda: None)
    monkeypatch.setattr(server, "_HIVES", {})

    class Request:
        async def json(self):
            return {"command": "/run", "prompt": "inspect the project"}

    result = await server.multi_agent(Request())

    assert result["status"] == "started"
    assert result["hive_id"] == "hive-1"
    assert result["hive"]["agents"][0]["status"] == "running"
    assert server._HIVES["hive-1"]["status"] == "running"


@pytest.mark.asyncio
async def test_multi_agent_endpoint_rejects_empty_prompt():
    import apps.api

    class Request:
        async def json(self):
            return {"command": "/run", "prompt": "   "}

    with pytest.raises(Exception) as raised:
        await server.multi_agent(Request())
    assert getattr(raised.value, "status_code", None) == 400
