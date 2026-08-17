"""Tests for V5 tool gates: risk classes, confirmations, lint, windowed ACI, code actions."""

import asyncio
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from nexus.main_agent.core import NexusLoopV5
from nexus.main_agent.tools import _TextToolCall
from extensions.tools.built_in.nexus_tools.base_tool import ToolResult


class _FakeAssessment:
    def __init__(self, score: int):
        self.score = score
        self.blocked = score >= 80


class _FakeRiskScorer:
    def __init__(self, score: int):
        self._score = score

    def assess(self, command: str):
        return _FakeAssessment(self._score)


@pytest.fixture
def loop(tmp_path):
    instance = NexusLoopV5(root_dir=str(tmp_path), session_id="gate-test")
    instance.kernel = None
    instance.runtime.permissions = None
    instance.runtime.permission_mode_value = "bypass"
    return instance


def _call(name, params=None, call_id=""):
    return _TextToolCall(name, params or {}, call_id)


def test_risk_class_low_for_reading(loop):
    assert loop._risk_class_for_call(_call("reading", {"path": "notes.txt"})) == "low"


def test_risk_class_critical_for_deleting(loop):
    assert loop._risk_class_for_call(_call("deleting", {"path": "notes.txt"})) == "critical"


def test_risk_class_command_uses_scorer(loop):
    loop.runtime.risk_scorer = _FakeRiskScorer(2)
    assert loop._risk_class_for_call(_call("bash", {"command": "dir"})) == "low"
    loop.runtime.risk_scorer = _FakeRiskScorer(9)
    assert loop._risk_class_for_call(_call("shell", {"cmd": "danger"})) == "high"


def test_risk_class_high_for_sensitive_path(loop):
    assert loop._risk_class_for_call(_call("modifying", {"path": "config/.env"})) == "high"


def test_risk_class_medium_for_plain_modify(loop):
    assert loop._risk_class_for_call(_call("modifying", {"path": "src/app.py"})) == "medium"


def test_require_confirmation_false_outside_approve(loop):
    loop.runtime.permission_mode_value = "bypass"
    assert loop._require_confirmation(_call("deleting", {"path": "x"}, "c1")) is False


def test_require_confirmation_true_in_approve_critical(loop):
    loop.runtime.permission_mode_value = "approve"
    assert loop._require_confirmation(_call("deleting", {"path": "x"}, "c2")) is True


def test_require_confirmation_skips_approved_call(loop):
    loop.runtime.permission_mode_value = "approve"
    loop._approved_calls = {"c3": True}
    assert loop._require_confirmation(_call("deleting", {"path": "x"}, "c3")) is False


def test_require_confirmation_fails_closed_when_risk_classification_raises(loop):
    loop.runtime.permission_mode_value = "bypass"
    loop._risk_class_for_call = lambda call: (_ for _ in ()).throw(RuntimeError("risk unavailable"))
    assert loop._require_confirmation(_call("deleting", {"path": "x"}, "risk-error")) is True


def test_confirmation_gate_fails_closed_without_broker(loop):
    loop.runtime.permission_mode_value = "approve"
    loop._open_approval = lambda *args, **kwargs: None
    approved = asyncio.run(loop._confirmation_gate(_call("deleting", {"path": "x"}, "c4")))
    assert approved is False


def test_audit_approval_satisfies_followup_confirmation_gate(loop):
    """One registry approval must not open a second hidden broker request."""
    loop.runtime.permission_mode_value = "approve"

    class ManualApproval:
        granted = False
        reason = "manual approval required"
        decision = {"source": "mode:manual_approval"}

    loop.runtime.permissions = SimpleNamespace(
        check=lambda *args, **kwargs: ManualApproval()
    )
    loop._await_human_approval = lambda *args, **kwargs: asyncio.sleep(0, result=True)
    call = _call("deleting", {"path": "x"}, "one-approval")

    async def scenario():
        assert await loop._audit_tool_call(call) is True
        assert loop._approved_calls.get("one-approval") is True
        assert await loop._confirmation_gate(call) is True

    asyncio.run(scenario())


def test_lint_source_valid_py(loop, tmp_path):
    path = tmp_path / "ok.py"
    path.write_text("def f():\n    return 1\n", encoding="utf-8")
    ok, err = loop._lint_source(str(path))
    assert ok is True
    assert err == ""


def test_lint_source_syntax_error_py(loop, tmp_path):
    path = tmp_path / "bad.py"
    path.write_text("def f(:\n", encoding="utf-8")
    ok, err = loop._lint_source(str(path))
    assert ok is False
    assert err


def test_lint_source_missing_file_passes(loop):
    ok, err = loop._lint_source(str(Path(loop.root_dir) / "nope.py"))
    assert ok is True
    assert err == ""


def test_lint_source_fails_closed_when_validator_errors(loop, tmp_path, monkeypatch):
    path = tmp_path / "validator.py"
    path.write_text("value = 1\n", encoding="utf-8")

    def broken_run(*args, **kwargs):
        raise OSError("compiler unavailable")

    monkeypatch.setattr("nexus.main_agent.tools.subprocess.run", broken_run)
    ok, err = loop._lint_source(str(path))
    assert ok is False
    assert "compiler unavailable" in err


def test_run_tool_rejects_and_rolls_back_invalid_post_write_edit(loop, tmp_path):
    path = tmp_path / "edited.py"
    original = "value = 1\n"
    path.write_text(original, encoding="utf-8")

    class Registry:
        def get(self, name):
            return object()

        async def stream_execute(self, name, **params):
            path.write_text("def broken(:\n", encoding="utf-8")
            yield ToolResult(success=True, output="modified")

    loop.tool_registry = Registry()
    loop._audit_tool_call = lambda call: _approved()

    async def run():
        return await loop._run_tool(_call("modifying", {"path": str(path)}))

    async def _approved():
        return True

    with pytest.raises(RuntimeError, match="post-write lint"):
        asyncio.run(run())
    assert path.read_text(encoding="utf-8") == original


def test_edit_lint_and_snapshot_do_not_block_event_loop(loop, tmp_path, monkeypatch):
    path = tmp_path / "edited.py"
    path.write_text("value = 1\n", encoding="utf-8")
    original_run = __import__("nexus.main_agent.tools", fromlist=["subprocess"]).subprocess.run

    def slow_run(*args, **kwargs):
        import time

        time.sleep(0.08)
        return original_run(*args, **kwargs)

    monkeypatch.setattr("nexus.main_agent.tools.subprocess.run", slow_run)

    class Registry:
        def get(self, name):
            return object()

        async def stream_execute(self, name, **params):
            path.write_text("value = 2\n", encoding="utf-8")
            yield ToolResult(success=True, output="modified")

    loop.tool_registry = Registry()

    async def _approved():
        return True

    loop._audit_tool_call = lambda call: _approved()

    async def run_with_heartbeat():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            result = await loop._run_tool(_call("modifying", {"path": str(path)}))
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        return result, ticks

    result, ticks = asyncio.run(run_with_heartbeat())
    assert result == "modified"
    assert ticks >= 8


def test_read_windowed_slice_and_header(loop, tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("".join(f"line {i}\n" for i in range(1, 151)), encoding="utf-8")
    text = loop._read_windowed(str(path), window=100)
    lines = text.splitlines()
    assert lines[0] == "#1-100/#150"
    assert "line 1" in text
    assert "line 100" in text
    assert "line 101" not in text
    assert lines[-1] == "..."


def test_read_windowed_offset_no_hint(loop, tmp_path):
    path = tmp_path / "big2.txt"
    path.write_text("".join(f"line {i}\n" for i in range(1, 151)), encoding="utf-8")
    text = loop._read_windowed(str(path), window=50, offset=100)
    lines = text.splitlines()
    assert lines[0] == "#101-150/#150"
    assert "line 101" in text
    assert lines[-1] != "..."


def test_execute_code_action_disabled(loop, monkeypatch):
    monkeypatch.delenv("NEXUS_CODE_ACTION", raising=False)
    loop._code_action_enabled = False
    result = asyncio.run(loop._execute_code_action("print('hi')"))
    assert result == "Error: code-action mode disabled"


def test_execute_code_action_requires_sandbox(loop, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_CODE_ACTION", "1")
    loop._code_action_enabled = False
    loop.runtime.sandbox = None
    result = asyncio.run(
        loop._execute_code_action("print('hello-from-code-action')", workdir=str(tmp_path))
    )
    assert result == "Error: code-action requires an active sandbox"


def test_execute_code_action_sanitizes_turn_path_and_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_CODE_ACTION", "1")

    class Sandbox:
        last_exit_code = 0

        async def stream_execute(self, command, **_kwargs):
            assert "code_action_escape.py" in command
            yield "ok"

    loop = NexusLoopV5(str(tmp_path))
    loop.runtime.sandbox = Sandbox()
    loop._current_turn_id = "../../escape"

    result = asyncio.run(loop._execute_code_action("print('ok')"))

    assert result == "ok"
    expected = tmp_path / ".nexus_v5" / "tmp" / "code_action_escape.py"
    assert expected.read_text(encoding="utf-8") == "print('ok')"
    assert not (tmp_path.parent / "escape.py").exists()
