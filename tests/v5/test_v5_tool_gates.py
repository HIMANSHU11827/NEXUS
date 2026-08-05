"""Tests for V5 tool gates: risk classes, confirmations, lint, windowed ACI, code actions."""

import asyncio
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrators.v5.core import NexusLoopV5
from orchestrators.v5.tools import _TextToolCall


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


def test_confirmation_gate_fails_closed_without_broker(loop):
    loop.runtime.permission_mode_value = "approve"
    loop._open_approval = lambda *args, **kwargs: None
    approved = asyncio.run(loop._confirmation_gate(_call("deleting", {"path": "x"}, "c4")))
    assert approved is False


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


def test_execute_code_action_env_enabled_run(loop, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_CODE_ACTION", "1")
    loop._code_action_enabled = False
    loop.runtime.sandbox = None
    result = asyncio.run(
        loop._execute_code_action("print('hello-from-code-action')", workdir=str(tmp_path))
    )
    assert "hello-from-code-action" in result
