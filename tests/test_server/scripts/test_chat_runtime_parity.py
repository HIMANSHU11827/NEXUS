import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _server_mocks():
    patches = [
        patch("dotenv.load_dotenv"),
        patch("orchestrators.NexusLoop"),
        patch("authentication.check_auth", return_value=MagicMock()),
        patch("authentication.is_public_path", return_value=True),
        patch("authentication.AuthUser"),
        patch("authentication.validate_dashboard_token", return_value=True),
        patch("yaml.safe_load", return_value={}),
        patch("yaml.safe_dump"),
    ]
    for item in patches:
        item.start()
    for mod in list(sys.modules.keys()):
        if mod.startswith("server"):
            del sys.modules[mod]
    yield
    for item in patches:
        item.stop()


def test_server_chat_cancel_route_aborts_active_loop():
    from server import _LOOPS, app

    class FakeLoop:
        _current_turn_id = "turn-server-cancel"
        aborted = False

        def abort(self):
            self.aborted = True

    loop = FakeLoop()
    _LOOPS["server-cancel"] = loop

    with TestClient(app) as client:
        response = client.post("/api/chat/server-cancel/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert loop.aborted is True
    assert payload["status"] == "cancelled"
    assert payload["run_id"] == "turn-server-cancel"
    assert payload["event"]["type"] == "run.cancelled"
    _LOOPS.clear()


def test_set_model_can_switch_to_an_enabled_named_profile(monkeypatch):
    import server

    class Profile:
        model_id = "deepseek-v4-flash"
        model = ""

    class Store:
        @staticmethod
        def get_profile(provider, name):
            return Profile() if (provider, name) == ("deepseek", "work") else None

    monkeypatch.setattr("providers.profiles.load_profile_store", lambda: Store())
    monkeypatch.setattr(server, "apply_runtime_to_all_loops", lambda: None)
    server._RUNTIME_SETTINGS.update({"model": "", "provider": "", "profile": ""})

    with TestClient(server.app) as client:
        response = client.post("/api/model", json={"model": "Friendly work", "provider": "deepseek", "profile": "work"})

    assert response.status_code == 200
    assert response.json()["model"] == "deepseek-v4-flash"
    assert response.json()["profile"] == "work"


def test_set_model_rejects_an_unavailable_profile(monkeypatch):
    import server

    class Store:
        @staticmethod
        def get_profile(_provider, _name):
            return None

    monkeypatch.setattr("providers.profiles.load_profile_store", lambda: Store())
    with TestClient(server.app) as client:
        response = client.post("/api/model", json={"model": "Friendly", "provider": "deepseek", "profile": "disabled"})

    assert response.status_code == 409
    assert "unavailable or disabled" in response.json()["detail"]


def test_saved_models_route_matches_gui_picker_contract(tmp_path, monkeypatch):
    import server

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    provider_path = config_dir / "provider.yml"
    provider_path.write_text(
        "providers:\n  deepseek:\n    model: deepseek-chat\n  ollama:\n    model: llama3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(server.yaml, "safe_load", lambda _handle: {
        "providers": {
            "deepseek": {"model": "deepseek-chat"},
            "ollama": {"model": "llama3"},
        }
    })

    with TestClient(server.app) as client:
        response = client.get("/models/saved")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {"model": "deepseek-chat", "provider": "deepseek", "profile": "", "alias": "", "label": "deepseek: deepseek-chat"},
            {"model": "llama3", "provider": "ollama", "profile": "", "alias": "", "label": "ollama: llama3"},
        ]
    }


def test_server_chat_passes_turn_and_max_tokens_to_loop(monkeypatch):
    from server import app

    captured = {}

    class FakeLoop:
        is_running = False
        model = "default-model"
        work_event_sink = None

        async def stream_run(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            yield {"type": "content", "data": "ok"}

    import server

    monkeypatch.setattr(server, "get_loop", lambda _sid: FakeLoop())
    monkeypatch.setattr(server, "set_active_session", lambda *args, **kwargs: None)

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "prompt": "hello",
                "session_id": "server-param",
                "provider": "openai",
                "model": "gpt-test",
                "turn_id": "turn-server",
                "max_tokens": 321,
            },
        )

    assert response.status_code == 200
    assert response.json() == {"response": "ok"}
    assert captured["prompt"] == "hello"
    assert captured["kwargs"] == {
        "provider": "openai",
        "model": "gpt-test",
        "max_tokens": 321,
        "turn_id": "turn-server",
        "conversation_history": None,
        "deadline_seconds": 30.0,
    }


def test_server_chat_timeout_emits_error_before_one_terminal_marker(monkeypatch):
    import asyncio
    import server

    captured = {}

    class FakeLoop:
        is_running = False
        model = "default-model"
        work_event_sink = None

        def request_abort(self, run_id, reason=""):
            captured["abort"] = (run_id, reason)
            return True

        async def stream_run(self, prompt, **kwargs):
            await asyncio.sleep(2)
            yield {"type": "content", "data": "late"}

    monkeypatch.setattr(server, "get_loop", lambda _sid: FakeLoop())
    monkeypatch.setattr(server, "set_active_session", lambda *args, **kwargs: None)

    with TestClient(server.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "prompt": "stall",
                "session_id": "server-timeout-chat",
                "turn_id": "timeout-turn",
                "timeout_seconds": 1,
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert "Response timed out after 1 seconds" in response.text
    assert response.text.count("event: error") == 1
    assert captured["abort"] == ("timeout-turn", "deadline_exceeded")


def test_server_chat_uses_resume_workflow_context_and_completes_workflow(monkeypatch):
    import server

    captured = {}

    class FakeLoop:
        is_running = False
        model = "default-model"
        work_event_sink = None

        async def stream_run(self, prompt, **kwargs):
            captured["prompt"] = prompt
            yield {"type": "content", "data": "resumed"}

    def fake_start(session_id, prompt, turn_id):
        captured["start"] = (session_id, prompt, turn_id)
        return "unfinished phase"

    def fake_complete(session_id, prompt, turn_id, status="done"):
        captured["complete"] = (session_id, prompt, turn_id, status)

    monkeypatch.setattr(server, "get_loop", lambda _sid: FakeLoop())
    monkeypatch.setattr(server, "set_active_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "start_chat_workflow", fake_start)
    monkeypatch.setattr(server, "complete_chat_workflow", fake_complete)

    with TestClient(server.app) as client:
        response = client.post(
            "/api/chat",
            json={"prompt": "continue", "session_id": "resume-server", "turn_id": "resume-turn"},
        )

    assert response.status_code == 200
    assert "[NEXUS_RESUME_CONTEXT]" in captured["prompt"]
    assert "unfinished phase" in captured["prompt"]
    assert captured["start"] == ("resume-server", "continue", "resume-turn")
    assert captured["complete"] == ("resume-server", "continue", "resume-turn", "done")


def test_server_failed_terminal_chunk_marks_workflow_failed(monkeypatch):
    import server

    captured = {}

    class FakeLoop:
        is_running = False
        model = "default-model"
        work_event_sink = None

        async def stream_run(self, prompt, **kwargs):
            yield {"type": "done", "data": {"success": False, "error": "tool failed"}}

    monkeypatch.setattr(server, "get_loop", lambda _sid: FakeLoop())
    monkeypatch.setattr(server, "set_active_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "complete_chat_workflow", lambda *args: captured.setdefault("args", args))

    with TestClient(server.app) as client:
        response = client.post(
            "/api/chat",
            json={"prompt": "fail", "session_id": "failed-workflow", "turn_id": "failed-turn", "stream": True},
        )

    assert response.status_code == 200
    assert captured["args"][-1] == "failed"


def test_server_non_stream_timeout_requests_run_abort(monkeypatch):
    import asyncio
    import server

    captured = {}

    class FakeLoop:
        is_running = False
        model = "default-model"
        work_event_sink = None

        def request_abort(self, run_id, reason=""):
            captured["abort"] = (run_id, reason)
            return True

        async def stream_run(self, prompt, **kwargs):
            await asyncio.sleep(2)
            yield {"type": "content", "data": "late"}

    monkeypatch.setattr(server, "get_loop", lambda _sid: FakeLoop())
    monkeypatch.setattr(server, "set_active_session", lambda *args, **kwargs: None)

    with TestClient(server.app) as client:
        response = client.post(
            "/api/chat",
            json={"prompt": "stall", "session_id": "nonstream-timeout", "turn_id": "nonstream-turn", "timeout_seconds": 1},
        )

    assert response.status_code == 200
    assert "Response timed out after 1 seconds" in response.json()["response"]
    assert captured["abort"] == ("nonstream-turn", "deadline_exceeded")


def test_server_run_context_endpoints_list_and_read_runs(tmp_path, monkeypatch):
    import server
    from nexus.run_context import start_run_context
    from server import app

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "work_events"))
    server._WORK_EVENT_SEQUENCES.clear()
    context = start_run_context(
        root=str(tmp_path),
        session_id="session-a",
        run_id="run-a",
        prompt="hello",
        provider="openai",
        model="gpt-test",
    )
    context.finish("success", "run.completed")
    server._append_work_event(
        "session-a",
        {
            "event_id": "run-run-a",
            "id": "run-run-a",
            "sequence": 1,
            "turn_id": "run-a",
            "run_id": "run-a",
            "kind": "run",
            "status": "running",
            "event_type": "run.started",
        },
    )
    server._append_work_event(
        "session-a",
        {
            "event_id": "tool-run-a",
            "id": "tool-run-a",
            "sequence": 2,
            "turn_id": "run-a",
            "run_id": "run-a",
            "kind": "tool",
            "status": "success",
            "event_type": "tool.completed",
        },
    )
    server._append_work_event(
        "session-a",
        {
            "event_id": "other-run",
            "id": "other-run",
            "sequence": 3,
            "turn_id": "run-b",
            "run_id": "run-b",
            "kind": "tool",
            "status": "success",
            "event_type": "tool.completed",
        },
    )

    with TestClient(app) as client:
        list_response = client.get("/api/runs?session_id=session-a")
        get_response = client.get("/api/runs/session-a/run-a")
        replay_response = client.get("/api/work-events?session_id=session-a&limit=20", headers={"Last-Event-ID": "1"})

    assert list_response.status_code == 200
    listed = list_response.json()["runs"]
    assert len(listed) == 1
    assert listed[0]["run_id"] == "run-a"
    assert "_path" not in listed[0]
    assert listed[0]["work_events"]["event_count"] == 2
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["run"]["status"] == "success"
    assert [event["turn_id"] for event in payload["events"]] == ["run-a", "run-a"]
    assert payload["work_events"]["kinds"] == {"run": 1, "tool": 1}
    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert [event["sequence"] for event in replay["events"]] == [2, 3]
    assert replay["after_sequence"] == 1
    assert replay["next_sequence"] == 3


def test_server_work_event_append_assigns_monotonic_sequences(tmp_path, monkeypatch):
    import server
    from server import app

    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "work_events"))
    server._WORK_EVENT_SEQUENCES.clear()

    first = server._append_work_event("session-b", {"id": "first", "kind": "tool", "status": "running"})
    second = server._append_work_event("session-b", {"id": "second", "kind": "tool", "status": "success"})
    explicit = server._append_work_event("session-b", {"id": "explicit", "sequence": 10, "kind": "tool", "status": "success"})
    after_explicit = server._append_work_event("session-b", {"id": "after-explicit", "kind": "tool", "status": "success"})

    with TestClient(app) as client:
        replay_response = client.get(
            "/api/work-events?session_id=session-b&limit=20",
            headers={"Last-Event-ID": "10"},
        )

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert explicit["sequence"] == 10
    assert after_explicit["sequence"] == 11
    assert replay_response.status_code == 200
    replay = replay_response.json()
    assert [event["id"] for event in replay["events"]] == ["after-explicit"]
    assert replay["next_sequence"] == 11
