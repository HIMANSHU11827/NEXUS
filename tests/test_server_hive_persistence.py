import json
import asyncio
from types import SimpleNamespace


def test_hive_manifest_restores_running_hives_as_interrupted(tmp_path, monkeypatch):
    import server

    manifest = tmp_path / "hives" / "index.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps([
            {
                "id": "hive_saved",
                "status": "running",
                "agents": [{"id": "agent_saved", "status": "running"}],
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_HIVE_MANIFEST_PATH", str(manifest))
    monkeypatch.setattr(server, "_HIVES", {})

    server._load_hive_manifest()

    restored = server._HIVES["hive_saved"]
    assert restored["status"] == "interrupted"
    assert restored["resume_required"] is True
    assert restored["agents"][0]["status"] == "interrupted"


def test_hive_manifest_persist_is_atomic_and_round_trips(tmp_path, monkeypatch):
    import server

    manifest = tmp_path / "hives" / "index.json"
    monkeypatch.setattr(server, "_HIVE_MANIFEST_PATH", str(manifest))
    monkeypatch.setattr(server, "_HIVES", {})
    server._HIVES["hive_roundtrip"] = {
        "id": "hive_roundtrip",
        "status": "cancelled",
        "agents": [],
    }

    server._persist_hive_manifest()

    assert json.loads(manifest.read_text(encoding="utf-8"))[0]["id"] == "hive_roundtrip"


def test_resume_hive_respawns_saved_tasks_and_links_runs(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "_HIVE_MANIFEST_PATH", str(tmp_path / "index.json"))
    monkeypatch.setattr(server, "_HIVES", {
        "hive_old": {
            "id": "hive_old",
            "status": "interrupted",
            "agents": [{"id": "agent_old", "task": "run tests", "persona": "TESTER", "status": "interrupted"}],
        }
    })

    class FakeEngine:
        async def spawn_hive(self, tasks, parent_run_id=""):
            assert tasks == [("run tests", "TESTER")]
            assert parent_run_id == "hive_old"
            agent = SimpleNamespace(agent_id="agent_new", task="run tests", persona="TESTER", status="pending")
            return "hive_new", [agent]

    monkeypatch.setattr(server, "_get_hive_engine", lambda: FakeEngine())
    result = asyncio.run(server.resume_hive("hive_old"))

    assert result["hive"]["id"] == "hive_new"
    assert server._HIVES["hive_old"]["resumed_to"] == "hive_new"
    assert server._HIVES["hive_old"]["status"] == "superseded"
    assert server._HIVES["hive_new"]["resumed_from"] == "hive_old"


def test_resume_hive_skips_terminal_agents(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "_HIVE_MANIFEST_PATH", str(tmp_path / "index.json"))
    monkeypatch.setattr(server, "_HIVES", {
        "hive_old": {
            "id": "hive_old", "status": "interrupted",
            "agents": [
                {"id": "done", "task": "already done", "persona": "WORKER", "status": "success"},
                {"id": "left", "task": "continue this", "persona": "WORKER", "status": "interrupted"},
            ],
        }
    })

    class FakeEngine:
        async def spawn_hive(self, tasks, parent_run_id=""):
            assert tasks == [("continue this", "WORKER")]
            return "hive_new", []

    monkeypatch.setattr(server, "_get_hive_engine", lambda: FakeEngine())
    asyncio.run(server.resume_hive("hive_old"))
