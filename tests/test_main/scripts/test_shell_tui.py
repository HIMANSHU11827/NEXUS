import asyncio
import io
from typing import Any, cast

from rich.console import Console

import shell


def capture_console(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(shell, "console", Console(file=output, force_terminal=False, color_system=None))
    return output


def test_run_bash_streams_output_and_reports_exit_code(monkeypatch, tmp_path):
    output = capture_console(monkeypatch)
    nexus_shell = shell.NexusShell()
    nexus_shell._brain = cast(Any, type("Brain", (), {"root": str(tmp_path)})())

    code = nexus_shell._run_bash('python -c "print(\'REAL_OUTPUT\')"')

    rendered = output.getvalue()
    assert code == 0
    assert "Command started:" in rendered
    assert "REAL_OUTPUT" in rendered
    assert "Command completed · exit code 0" in rendered


def test_agent_shortcuts_queue_real_work_instead_of_fake_completion(monkeypatch):
    output = capture_console(monkeypatch)
    nexus_shell = shell.NexusShell()

    assert nexus_shell._handle_slash("/verify") is True
    assert nexus_shell._pending_agent_prompt is not None
    assert nexus_shell._pending_agent_prompt.startswith("Verify the current project changes")
    assert nexus_shell._pending_task_id
    assert "COMPLETED" not in output.getvalue()
    assert shell.TaskTracker.list()[-1]["status"] == "running"


def test_stream_response_shows_real_phase_and_tool_summary(monkeypatch):
    output = capture_console(monkeypatch)

    class FakeBrain:
        async def stream_run(self, _prompt):
            yield {"type": "status", "data": "[inference]"}
            yield {
                "type": "tools_discovered",
                "tool_calls": [{"name": "bash", "arguments": {"command": "echo safe"}}],
            }
            yield {"type": "status", "data": "[executing]"}
            yield {"type": "observations", "data": ["safe"]}
            yield {"type": "content", "data": "done"}

    nexus_shell = shell.NexusShell()
    nexus_shell._brain = cast(Any, FakeBrain())
    monkeypatch.setattr("utils.session_bus.sync_loop_from_disk", lambda: None)

    text, interrupted, _files, _tools = asyncio.run(nexus_shell._stream_response("test"))

    rendered = output.getvalue()
    assert interrupted is False
    assert text == "done"
    assert "inference" in rendered
    assert "bash" in rendered
    assert "echo safe" in rendered
    assert "Tools:" in rendered
    assert "bash: echo safe" in rendered or "bash" in rendered


def test_stream_response_renders_public_structured_work_events(monkeypatch):
    output = capture_console(monkeypatch)

    class EventBrain:
        async def stream_run(self, _prompt):
            yield {
                "type": "work_event",
                "event": {
                    "kind": "command",
                    "action": "Run command",
                    "target": "python -m pytest tests/unit",
                    "status": "running",
                    "visibility": "public",
                },
            }
            yield {"type": "content", "data": "verified"}

    nexus_shell = shell.NexusShell()
    nexus_shell._brain = cast(Any, EventBrain())
    monkeypatch.setattr("utils.session_bus.sync_loop_from_disk", lambda: None)

    text, interrupted, _files, _tools = asyncio.run(nexus_shell._stream_response("verify"))

    assert interrupted is False
    assert text == "verified"
    rendered = output.getvalue()
    assert "$ python -m pytest tests/unit" in rendered
    assert "running" in rendered


def test_stream_response_hides_internal_error_work_events(monkeypatch):
    output = capture_console(monkeypatch)

    class EventBrain:
        async def stream_run(self, _prompt):
            yield {
                "type": "work_event",
                "event": {
                    "kind": "error",
                    "action": "Internal verifier diagnostic",
                    "target": "hidden prompt evidence",
                    "status": "error",
                    "visibility": "internal",
                },
            }
            yield {"type": "content", "data": "request failed safely"}

    nexus_shell = shell.NexusShell()
    nexus_shell._brain = cast(Any, EventBrain())
    monkeypatch.setattr("utils.session_bus.sync_loop_from_disk", lambda: None)

    text, interrupted, _files, _tools = asyncio.run(nexus_shell._stream_response("verify"))

    assert interrupted is False
    assert text == "request failed safely"
    assert "Internal verifier diagnostic" not in output.getvalue()
    assert "hidden prompt evidence" not in output.getvalue()


def test_stream_response_renders_pure_canonical_event_envelope(monkeypatch):
    output = capture_console(monkeypatch)

    class EventBrain:
        async def stream_run(self, _prompt):
            yield {
                "type": "work_event",
                "event": {
                    "event_id": "evt-canonical",
                    "run_id": "run-1",
                    "conversation_id": "session-1",
                    "type": "command.completed",
                    "title": "Run checks",
                    "status": "success",
                    "timestamp": 1.0,
                    "sequence": 3,
                    "duration_ms": 42,
                    "exit_code": 0,
                    "related_command": "pytest -q",
                    "payload": {"visibility": "public"},
                },
            }

    nexus_shell = shell.NexusShell()
    nexus_shell._brain = cast(Any, EventBrain())
    monkeypatch.setattr("utils.session_bus.sync_loop_from_disk", lambda: None)

    asyncio.run(nexus_shell._stream_response("verify"))

    rendered = output.getvalue()
    assert "$ pytest -q" in rendered
    assert "exit 0" in rendered
    assert "42" in rendered
    assert "success" in rendered


def test_ink_clients_keep_real_public_agent_event_kinds():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    interactive = (root / "tui" / "nexus-tui.tsx").read_text(encoding="utf-8")
    headless = (root / "tui" / "nexus-tui-headless.ts").read_text(encoding="utf-8")

    for source in (interactive, headless):
        for kind in ("mcp", "skill", "plugin", "hive", "provider", "rag", "approval"):
            assert f"'{kind}'" in source
    assert "upsertWorkEventActivity(event)" in interactive
    assert "setIsThinking(['queued', 'pending', 'running', 'in_progress'].includes" in interactive
    for source in (interactive, headless):
        assert "visibility !== 'public' || !PUBLIC_ACTIVITY_KINDS.has" in source


def _unique_work_session(prefix: str) -> str:
    import uuid

    return f"pytest-{prefix}-{uuid.uuid4().hex[:10]}"


def _cleanup_work_session(session_id: str) -> None:
    import os

    import server

    try:
        os.remove(server.work_events_path(session_id))
    except OSError:
        pass


def test_work_events_collapse_only_stable_event_ids_with_latest_update_winning():
    """A stable event id must render ONCE, holding its latest state, at its
    first-seen position; id-less events must never be collapsed together."""
    import server

    session = _unique_work_session("collapse")
    try:
        server.append_work_event(session, {
            "event_id": "evt-cmd", "kind": "command", "action": "Run checks",
            "target": "pytest -q", "status": "running", "visibility": "public",
        })
        server.append_work_event(session, {
            "event_id": "evt-file", "kind": "file", "action": "Edit file",
            "target": "a.py", "status": "running", "visibility": "public",
        })
        server.append_work_event(session, {
            "event_id": "evt-cmd", "kind": "command", "action": "Run checks",
            "target": "pytest -q", "status": "success", "exit_code": 0, "visibility": "public",
        })
        server.append_work_event(session, {
            "kind": "search", "action": "Anonymous A", "status": "success", "visibility": "public",
        })
        server.append_work_event(session, {
            "kind": "search", "action": "Anonymous B", "status": "success", "visibility": "public",
        })
        server.append_work_event(session, {
            "event_id": "evt-hidden", "kind": "error", "action": "internal only",
            "status": "failed", "visibility": "internal",
        })

        events = server.list_work_events(session, limit=100)
        ids = [str(event.get("event_id") or "") for event in events]

        # stable ids collapse to one row each
        assert ids.count("evt-cmd") == 1
        assert ids.count("evt-file") == 1
        # first-seen order preserved: the completed command stays ahead of the file
        assert ids.index("evt-cmd") < ids.index("evt-file")
        # latest update wins
        collapsed = next(event for event in events if event.get("event_id") == "evt-cmd")
        assert collapsed["status"] == "success"
        assert collapsed.get("exit_code") == 0
        # id-less events are distinct rows, never merged
        titles = [str(event.get("title") or event.get("action") or "") for event in events]
        assert "Anonymous A" in titles and "Anonymous B" in titles
        # internal events never reach the timeline
        assert "evt-hidden" not in ids
    finally:
        _cleanup_work_session(session)


def test_ink_stop_aborts_the_real_stream_and_retry_uses_original_prompt():
    """/stop must abort the live fetch (not just hide spinners) and /retry must
    resend the ORIGINAL user prompt verbatim."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    interactive = (root / "tui" / "nexus-tui.tsx").read_text(encoding="utf-8")

    # the chat request is genuinely abortable
    assert "signal: controller.signal" in interactive
    assert "chatAbortControllerRef.current = controller" in interactive or "chatAbortControllerRef.current" in interactive
    # /stop aborts the controller instead of faking a stopped UI state
    stop_block = interactive.split("command === '/stop'", 1)[1][:500]
    assert "chatAbortControllerRef.current.abort()" in stop_block
    assert "stopped visible working state" not in interactive
    # abort is surfaced as a cancellation, not an error
    assert "name === 'AbortError'" in interactive
    assert "completeRunningActivities('cancelled')" in interactive
    # /retry replays the last user prompt exactly, and never a slash command
    retry_block = interactive.split("command === '/retry'", 1)[1][:900]
    assert "message.role === 'user'" in retry_block
    assert "handleSubmit(lastUserPrompt)" in retry_block
    assert "lastUserPrompt.startsWith('/')" in retry_block
    assert "{name: '/retry'" in interactive


def test_canonical_envelope_adaptation_and_replay_sequence_guard():
    """Loose work events become canonical envelopes, and replay by cursor never
    re-delivers already-seen events nor loses sequence ordering."""
    import server
    from nexus.events import CanonicalEvent

    canonical = CanonicalEvent.from_work_event(
        {
            "id": "evt-adapt", "kind": "command", "action": "Run checks",
            "status": "success", "command": "pytest -q", "exit_code": 0,
            "duration_ms": 42, "visibility": "public", "payload": {"extra": 1},
        },
        "session-1",
        7,
    ).to_dict()

    assert canonical["event_id"] == "evt-adapt"
    assert canonical["conversation_id"] == "session-1"
    assert canonical["sequence"] == 7
    assert canonical["title"] == "Run checks"
    assert canonical["related_command"] == "pytest -q"
    assert canonical["exit_code"] == 0
    assert canonical["duration_ms"] == 42
    # unknown fields survive inside payload rather than being dropped
    assert canonical["payload"]["visibility"] == "public"
    assert canonical["payload"]["extra"] == 1

    session = _unique_work_session("replay")
    try:
        stored = [
            server.append_work_event(session, {
                "event_id": f"evt-{index}", "kind": "command", "action": f"step {index}",
                "status": "success", "visibility": "public",
            })
            for index in range(4)
        ]
        sequences = [int(event["sequence"]) for event in stored]
        assert sequences == sorted(sequences) and len(set(sequences)) == 4

        cursor = sequences[1]
        replayed = server.replay_work_events_after(session, cursor)
        replayed_sequences = [int(event["sequence"]) for event in replayed]
        # nothing at or before the cursor is re-delivered (duplicate guard)
        assert all(sequence > cursor for sequence in replayed_sequences)
        assert replayed_sequences == sorted(replayed_sequences)
        assert replayed_sequences == sequences[2:]
        # exhausted cursor yields nothing
        assert server.replay_work_events_after(session, sequences[-1]) == []
        # collapsed listing honours the same cursor guard
        listed = server.list_work_events(session, limit=100, after_sequence=cursor)
        assert [int(event["sequence"]) for event in listed] == sequences[2:]
    finally:
        _cleanup_work_session(session)

    # clients adapt the same envelope shape before rendering, and dedupe replays
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    interactive = (root / "tui" / "nexus-tui.tsx").read_text(encoding="utf-8")
    headless = (root / "tui" / "nexus-tui-headless.ts").read_text(encoding="utf-8")
    for source in (interactive, headless):
        assert "adaptCanonicalEvent" in source
        assert "input.event_id || input.id" in source
        assert "input.related_command" in source
    assert "if (!acceptWorkEvent(event)) return;" in interactive
    assert "seenWorkEventIds.current.has(identity)" in interactive
