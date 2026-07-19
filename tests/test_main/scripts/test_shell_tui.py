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


def test_gui_collapses_only_stable_event_ids_with_latest_update_winning():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    utility = (root / "gui" / "src" / "utils" / "workActivityUtils.ts").read_text(encoding="utf-8")
    app = (root / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "export const collapseWorkActivityUpdates" in utility
    assert "const id = String(row.event_id || row.id || '').trim()" in utility
    assert "collapsed[existingIndex] = { ...existing, ...row }" in utility
    assert "kind || row.type}|${row.target" not in app
    assert "return collapseWorkActivityUpdates(rows)" in app


def test_gui_and_ink_stop_abort_the_real_stream_and_retry_uses_original_prompt():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    app = (root / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    chat_input = (root / "gui" / "src" / "components" / "chat" / "ChatInput.tsx").read_text(encoding="utf-8")
    interactive = (root / "tui" / "nexus-tui.tsx").read_text(encoding="utf-8")

    for source in (app, interactive):
        assert "chatAbortControllerRef.current?.abort()" in source or "chatAbortControllerRef.current.abort()" in source
        assert "signal: controller.signal" in source
        assert "name === 'AbortError'" in source

    assert "aria-label={isStreaming ? 'Stop current turn' : 'Send message'}" in chat_input
    assert "if (isStreaming) stopCurrentTurn(); else handleSend();" in chat_input
    assert "void handleSend(lastUser.content)" in app
    assert "setTimeout(handleSend, 50)" not in app
    assert "stopped visible working state" not in interactive


def test_clients_adapt_canonical_envelope_and_guard_replay_sequence():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    utility = (root / "gui" / "src" / "utils" / "workActivityUtils.ts").read_text(encoding="utf-8")
    app = (root / "gui" / "src" / "App.tsx").read_text(encoding="utf-8")
    timeline = (root / "gui" / "src" / "components" / "WorkActivityTimeline.tsx").read_text(encoding="utf-8")
    bubble = (root / "gui" / "src" / "components" / "chat" / "MessageBubble.tsx").read_text(encoding="utf-8")
    interactive = (root / "tui" / "nexus-tui.tsx").read_text(encoding="utf-8")
    headless = (root / "tui" / "nexus-tui-headless.ts").read_text(encoding="utf-8")

    assert "export const adaptCanonicalWorkEvent" in utility
    assert "input.event_id || input.id" in utility
    assert "input.payload && typeof input.payload === 'object'" in utility
    assert "incomingSequence >= existingSequence" in utility
    for source in (interactive, headless):
        assert "adaptCanonicalEvent" in source
        assert "input.event_id || input.id" in source
        assert "input.related_command" in source

    assert "Retry failed turn" in bubble
    assert "server exposes no approve/deny endpoint" in timeline
