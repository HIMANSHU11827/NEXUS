import json
import queue
from pathlib import Path

from fastapi.testclient import TestClient
from nexus.events import EVENT_STATUSES, EVENT_TYPES, CanonicalEvent
from nexus.run_context import start_run_context
from gui import api
from starlette.requests import Request


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


def test_canonical_event_registry_covers_required_runtime_families():
    assert EVENT_STATUSES == {"pending", "running", "success", "failed", "skipped", "cancelled"}
    for family in ("run", "conversation", "message", "plan", "phase", "tool", "command", "file", "search", "web", "test", "subagent", "handoff", "memory", "skill"):
        assert any(event_type.startswith(f"{family}.") for event_type in EVENT_TYPES), family


def test_gui_loop_structured_event_sink_persists_canonical_events(tmp_path, monkeypatch):
    class FakeLoop:
        def __init__(self, root_dir):
            self.root_dir = root_dir
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
    monkeypatch.setattr(api, "_ROOT", str(tmp_path))
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


def test_chat_endpoint_rejects_empty_prompt_before_loop_lookup(monkeypatch):
    def fail_get_loop(_session_id):
        raise AssertionError("empty prompt should be rejected before loop lookup")

    monkeypatch.setattr(api, "get_loop", fail_get_loop)

    with TestClient(api.app) as client:
        response = client.post("/api/chat", json={"prompt": "   ", "session_id": "empty-chat"})

    assert response.status_code == 400
    assert "prompt is required" in response.json()["message"]


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
    }


def test_active_stream_blocks_background_session_overwrite():
    app_source = (Path(__file__).parents[3] / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "const activeStreamSessionRef = useRef('')" in app_source
    assert "if (activeStreamSessionRef.current) return;" in app_source
    assert "if (activeStreamSessionRef.current === sid) return;" in app_source


def test_workspace_visibility_uses_public_allowlist():
    source = (Path(__file__).parents[3] / "gui" / "src" / "utils" / "workActivityUtils.ts").read_text(encoding="utf-8")
    assert "if (String(row.visibility || '').toLowerCase() === 'internal') return false;" in source
    assert "'prompt_files'" in source
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
    source = (Path(__file__).parents[3] / "orchestrators" / "loop.py").read_text(encoding="utf-8")
    assert "plan_items = [" in source
    assert 'payload["items"] = items' in source
    assert 'enumerate(items, start=1)' in source


def test_timeline_never_fabricates_thinking_or_next_action_cards():
    source = (Path(__file__).parents[3] / "gui" / "src" / "components" / "WorkActivityTimeline.tsx").read_text(encoding="utf-8")
    assert "evt_thinking_virtual" not in source
    assert "No captured reasoning yet" not in source
    assert "<code>next action</code>" not in source
    assert 'role="status" aria-live="polite"' in source


def test_frontend_preserves_actionable_failure_approval_and_retry_events():
    source = (Path(__file__).parents[3] / "gui" / "src" / "utils" / "workActivityUtils.ts").read_text(encoding="utf-8")
    assert "event.error || event.message || fallbackTarget" in source
    assert "kind.includes('approval')" in source
    assert "kind.includes('retry')" in source
    assert "kind.includes('error')" in source


def test_session_activity_fetch_is_request_scoped_and_full_history_is_unfiltered():
    source = (Path(__file__).parents[3] / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "const requestId = ++workEventsRequestRef.current" in source
    assert "currentSessionIdRef.current !== sid" in source
    assert "loadWorkEvents(sid, '')" in source
    assert "workEventsFetchInFlightRef" not in source


def test_event_only_turns_stay_visible_and_replay_uses_event_indices():
    root = Path(__file__).parents[3] / "gui" / "src"
    message_source = (root / "components" / "chat" / "MessageBubble.tsx").read_text(encoding="utf-8")
    canvas_source = (root / "components" / "CanvasPanel.tsx").read_text(encoding="utf-8")
    app_source = (root / "App.tsx").read_text(encoding="utf-8")
    assert "!isStreaming && !hasVisibleTimeline" in message_source
    assert "Waiting for agent activity" in message_source
    assert "Good response" not in message_source
    assert "Bad response" not in message_source
    assert "Event ${Math.min" in canvas_source
    assert "canvasPlaybackTime / 5" not in app_source
    assert "(allWorkActivities.length - 1) * 5" not in canvas_source


def test_network_and_empty_stream_failures_are_visible_in_the_turn():
    source = (Path(__file__).parents[3] / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "NEXUS could not complete this turn" in source
    assert "finished without returning a response or public work evidence" in source
    assert "NEXUS disconnected. Your prompt is restored so you can retry." in source


def test_live_gui_state_is_bounded_and_keeps_stable_id_deduplication():
    root = Path(__file__).parents[3] / "gui" / "src"
    utility = (root / "utils" / "workActivityUtils.ts").read_text(encoding="utf-8")
    app = (root / "App.tsx").read_text(encoding="utf-8")
    assert "MAX_LIVE_WORK_EVENTS = 500" in utility
    assert "merged.slice(-limit)" in utility
    assert "mergeLiveWorkEvents(previous, events)" in app
    assert "eventAny.id || `unkeyed:${eventIndex}`" in app


def test_live_command_output_is_tail_bounded_before_rendering():
    root = Path(__file__).parents[3] / "gui" / "src"
    utility = (root / "utils" / "workActivityUtils.ts").read_text(encoding="utf-8")
    app = (root / "App.tsx").read_text(encoding="utf-8")
    assert "MAX_LIVE_OUTPUT_CHARS = 256 * 1024" in utility
    assert "earlier output omitted" in utility
    assert "stdout = boundedLiveOutput(stdout + text)" in app
    assert "stderr = boundedLiveOutput(stderr + text)" in app
