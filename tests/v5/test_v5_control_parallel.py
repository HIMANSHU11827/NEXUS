"""Tests for V5 run control (phase hooks, budget, workspace rollback) and
parallel executor (superstep fan-out, stall detection) mixins."""

import json
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from nexus.main_agent.core import NexusLoopV5


def _git_available() -> bool:
    try:
        proc = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=15
        )
        return proc.returncode == 0
    except Exception:
        return False


HAVE_GIT = _git_available()


# ─────────────────────────────────────────────────────────────────────────────
# PHASE HOOKS (roadmap #9)
# ─────────────────────────────────────────────────────────────────────────────

async def test_phase_hook_block_and_allow(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    calls = []

    async def async_hook(position=None, phase=None):
        calls.append((position, phase))
        return {"decision": "block", "reason": "policy says no"}

    def sync_hook(position=None, phase=None):
        calls.append((position, phase))
        return {"decision": "allow", "reason": "fine"}

    assert loop._register_phase_hook("pre_phase", "acting", async_hook) is True
    assert loop._register_phase_hook("pre_phase", "acting", sync_hook) is True
    assert loop._register_phase_hook("pre_phase", "acting", async_hook) is True
    assert len(loop._phase_hooks[("pre_phase", "acting")]) == 2

    reason = await loop._fire_phase_hooks("pre_phase", "acting")
    assert reason == "policy says no"
    assert ("pre_phase", "acting") in calls

    assert await loop._fire_phase_hooks("post_phase", "acting") == ""


async def test_phase_hook_allow_none_and_string_contracts(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))

    def none_hook(position=None, phase=None):
        return None

    def allow_hook(position=None, phase=None):
        return "allow"

    def json_hook(position=None, phase=None):
        return json.dumps({"decision": "block", "reason": "json-policy"})

    def plain_block_hook(position=None, phase=None):
        return "block"

    def no_arg_hook():
        return {"decision": "block", "reason": "no-arg-blocked"}

    def phase_only_hook(phase):
        return {"decision": "block", "reason": f"blocked-{phase}"}

    loop._register_phase_hook("pre_phase", "perceiving", none_hook)
    loop._register_phase_hook("pre_phase", "perceiving", allow_hook)
    assert await loop._fire_phase_hooks("pre_phase", "perceiving") == ""

    loop._register_phase_hook("pre_phase", "observing", json_hook)
    assert await loop._fire_phase_hooks("pre_phase", "observing") == "json-policy"

    loop._register_phase_hook("pre_phase", "reflecting", plain_block_hook)
    assert await loop._fire_phase_hooks("pre_phase", "reflecting") == "blocked by phase hook"

    loop._register_phase_hook("pre_phase", "evolving", no_arg_hook)
    assert await loop._fire_phase_hooks("pre_phase", "evolving") == "no-arg-blocked"

    loop._register_phase_hook("pre_phase", "outputting", phase_only_hook)
    assert await loop._fire_phase_hooks("pre_phase", "outputting") == "blocked-outputting"

    assert loop._register_phase_hook("bogus_position", "acting", allow_hook) is False
    assert loop._register_phase_hook("pre_phase", "acting", None) is False


async def test_phase_hook_failure_does_not_block_others(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))

    def bad_hook(position=None, phase=None):
        raise RuntimeError("hook exploded")

    def blocking_hook(position=None, phase=None):
        return {"decision": "block", "reason": "after-bad"}

    loop._register_phase_hook("pre_phase", "planning", bad_hook)
    loop._register_phase_hook("pre_phase", "planning", blocking_hook)
    assert await loop._fire_phase_hooks("pre_phase", "planning") == "after-bad"
    assert await loop._fire_phase_hooks("post_phase", "planning") == ""


# ─────────────────────────────────────────────────────────────────────────────
# PER-RUN BUDGET + COST TELEMETRY (roadmap #16)
# ─────────────────────────────────────────────────────────────────────────────

async def test_budget_tick_exceed_and_report(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_MAX_TURNS", raising=False)
    monkeypatch.delenv("NEXUS_MAX_BUDGET_USD", raising=False)
    loop = NexusLoopV5(root_dir=str(tmp_path))
    loop._budget = {
        "max_turns": 2,
        "max_budget_usd": 5.0,
        "turns": 0,
        "cost": 0.0,
        "tokens": 0,
        "started": time.time(),
    }

    tick = loop._budget_tick(tokens=100, cost=1.0)
    assert tick["turns"] == 1
    assert tick["tokens"] == 100
    assert tick["cost"] == 1.0
    assert loop._budget_exceeded() is False

    loop._budget_tick(tokens=200, cost=3.5)
    assert loop._budget_exceeded() is True  # turns=2 >= max_turns=2

    loop._budget_tick()
    assert loop._budget_exceeded() is True  # still exceeded (turns=3)

    report = loop._budget_report()
    assert report["turns"] == 3
    assert report["tokens"] == 300
    assert report["cost_usd"] == 4.5
    assert report["max_turns"] == 2
    assert report["max_budget_usd"] == 5.0
    assert report["duration_s"] >= 0


async def test_budget_cost_ceiling_and_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_MAX_TURNS", raising=False)
    monkeypatch.delenv("NEXUS_MAX_BUDGET_USD", raising=False)
    loop = NexusLoopV5(root_dir=str(tmp_path))
    loop._budget = {
        "max_turns": 50,
        "max_budget_usd": 2.0,
        "turns": 0,
        "cost": 0.0,
        "tokens": 0,
        "started": time.time(),
    }
    loop._budget_tick(cost=2.0)
    assert loop._budget_exceeded() is True

    fresh = NexusLoopV5(root_dir=str(tmp_path))
    assert fresh._budget_tick()["turns"] == 1
    # Default is unlimited turns (0): a run ends when the model stops
    # requesting tools, not at an arbitrary counter (Claude Code semantics).
    assert fresh._budget["max_turns"] == 0
    assert fresh._budget["max_budget_usd"] == 0.0
    assert fresh._budget_exceeded() is False

    monkeypatch.setenv("NEXUS_MAX_TURNS", "7")
    monkeypatch.setenv("NEXUS_MAX_BUDGET_USD", "3.5")
    env_loop = NexusLoopV5(root_dir=str(tmp_path))
    env_loop._init_budget()
    assert env_loop._budget["max_turns"] == 7
    assert env_loop._budget["max_budget_usd"] == 3.5


def test_budget_can_be_reset_at_a_new_run_boundary(tmp_path):
    loop = NexusLoopV5(str(tmp_path))
    loop._init_budget()
    loop._budget_tick(tokens=100)
    loop._budget_tick(tokens=200)
    assert loop._budget["turns"] == 2

    loop._init_budget(reset=True)

    assert loop._budget["turns"] == 0
    assert loop._budget["tokens"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# WORKSPACE ROLLBACK / GIT SNAPSHOT (roadmap #10)
# ─────────────────────────────────────────────────────────────────────────────

async def test_snapshot_workspace_without_git_repo(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    (tmp_path / "plain.txt").write_text("x", encoding="utf-8")
    assert loop._snapshot_workspace(turn_id="t1") == ""


async def test_undo_last_without_snapshots(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    assert loop._undo_last() is False
    assert loop._rollback_snapshot("missing_turn") is False


@pytest.mark.skipif(not HAVE_GIT, reason="git executable not available")
async def test_snapshot_rollback_with_git(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@nexus.local"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Nexus Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    notes = tmp_path / "notes.txt"
    notes.write_text("original content", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)

    notes.write_text("modified content", encoding="utf-8")

    loop = NexusLoopV5(root_dir=str(tmp_path))
    snap = loop._snapshot_workspace(turn_id="t1")
    assert snap and os.path.isdir(snap)
    captured = tmp_path / ".nexus" / "v5" / "snapshots" / "t1" / "notes.txt"
    assert captured.is_file()
    assert captured.read_text(encoding="utf-8") == "original content"

    notes.write_text("modified again", encoding="utf-8")
    assert loop._rollback_snapshot("t1") is True
    assert notes.read_text(encoding="utf-8") == "original content"

    assert loop._undo_last() is True
    assert notes.read_text(encoding="utf-8") == "original content"


# ─────────────────────────────────────────────────────────────────────────────
# MAP-REDUCE SEND-STYLE SUPERSTEP (roadmap #12)
# ─────────────────────────────────────────────────────────────────────────────

class _FakeExecutor:
    """Records duck call objects; fails calls whose params request failure."""

    def __init__(self):
        self.calls = []

    async def __call__(self, call):
        self.calls.append(call)
        if call.params.get("fail"):
            raise RuntimeError("read failed")
        return f"ok:{call.name}:{call.call_id}"


async def test_run_superstep_blocks_writers_on_failed_read(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    executor = _FakeExecutor()
    steps = [
        {"description": "read a", "tool": "reading", "params": {"path": "a"}, "read_only": True},
        {"description": "read b", "tool": "reading", "params": {"path": "b", "fail": True}, "read_only": True},
        {"description": "write c", "tool": "writing", "params": {"path": "c"}},
    ]
    result = await loop._run_superstep(steps, executor=executor)

    assert result["applied"] is False
    assert result["blocked"] == ["step 2: writer skipped"]
    assert len(result["results"]) == 2
    assert result["results"][0]["index"] == 0
    assert result["results"][0]["success"] is True
    assert result["results"][1]["index"] == 1
    assert result["results"][1]["success"] is False
    assert "read failed" in result["results"][1]["error"]
    assert [call.name for call in executor.calls] == ["reading", "reading"]


async def test_run_superstep_all_reads_success(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    executor = _FakeExecutor()
    steps = [
        {"description": "read x", "tool": "reading", "params": {"path": "x"}},
        {"description": "read y", "tool": "code_search", "params": {"q": "y"}},
        {"description": "think", "tool": ""},
    ]
    result = await loop._run_superstep(steps, executor=executor)

    assert result["applied"] is True
    assert result["blocked"] == []
    assert len(result["results"]) == 3
    assert all(entry["success"] for entry in result["results"])
    assert [call.name for call in executor.calls] == ["reading", "code_search"]
    assert result["results"][2]["output"] == "Reasoning recorded; no external action executed: think"
    assert result["results"][2]["verified"] is False


async def test_run_superstep_apply_if_all_false(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    executor = _FakeExecutor()
    steps = [
        {"description": "read a", "tool": "reading", "params": {"path": "a", "fail": True}},
        {"description": "write c", "tool": "writing", "params": {"path": "c"}},
    ]
    result = await loop._run_superstep(steps, executor=executor, apply_if_all=False)

    assert result["applied"] is True
    assert result["blocked"] == []
    assert len(result["results"]) == 2


async def test_run_superstep_preserves_structured_executor_failure(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))

    async def executor(call):
        return {"success": False, "output": "", "error": "compiler failed"}

    result = await loop._run_superstep(
        [{"description": "compile", "tool": "terminal"}], executor=executor
    )

    assert result["applied"] is True
    assert result["results"][0]["success"] is False
    assert result["results"][0]["error"] == "compiler failed"


async def test_run_superstep_reports_self_cancelled_branch_as_failure(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))

    async def executor(call):
        if call.name == "reading":
            raise asyncio.CancelledError("child probe stopped")
        return "healthy branch"

    result = await loop._run_superstep(
        [
            {"description": "probe", "tool": "reading", "read_only": True},
            {"description": "other probe", "tool": "code_search", "read_only": True},
        ],
        executor=executor,
    )

    assert result["results"][0]["success"] is False
    assert result["results"][0]["error"] == "tool cancelled"
    assert result["results"][1]["success"] is True


async def test_run_superstep_guards(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))
    executor = _FakeExecutor()
    result = await loop._run_superstep("not a list", executor=executor)
    assert result["applied"] is True
    assert result["results"] == []
    assert result["blocked"] == []


async def test_parallel_writer_self_cancellation_is_a_failed_action(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))

    async def tool(_call):
        raise asyncio.CancelledError("writer stopped")

    loop._run_tool = tool
    actions = await loop._run_steps_parallel([
        {"description": "run command", "tool": "terminal", "params": {"cmd": "stop"}},
    ])

    assert len(actions) == 1
    assert actions[0]["success"] is False
    assert actions[0]["error"] == "tool cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# STALL DETECTION + REPLAN HINT (roadmap #13)
# ─────────────────────────────────────────────────────────────────────────────

async def test_detect_stall_and_replan_hint(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path))

    three_failures = [
        {"success": False, "description": f"attempt {i}"} for i in range(3)
    ]
    assert loop._detect_stall(three_failures) is True
    assert loop._detect_stall(three_failures, threshold=4) is False

    two_failures = [{"success": False}, {"success": False}]
    assert loop._detect_stall(two_failures) is False

    ok_then_two_failures = [{"success": True}, {"success": False}, {"success": False}]
    assert loop._detect_stall(ok_then_two_failures) is False

    repeated = [{"success": True, "description": "same step"}] * 3
    assert loop._detect_stall(repeated) is True

    assert loop._detect_stall([]) is False
    assert loop._detect_stall(None) is False

    hint = loop._replan_hint(three_failures)
    assert "Repeated failure detected (3 consecutive attempts)" in hint
    assert "Change approach" in hint
    assert loop._replan_hint(two_failures) == ""
    assert loop._replan_hint([]) == ""
    assert loop._replan_hint(None) == ""
