import json
import asyncio
from types import SimpleNamespace


def test_hive_budget_environment_setting_is_fail_safe(monkeypatch):
    import server

    monkeypatch.setenv("NEXUS_HIVE_MAX_TOTAL_STEPS", "not-an-integer")
    assert server._nonnegative_env_int("NEXUS_HIVE_MAX_TOTAL_STEPS") == 0
    monkeypatch.setenv("NEXUS_HIVE_MAX_TOTAL_STEPS", "-4")
    assert server._nonnegative_env_int("NEXUS_HIVE_MAX_TOTAL_STEPS") == 0
    monkeypatch.setenv("NEXUS_HIVE_MAX_TOTAL_STEPS", "12")
    assert server._nonnegative_env_int("NEXUS_HIVE_MAX_TOTAL_STEPS") == 12


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


def test_auto_resume_interrupted_hives_is_opt_in_and_links_new_hive(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "_HIVE_MANIFEST_PATH", str(tmp_path / "index.json"))
    monkeypatch.setattr(server, "_HIVES", {
        "hive_old": {
            "id": "hive_old", "status": "interrupted", "resume_required": True,
            "agents": [{"id": "left", "task": "continue", "persona": "WORKER", "status": "interrupted"}],
        }
    })

    class FakeEngine:
        async def spawn_hive(self, tasks, parent_run_id=""):
            assert tasks == [("continue", "WORKER")]
            assert parent_run_id == "hive_old"
            return "hive_new", [SimpleNamespace(agent_id="new", task="continue", persona="WORKER", status="pending")]

    monkeypatch.setattr(server, "_get_hive_engine", lambda: FakeEngine())
    result = asyncio.run(server._auto_resume_interrupted_hives())
    assert result == ["hive_new"]
    assert server._HIVES["hive_old"]["status"] == "superseded"
    assert server._HIVES["hive_new"]["resumed_from"] == "hive_old"


def test_pause_and_resume_paused_hive_stay_on_same_identity(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "_HIVE_MANIFEST_PATH", str(tmp_path / "index.json"))
    monkeypatch.setattr(server, "_HIVES", {
        "hive_live": {
            "id": "hive_live", "status": "running",
            "agents": [{"id": "agent_live", "task": "continue", "persona": "WORKER", "status": "running"}],
        }
    })

    class FakeEngine:
        def __init__(self):
            self.paused = []
            self.resumed = []
            self._hives = {"hive_live": []}

        async def pause_hive(self, hive_id):
            self.paused.append(hive_id)

        async def resume_hive(self, hive_id):
            self.resumed.append(hive_id)

    engine = FakeEngine()
    monkeypatch.setattr(server, "_get_hive_engine", lambda: engine)

    paused = asyncio.run(server.pause_hive("hive_live"))
    assert paused["hive"]["status"] == "paused"
    resumed = asyncio.run(server.resume_hive("hive_live"))
    assert resumed["hive"]["id"] == "hive_live"
    assert resumed["hive"]["status"] == "running"
    assert engine.paused == ["hive_live"]
    assert engine.resumed == ["hive_live"]


def test_resume_reconstructs_paused_hive_after_backend_restart(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server, "_HIVE_MANIFEST_PATH", str(tmp_path / "index.json"))
    monkeypatch.setattr(server, "_HIVES", {
        "hive_saved": {
            "id": "hive_saved", "status": "paused",
            "agents": [{"id": "agent_saved", "task": "continue safely", "persona": "WORKER", "status": "paused"}],
        }
    })

    class FreshEngine:
        _hives = {}

        async def spawn_hive(self, tasks, parent_run_id=""):
            assert tasks == [("continue safely", "WORKER")]
            assert parent_run_id == "hive_saved"
            return "hive_resumed", [SimpleNamespace(agent_id="agent_new", task="continue safely", persona="WORKER", status="pending")]

    monkeypatch.setattr(server, "_get_hive_engine", lambda: FreshEngine())
    result = asyncio.run(server.resume_hive("hive_saved"))
    assert result["hive"]["id"] == "hive_resumed"
    assert server._HIVES["hive_saved"]["status"] == "superseded"


def test_create_hive_reconciles_fast_terminal_agents_before_persisting(tmp_path, monkeypatch):
    import server

    class Request:
        async def json(self):
            return {"agents": [{"task": "fast", "persona": "TESTER"}]}

    class FastAgent:
        agent_id = "agent_fast"
        task = "fast"
        persona = "TESTER"
        status = "success"

    class FastEngine:
        async def spawn_hive(self, tasks):
            assert tasks == [("fast", "TESTER")]
            return "hive_fast", [FastAgent()]

    monkeypatch.setattr(server, "_HIVES", {})
    monkeypatch.setattr(server, "_get_hive_engine", lambda: FastEngine())
    monkeypatch.setattr(server, "_persist_hive_manifest", lambda: None)

    result = asyncio.run(server.create_hive(Request()))

    assert result["hive"]["status"] == "success"
    assert server._HIVES["hive_fast"]["status"] == "success"
