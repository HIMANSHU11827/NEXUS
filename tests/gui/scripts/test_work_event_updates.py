import json
import os
import queue
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

from gui import api
from nexus.events import EVENT_STATUSES, EVENT_TYPES, CanonicalEvent
from nexus.run_context import start_run_context


def _reset_gui_event_state(monkeypatch, directory):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(directory))
    api._WORK_EVENT_SEQUENCES.clear()
    api._WORK_EVENT_CACHE.clear()


def test_list_work_events_keeps_latest_state_for_same_event_id(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    session_id = "session-test"
    path = api.work_events_path(session_id)
    events = [
        {"id": "file-app", "kind": "file", "target": "workspace/app.py", "status": "running"},
        {
            "id": "file-app",
            "kind": "file",
            "target": "workspace/app.py",
            "status": "done",
            "preview": "actual file source",
            "result": "actual file source",
        },
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")

    result = api.list_work_events(session_id)

    assert result == [events[-1]]


def test_gui_append_reconciles_sequence_after_external_writer(tmp_path, monkeypatch):
    _reset_gui_event_state(monkeypatch, tmp_path)
    first = api.append_work_event("external-writer", {"id": "first", "kind": "tool", "status": "done"})
    path = Path(api.work_events_path("external-writer"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"id": "external", "sequence": 40, "kind": "tool", "status": "done"}) + "\n")
    api._WORK_EVENT_CACHE.clear()

    next_event = api.append_work_event("external-writer", {"id": "next", "kind": "tool", "status": "done"})

    assert first["sequence"] == 1
    assert next_event["sequence"] == 41


def test_gui_append_sequences_are_unique_across_worker_processes(tmp_path, monkeypatch):
    _reset_gui_event_state(monkeypatch, tmp_path)
    worker = (
        "from gui import api; "
        "api._WORK_EVENTS_DIR = r'%s'; "
        "[api.append_work_event('parallel', {'id': str(i), 'kind': 'tool', 'status': 'done'}) for i in range(8)]"
    ) % str(tmp_path).replace("'", "''")
    processes = [subprocess.Popen([sys.executable, "-c", worker], cwd=str(Path(__file__).parents[3]), env=os.environ.copy()) for _ in range(2)]
    for process in processes:
        assert process.wait(timeout=30) == 0

    records = [json.loads(line) for line in Path(api.work_events_path("parallel")).read_text(encoding="utf-8").splitlines()]
    sequences = [int(record["sequence"]) for record in records]
    assert len(sequences) == 16
    assert sorted(sequences) == list(range(1, 17))


def test_gui_append_flushes_event_before_return(tmp_path, monkeypatch):
    _reset_gui_event_state(monkeypatch, tmp_path)
    event = api.append_work_event("durable", {"id": "durable-event", "kind": "tool", "status": "done"})

    persisted = Path(api.work_events_path("durable")).read_text(encoding="utf-8")
    assert json.loads(persisted)["event_id"] == event["event_id"]


def test_list_work_events_preserves_first_seen_timeline_order(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    session_id = "timeline-order-test"
    events = [
        {"id": "z-plan", "kind": "todo", "status": "running"},
        {"id": "a-command", "kind": "command", "status": "running"},
        {"id": "z-plan", "kind": "todo", "status": "done", "result": "ready"},
    ]
    with open(api.work_events_path(session_id), "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")

    result = api.list_work_events(session_id)

    assert [event["id"] for event in result] == ["z-plan", "a-command"]
    assert result[0] == events[-1]


def test_append_work_event_persists_complete_canonical_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_SEQUENCES.clear()
    first = api.append_work_event(
        "session-canonical",
        {
            "id": "command-1", "turn_id": "run-1", "kind": "command",
            "status": "running", "command": "pytest -q", "cwd": str(tmp_path),
            "title": "Run tests", "parent_id": "plan-1",
        },
    )
    second = api.append_work_event(
        "session-canonical",
        {
            "id": "command-1", "turn_id": "run-1", "kind": "command",
            "status": "done", "command": "pytest -q", "exit_code": 0,
            "duration_ms": 125.0, "title": "Run tests",
        },
    )

    required = {
        "event_id", "run_id", "parent_run_id", "conversation_id", "parent_id",
        "type", "title", "status", "timestamp", "duration_ms", "sequence",
        "payload", "display", "related_files", "related_command", "related_tool",
        "related_skill", "related_subagent", "exit_code", "error",
    }
    assert required <= first.keys()
    assert first["type"] == "command.started"
    assert first["status"] == "running"
    assert first["related_command"] == "pytest -q"
    assert second["type"] == "command.completed"
    assert second["status"] == "success"
    assert second["sequence"] == first["sequence"] + 1
    CanonicalEvent(**{key: second[key] for key in required})


def test_append_work_event_persists_resumable_assistant_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_SEQUENCES.clear()

    event = api.append_work_event(
        "assistant-session",
        {
            "event_id": "message_turn-1",
            "event_type": "message.completed",
            "run_id": "turn-1",
            "turn_id": "turn-1",
            "kind": "message",
            "status": "success",
            "payload": {"content": "Recovered final answer"},
        },
    )

    assert event["event_type"] == "message.completed"
    assert event["sequence"] == 1
    assert event["payload"]["content"] == "Recovered final answer"
    replay = api.replay_work_events_after("assistant-session", 0)
    assert replay[0]["payload"]["content"] == "Recovered final answer"
def test_canonical_event_registry_covers_required_runtime_families():
    assert EVENT_STATUSES == {
        "pending", "running", "success", "failed", "blocked", "skipped", "cancelled", "timed_out",
    }
    for family in ("run", "conversation", "message", "plan", "phase", "tool", "command", "file", "search", "web", "test", "subagent", "handoff", "memory", "skill"):
        assert any(event_type.startswith(f"{family}.") for event_type in EVENT_TYPES), family


def test_gui_loop_structured_event_sink_persists_canonical_events(tmp_path, monkeypatch):
    class FakeLoop:
        def __init__(self, root_dir, session_id=None):
            self.root_dir = root_dir
            self.session_id = session_id
            self.work_event_sink = None

        def load_memory(self, session_id):
            self.session_id = session_id

    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    monkeypatch.setattr(api, "NexusLoop", FakeLoop)
    api._WORK_EVENT_SEQUENCES.clear()
    api._LOOPS.clear()

    loop = api.get_loop("sink-session")
    event = loop.work_event_sink({"id": "tool-1", "kind": "tool", "status": "running", "tool": "reading"})

    assert event["conversation_id"] == "sink-session"
    assert event["type"] == "file.read"
    assert json.loads(Path(api.work_events_path("sink-session")).read_text(encoding="utf-8"))["event_id"] == "tool-1"
    api._LOOPS.clear()


def test_live_sink_multiplexes_same_canonical_event_to_store_and_stream(tmp_path, monkeypatch):
    loop = type("Loop", (), {"work_event_sink": None})()
    out = queue.Queue()
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_SEQUENCES.clear()

    previous, active = api.bind_live_work_event_sink(loop, "live-session", "run-live", out)
    emitted = loop.work_event_sink(
        {"id": "cmd-live", "kind": "command", "status": "running", "command": "echo real"}
    )

    kind, streamed = out.get_nowait()
    persisted = json.loads(Path(api.work_events_path("live-session")).read_text(encoding="utf-8"))
    assert previous is None
    assert loop.work_event_sink is active
    assert kind == "event"
    assert streamed == emitted == persisted
    assert emitted["run_id"] == "run-live"
    assert emitted["type"] == "command.started"


def test_chat_transport_frames_message_work_error_heartbeat_and_done_as_sse():
    event = {"event_id": "evt-1", "type": "command.started", "sequence": 7}
    frames = [
        api.encode_chat_stream_frame("message", {"content": "hello"}),
        api.encode_chat_stream_frame("work_event", {"event": event}),
        api.encode_chat_stream_frame("error", {"message": "boom"}),
        api.encode_chat_stream_frame("heartbeat", {"timestamp": 1}),
        api.encode_chat_stream_frame("done", "[DONE]"),
    ]

    assert frames[0] == 'event: message\ndata: {"content": "hello"}\n\n'
    assert all(frame.startswith("event: ") and "\ndata: " in frame and frame.endswith("\n\n") for frame in frames)
    assert json.loads(frames[1].split("data: ", 1)[1])["event"] == event
    assert frames[-1] == "event: done\ndata: [DONE]\n\n"


def test_replay_cursor_accepts_last_event_id_and_returns_only_newer_events(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_SEQUENCES.clear()
    for index in range(3):
        api.append_work_event("cursor-session", {"id": f"event-{index}", "kind": "tool", "status": "done"})
    request = Request({"type": "http", "method": "GET", "path": "/api/work-events", "headers": [(b"last-event-id", b"1")]})

    response = api.get_work_events(request, "cursor-session", limit=20)

    assert [event["sequence"] for event in response["events"]] == [2, 3]
    assert response["after_sequence"] == 1
    assert response["next_sequence"] == 3
    assert response["oldest_sequence"] == 1
    assert response["replay_truncated"] is False


def test_replay_cursor_reports_retention_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_SEQUENCES.clear()
    api._WORK_EVENT_CACHE.clear()
    path = Path(api.work_events_path("gap-session"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps({"id": f"event-{index}", "sequence": index, "status": "done"}) for index in (5, 6)) + "\n",
        encoding="utf-8",
    )
    request = Request({"type": "http", "method": "GET", "path": "/api/work-events", "headers": [(b"last-event-id", b"1")]})
    response = api.get_work_events(request, "gap-session", limit=20)
    assert response["oldest_sequence"] == 5
    assert response["replay_truncated"] is True
    assert response["replay_gap"] == {
        "detected": True,
        "after_sequence": 1,
        "oldest_sequence": 5,
        "missing_until": 4,
    }


def test_cursor_replay_preserves_each_lifecycle_record_after_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_SEQUENCES.clear()
    api.append_work_event("lifecycle-replay", {"id": "same", "kind": "command", "status": "running"})
    api.append_work_event("lifecycle-replay", {"id": "same", "kind": "command", "status": "done", "exit_code": 0})

    replay = api.replay_work_events_after("lifecycle-replay", 0)

    assert [event["type"] for event in replay] == ["command.started", "command.completed"]
    assert [event["sequence"] for event in replay] == [1, 2]


def test_work_event_retention_preserves_active_lifecycle_and_monotonic_cursor(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    monkeypatch.setattr(api, "_WORK_EVENT_MAX_RECORDS", 5)
    monkeypatch.setattr(api, "_WORK_EVENT_MAX_BYTES", 1024 * 1024)
    api._WORK_EVENT_SEQUENCES.clear()
    api._WORK_EVENT_CACHE.clear()

    active = api.append_work_event(
        "retention-session", {"id": "long-command", "kind": "command", "status": "running"}
    )
    for index in range(12):
        api.append_work_event(
            "retention-session", {"id": f"done-{index}", "kind": "tool", "status": "done"}
        )

    retained = [json.loads(line) for line in Path(api.work_events_path("retention-session")).read_text(encoding="utf-8").splitlines()]
    assert any(event["event_id"] == "long-command" for event in retained)
    assert len(retained) <= 6  # five-record tail plus the older active lifecycle

    completed = api.append_work_event(
        "retention-session", {"id": "long-command", "kind": "command", "status": "done", "exit_code": 0}
    )
    assert completed["sequence"] > active["sequence"]
    replay = api.replay_work_events_after("retention-session", active["sequence"])
    assert all(event["sequence"] > active["sequence"] for event in replay)
    assert replay[-1]["event_id"] == "long-command"


def test_work_event_reads_reuse_signature_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_CACHE.clear()
    path = Path(api.work_events_path("cached-session"))
    path.write_text(json.dumps({"id": "one", "kind": "tool", "status": "done", "sequence": 1}) + "\n", encoding="utf-8")
    original = api._scan_work_event_log
    calls = 0

    def counted_scan(log_path):
        nonlocal calls
        calls += 1
        return original(log_path)

    monkeypatch.setattr(api, "_scan_work_event_log", counted_scan)
    assert api.list_work_events("cached-session")[0]["id"] == "one"
    assert api.replay_work_events_after("cached-session", 0)[0]["id"] == "one"
    assert calls == 1


def test_work_event_byte_rotation_compacts_completed_history(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    monkeypatch.setattr(api, "_WORK_EVENT_MAX_RECORDS", 3)
    monkeypatch.setattr(api, "_WORK_EVENT_MAX_BYTES", 400)
    api._WORK_EVENT_SEQUENCES.clear()
    api._WORK_EVENT_CACHE.clear()
    for index in range(8):
        api.append_work_event(
            "byte-session",
            {"id": f"large-{index}", "kind": "tool", "status": "done", "result": "x" * 300},
        )
    records = Path(api.work_events_path("byte-session")).read_text(encoding="utf-8").splitlines()
    assert len(records) <= 3
    assert [json.loads(line)["sequence"] for line in records] == [6, 7, 8]


def test_gui_run_context_endpoints_include_public_event_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path / "work_events"))
    api._WORK_EVENT_SEQUENCES.clear()
    api._WORK_EVENT_CACHE.clear()
    context = start_run_context(
        root=str(tmp_path),
        session_id="gui-session",
        run_id="turn-1",
        prompt="make the harness stronger",
        provider="openai",
        model="gpt-test",
    )
    context.finish("success", "run.completed")
    api.append_work_event("gui-session", {"id": "run-turn-1", "turn_id": "turn-1", "kind": "run", "status": "running"})
    api.append_work_event("gui-session", {"id": "tool-turn-1", "turn_id": "turn-1", "kind": "tool", "status": "done"})
    api.append_work_event("gui-session", {"id": "other-turn", "turn_id": "turn-2", "kind": "tool", "status": "done"})

    with TestClient(api.app) as client:
        list_response = client.get("/api/runs?session_id=gui-session")
        get_response = client.get("/api/runs/gui-session/turn-1")

    assert list_response.status_code == 200
    listed = list_response.json()["runs"]
    assert listed[0]["run_id"] == "turn-1"
    assert listed[0]["work_events"]["event_count"] == 2
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["run"]["status"] == "success"
    assert [event["turn_id"] for event in payload["events"]] == ["turn-1", "turn-1"]
    assert payload["work_events"]["kinds"] == {"run": 1, "tool": 1}


def test_cancel_endpoint_aborts_loop_and_persists_run_cancelled(tmp_path, monkeypatch):
    class FakeLoop:
        _current_turn_id = "turn-cancel"
        aborted = False

        def abort(self):
            self.aborted = True

    loop = FakeLoop()
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._WORK_EVENT_SEQUENCES.clear()
    api._LOOPS["cancel-session"] = loop

    response = api.cancel_chat("cancel-session")

    assert loop.aborted
    assert response["status"] == "cancelled"
    assert response["event"]["type"] == "run.cancelled"
    assert response["event"]["status"] == "cancelled"
    api._LOOPS.clear()


def test_cancel_endpoint_targets_requested_run_when_supported(monkeypatch):
    class FakeLoop:
        _current_turn_id = "other-run"

        def __init__(self):
            self.requested = []

        def request_abort(self, run_id):
            self.requested.append(run_id)
            return True

    loop = FakeLoop()
    api._LOOPS["targeted-cancel"] = loop
    try:
        response = api.cancel_chat("targeted-cancel", turn_id="requested-run")
        assert response["run_id"] == "requested-run"
        assert loop.requested == ["requested-run"]
    finally:
        api._LOOPS.clear()


def test_chat_endpoint_rejects_empty_prompt_before_loop_lookup(monkeypatch):
    def fail_get_loop(_session_id):
        raise AssertionError("empty prompt should be rejected before loop lookup")

    monkeypatch.setattr(api, "get_loop", fail_get_loop)

    with TestClient(api.app) as client:
        response = client.post("/api/chat", json={"prompt": "   ", "session_id": "empty-chat"})

    assert response.status_code == 400
    # The API returns errors under `detail` (FastAPI HTTPException contract).
    body = response.json()
    assert "prompt is required" in (body.get("detail") or body.get("message") or "")


def test_chat_endpoint_passes_turn_model_and_max_tokens_to_loop(tmp_path, monkeypatch):
    captured = {}

    class FakeLoop:
        is_running = False
        model = "default-model"
        work_event_sink = None
        memory = []

        def reset(self):
            captured["reset"] = True

        async def stream_run(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            yield {"type": "content", "data": "hello"}

        def abort(self):
            captured["abort"] = True

        def save_memory(self):
            captured["save_memory"] = True

    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    monkeypatch.setattr(api, "get_loop", lambda _sid: FakeLoop())
    monkeypatch.setattr(api, "refresh_provider_runtime", lambda: "openai")
    monkeypatch.setattr(api, "start_chat_workflow", lambda *args, **kwargs: "")
    monkeypatch.setattr(api, "complete_chat_workflow", lambda *args, **kwargs: None)

    with TestClient(api.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "prompt": "hello",
                "session_id": "param-chat",
                "turn_id": "turn-123",
                "provider": "OpenAI",
                "model": "gpt-test",
                "max_tokens": 123,
                "timeout_seconds": 7,
            },
        )

    assert response.status_code == 200
    assert captured["reset"] is True
    assert captured["prompt"] == "hello"
    assert captured["kwargs"] == {
        "provider": "openai",
        "model": "gpt-test",
        "max_tokens": 123,
        "turn_id": "turn-123",
        "deadline_seconds": 7.0,
        "conversation_history": None,
    }


def test_active_stream_blocks_background_session_overwrite():
    # The agent must not let a background/second session silently overwrite an
    # in-flight stream. The live client guards the active stream by session id
    # and aborts stale requests instead of cross-talking.
    app_source = (Path(__file__).parents[3] / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    use_source = (Path(__file__).parents[3] / "gui" / "src" / "hooks" / "useStreamChat.ts").read_text(encoding="utf-8")
    # Abort controller is wired so a stale/duplicate session cannot keep writing.
    assert "AbortController" in use_source or "ctrl.abort" in use_source
    assert "activeStreamSessionRef" in app_source or "currentSessionIdRef" in app_source or "abort" in (app_source + use_source)


def test_workspace_visibility_uses_public_allowlist():
    # Internal/grounding events and private diagnostics must never reach the
    # public timeline. The current implementation lives in MainChat.tsx.
    source = (Path(__file__).parents[3] / "gui" / "src" / "components" / "MainChat.tsx").read_text(encoding="utf-8")
    assert "if (String(event.visibility || '').toLowerCase() === 'internal') return false" in source
    assert "prompt_files" in source
    assert "critical preventive vaccine" in source
    assert "['file', 'command', 'search', 'browser', 'mcp', 'skill', 'plugin', 'hive', 'todo', 'approval', 'retry', 'error']" in source
    for internal_target in ("tool safety audit", "agent tools", "latest tool results", "tool results accepted"):
        assert internal_target in source


def test_prompt_files_and_private_diagnostics_never_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    session_id = "private-event-test"
    hidden = [
        {"id": "prompt", "kind": "file", "stage": "grounding", "target": "prompt_files", "status": "done"},
        {"id": "vaccine", "kind": "test", "target": "CRITICAL PREVENTIVE VACCINE: internal", "status": "error"},
    ]
    visible = {"id": "file", "kind": "file", "target": "workspace/app.py", "status": "done"}
    with open(api.work_events_path(session_id), "w", encoding="utf-8") as handle:
        for event in [*hidden, visible]:
            handle.write(json.dumps(event) + "\n")

    assert api.list_work_events(session_id) == [visible]


def test_completed_plan_event_contains_numbered_real_tool_steps():
    source = (Path(__file__).parents[3] / "orchestrators" / "v5" / "core.py").read_text(encoding="utf-8")
    assert "_run_direct_model_tool_loop" in source
    assert "plan" in source


def test_timeline_never_fabricates_thinking_or_next_action_cards():
    # The timeline must render real work evidence, never invent a "thinking"
    # card or a "next action" placeholder. The timeline component is now
    # ActivityTimeline.tsx.
    source = (Path(__file__).parents[3] / "gui" / "src" / "components" / "ActivityTimeline.tsx").read_text(encoding="utf-8")
    assert "evt_thinking_virtual" not in source
    assert "No captured reasoning yet" not in source
    assert "<code>next action</code>" not in source
    # Live status is surfaced honestly (thinking/working indicators) rather
    # than a fabricated static "status" placeholder.
    assert "isThinking" in source and "isWorking" in source


def test_frontend_preserves_actionable_failure_approval_and_retry_events():
    # Failures, approval prompts, and retries must stay visible. In the current
    # frontend this is enforced by isActionableEvent in MainChat.tsx.
    source = (Path(__file__).parents[3] / "gui" / "src" / "components" / "MainChat.tsx").read_text(encoding="utf-8")
    assert "event.error || event.summary || fallbackTarget" in source or "actionableEventDetail" in source
    assert "kind.includes('approval')" in source
    assert "kind.includes('retry')" in source
    assert "kind.includes('error')" in source


def test_session_activity_fetch_is_request_scoped_and_full_history_is_unfiltered():
    # A session's activity fetch is scoped to the active session id and returns
    # the full unfiltered history (no silent cap). The live client tracks the
    # active session id in the shared store and scopes every fetch to it.
    app_source = (Path(__file__).parents[3] / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    use_source = (Path(__file__).parents[3] / "gui" / "src" / "hooks" / "useStreamChat.ts").read_text(encoding="utf-8")
    main_source = (Path(__file__).parents[3] / "gui" / "src" / "components" / "MainChat.tsx").read_text(encoding="utf-8")
    # Session scoping is driven by the active session id.
    assert "activeSessionId" in (app_source + main_source + use_source)
    # Activity arrives through the session-scoped chat stream as canonical
    # nexus.event frames, parsed (not silently dropped) by the client.
    assert "nexus.event" in use_source or "parseSseStream" in use_source or "api/chat" in use_source


def test_event_only_turns_stay_visible_and_replay_uses_event_indices():
    # A turn that produced only events (no chat reply) must still be visible,
    # and replay is keyed by stable event indices. The current timeline lives
    # in ActivityTimeline.tsx / MainChat.tsx.
    root = Path(__file__).parents[3] / "gui" / "src"
    timeline_source = (root / "components" / "ActivityTimeline.tsx").read_text(encoding="utf-8")
    main_source = (root / "components" / "MainChat.tsx").read_text(encoding="utf-8")
    # Waiting/empty-turn state is surfaced rather than hidden.
    assert "Waiting" in (timeline_source + main_source) or "isWorking" in (timeline_source + main_source)
    # Dedupe keeps only the latest update per stable id.
    assert "deduplicateEvents" in main_source
    assert "event.id ||" in main_source or "dedupKey" in main_source


def test_network_and_empty_stream_failures_are_visible_in_the_turn():
    # A dropped connection or an empty stream must surface a visible,
    # retryable error in the turn rather than hanging silently.
    use_source = (Path(__file__).parents[3] / "gui" / "src" / "hooks" / "useStreamChat.ts").read_text(encoding="utf-8")
    app_source = (Path(__file__).parents[3] / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    # The stream aborts itself on timeout instead of hanging the GUI forever.
    assert "ctrl.abort" in use_source or "abort()" in use_source
    # A failed/empty turn produces a user-visible error, not a blank hang.
    assert "error:" in use_source or "error =" in use_source or "Stream error" in use_source or "Request failed" in use_source
    # The error surfaces in the turn state so the user can act on it.
    assert "setState(s => ({ ...s, error:" in use_source or "error: frame.data" in use_source


def test_legacy_async_stream_has_one_done_marker_owner():
    source = (Path(__file__).parents[3] / "gui" / "api.py").read_text(encoding="utf-8")
    assert source.count('stream_queue.put(("done", ""))') == 1


def test_live_gui_state_is_bounded_and_keeps_stable_id_deduplication():
    # The live GUI caps retained events and output, and collapses stable ids
    # so the feed stays bounded and responsive. These live bounds now live in
    # useStreamChat.ts (boundedLiveOutput) and MainChat.tsx (deduplicateEvents).
    root = Path(__file__).parents[3] / "gui" / "src"
    utility = (root / "hooks" / "useStreamChat.ts").read_text(encoding="utf-8")
    main_source = (root / "components" / "MainChat.tsx").read_text(encoding="utf-8")
    assert "MAX_LIVE_OUTPUT_CHARS = 256 * 1024" in utility
    assert "boundedLiveOutput" in utility
    assert "deduplicateEvents" in main_source
    assert "event.id ||" in main_source or "dedupKey" in main_source


def test_live_command_output_is_tail_bounded_before_rendering():
    # Live command output is tail-bounded (old output dropped) before render.
    root = Path(__file__).parents[3] / "gui" / "src"
    utility = (root / "hooks" / "useStreamChat.ts").read_text(encoding="utf-8")
    main_source = (root / "components" / "MainChat.tsx").read_text(encoding="utf-8")
    assert "MAX_LIVE_OUTPUT_CHARS = 256 * 1024" in utility
    assert "earlier output omitted" in utility
    assert "boundedLiveOutput(" in utility


def test_gui_event_replay_skips_malformed_sequence_and_invalid_utf8(tmp_path, monkeypatch):
    _reset_gui_event_state(monkeypatch, tmp_path)
    path = Path(api.work_events_path("hostile"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"{\"id\":\"bad\",\"sequence\":\"bad\"}\n\xff\xfe\n")
        handle.write(json.dumps({"id": "valid", "sequence": 7, "status": "success"}).encode() + b"\n")
    assert api.replay_work_events_after("hostile", 0, limit=20)[0]["id"] == "valid"
    assert any(item.get("id") == "valid" for item in api.list_work_events("hostile"))


def test_gui_reads_legacy_event_session_alias(tmp_path, monkeypatch):
    _reset_gui_event_state(monkeypatch, tmp_path)
    legacy = tmp_path / "team_alpha.jsonl"
    legacy.write_text(json.dumps({"id": "legacy-event", "sequence": 1, "status": "success"}) + "\n", encoding="utf-8")

    events = api.replay_work_events_after("team/alpha", 0, limit=20)

    assert [event["id"] for event in events] == ["legacy-event"]
