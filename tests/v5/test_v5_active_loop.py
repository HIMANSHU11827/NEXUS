"""Test the V5ActiveLoop mixin (Hive-powered plan gating + self-repair + ledger).

Uses a mock Hive engine so no real LLM is needed.
"""

import json
import os
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrators.v5.active_loop import V5ActiveLoop


@pytest.fixture(autouse=True)
def _restore_active_mode_env(monkeypatch):
    """Neutralize _ActiveLoopHost's direct os.environ writes.

    The host sets NEXUS_HIVE / NEXUS_V5_ACTIVE_MODE at construction without
    cleanup, so the last instantiation's values otherwise leak into every
    later test in the process (this hung unrelated run() tests behind a real
    120s hive spawn wait). monkeypatch.undo() restores the pre-test values no
    matter what the host wrote during the test.
    """
    monkeypatch.setenv("NEXUS_HIVE", "0")
    monkeypatch.setenv("NEXUS_V5_ACTIVE_MODE", "false")
    yield


class _MockSubAgent:
    def __init__(self, persona, result, status="success"):
        self.persona = persona
        self.result = result
        self.status = status
        self.agent_id = f"mock_{persona}"
        self.task = ""


class _MockHiveEngine:
    def __init__(self, verdict_map=None):
        self._verdict_map = verdict_map or {}
        self._llm_call = None

    def set_llm_call(self, call):
        self._llm_call = call

    def set_tool_registry(self, reg):
        pass

    async def spawn_hive(self, tasks, parent_run_id="", tool_registry=None, max_steps=None):
        agents = []
        for task_text, persona in tasks:
            result = self._verdict_map.get(persona, "")
            agents.append(_MockSubAgent(persona, result))
        return "mock_hive", agents


class _MetadataEntry:
    def __init__(self, read_only):
        self._read_only = read_only

    def is_read_only(self, params=None):
        return self._read_only


class _MetadataRegistry:
    def __init__(self, entries):
        self._entries = entries

    def get(self, name):
        return self._entries.get(name)

    def list_tools(self, include_unavailable=True):
        return list(self._entries)


class _ActiveLoopHost(V5ActiveLoop):
    """Minimal host for unit-testing the mixin in isolation."""

    def __init__(self, hive_on=False, active_on=True, hive_engine=None):
        os.environ["NEXUS_HIVE"] = "1" if hive_on else "0"
        os.environ["NEXUS_V5_ACTIVE_MODE"] = "true" if active_on else "false"
        self._mock_hive_engine = hive_engine
        self._current_turn_id = "test_turn"
        import logging
        self.logger = logging.getLogger("test_active_loop")

    def _hive_engine(self):
        return self._mock_hive_engine

    def _hive_llm_call(self):
        async def _llm(messages):
            return "mock"
        return _llm

    async def _emit_runtime_event(self, *args, **kwargs):
        pass

    def _detect_stall(self, history, threshold=3):
        """Stubbed _detect_stall from V5ParallelExecutor."""
        return len([
            h for h in history if not h.get("success")
        ]) >= threshold


def test_active_mode_disabled_when_hive_off():
    host = _ActiveLoopHost(hive_on=False)
    assert host._active_mode_enabled() is False


def test_active_mode_enabled_when_hive_on():
    host = _ActiveLoopHost(hive_on=True, active_on=True)
    assert host._active_mode_enabled() is True


def test_active_mode_disabled_via_env():
    host = _ActiveLoopHost(hive_on=True, active_on=False)
    assert host._active_mode_enabled() is False


def test_max_repair_attempts_default():
    host = _ActiveLoopHost()
    assert host._max_repair_attempts() == 2


def test_init_task_ledger():
    host = _ActiveLoopHost()
    host._init_task_ledger()
    assert host._task_ledger == []
    assert host._repair_count == 0


def test_ledger_record():
    host = _ActiveLoopHost()
    host._init_task_ledger()
    host._ledger_record({"description": "read file", "tool": "reading"}, True)
    host._ledger_record({"description": "write file", "tool": "modifying"}, False)
    history = host._ledger_history()
    assert len(history) == 2
    assert history[0]["success"] is True
    assert history[1]["success"] is False


def test_ledger_history_empty_when_not_init():
    host = _ActiveLoopHost()
    assert host._ledger_history() == []


def test_classify_plan_risk_safe():
    host = _ActiveLoopHost()
    risk, concerns = host._classify_plan_risk([
        {"description": "read", "tool": "reading"},
        {"description": "search", "tool": "code_search"},
    ])
    assert risk == 0
    assert concerns == []


def test_classify_plan_risk_high():
    host = _ActiveLoopHost()
    risk, concerns = host._classify_plan_risk([
        {"description": "read", "tool": "reading"},
        {"description": "run cmd", "tool": "bash"},
    ])
    assert risk == 1
    assert len(concerns) == 1


def test_classify_plan_risk_covers_mutating_aliases_and_actions():
    host = _ActiveLoopHost()
    risk, concerns = host._classify_plan_risk([
        {"description": "create file", "tool": "creating"},
        {"description": "delete memory", "tool": "memory", "params": {"action": "delete"}},
    ])
    assert risk == 2
    assert len(concerns) == 2


def test_classify_plan_risk_uses_tool_metadata_for_new_mutating_tools():
    host = _ActiveLoopHost()
    host.tool_registry = _MetadataRegistry({
        "workspace_writer": _MetadataEntry(False),
    })
    risk, concerns = host._classify_plan_risk([
        {"description": "write workspace", "tool": "workspace_writer", "params": {}},
    ])
    assert risk == 1
    assert "workspace_writer" in concerns[0]


# ── Plan gating tests (items #21–#25) ───────────────────────────────────

@pytest.mark.asyncio
async def test_gate_plan_deterministic_blocks_high_risk():
    """With Hive off, a high-risk plan is blocked by deterministic gate."""
    host = _ActiveLoopHost(hive_on=False)
    steps = [{"description": "rm -rf", "tool": "bash", "params": {}}]
    gated = await host._gate_plan(steps, "delete everything")
    assert gated == []


@pytest.mark.asyncio
async def test_gate_plan_deterministic_allows_safe():
    """With Hive off, a safe plan passes deterministic gate."""
    host = _ActiveLoopHost(hive_on=False)
    steps = [{"description": "read file", "tool": "reading", "params": {}}]
    gated = await host._gate_plan(steps, "read the file")
    assert gated == steps


@pytest.mark.asyncio
async def test_gate_plan_hive_blocks():
    """Hive REVIEWER can block a plan."""
    host = _ActiveLoopHost(
        hive_on=True,
        hive_engine=_MockHiveEngine(verdict_map={
            "REVIEWER": "VERDICT: BLOCK\nCONCERNS: uses destructive command",
            "PLANNER": "VERDICT: APPROVE\nSUGGESTION: looks fine",
        }),
    )
    steps = [{"description": "test", "tool": "reading", "params": {}}]
    gated = await host._gate_plan(steps, "test task")
    assert gated == []


@pytest.mark.asyncio
async def test_gate_plan_hive_approves():
    """Hive REVIEWER + PLANNER both approve → plan passes."""
    host = _ActiveLoopHost(
        hive_on=True,
        hive_engine=_MockHiveEngine(verdict_map={
            "REVIEWER": "VERDICT: APPROVE\nCONCERNS: none",
            "PLANNER": "VERDICT: APPROVE\nSUGGESTION: good plan",
        }),
    )
    steps = [{"description": "read", "tool": "reading", "params": {}}]
    gated = await host._gate_plan(steps, "read task")
    assert gated == steps


@pytest.mark.asyncio
async def test_gate_plan_ignores_block_substring_without_block_verdict():
    """Narrative text containing 'blocking' must not veto a plan."""
    host = _ActiveLoopHost(
        hive_on=True,
        hive_engine=_MockHiveEngine(verdict_map={
            "REVIEWER": "VERDICT: APPROVE\nCONCERNS: no blocking issues",
            "PLANNER": "VERDICT: APPROVE\nSUGGESTION: good plan",
        }),
    )
    steps = [{"description": "read", "tool": "reading", "params": {}}]

    assert await host._gate_plan(steps, "read task") == steps


@pytest.mark.asyncio
async def test_gate_plan_fails_closed_for_high_risk_missing_reviewer_verdict():
    """A high-risk plan is blocked when the reviewer protocol is missing."""
    host = _ActiveLoopHost(
        hive_on=True,
        hive_engine=_MockHiveEngine(verdict_map={
            "REVIEWER": "Unable to assess this plan",
            "PLANNER": "VERDICT: APPROVE\nSUGGESTION: fine",
        }),
    )
    steps = [{"description": "delete data", "tool": "bash", "params": {}}]

    assert await host._gate_plan(steps, "delete data") == []


@pytest.mark.asyncio
async def test_gate_plan_fails_closed_for_high_risk_review_exception():
    """Unexpected review errors must not open a high-risk execution path."""
    host = _ActiveLoopHost(hive_on=True)

    async def fail_review(_steps, _user_input):
        raise RuntimeError("review service unavailable")

    host._hive_review_plan = fail_review
    steps = [{"description": "run command", "tool": "bash", "params": {}}]

    assert await host._gate_plan(steps, "run command") == []


@pytest.mark.asyncio
async def test_gate_plan_empty_steps_passthrough():
    """Empty steps are passed through without gating."""
    host = _ActiveLoopHost(hive_on=True)
    gated = await host._gate_plan([], "empty")
    assert gated == []


# ── Self-repair tests (items #26–#28) ───────────────────────────────────

@pytest.mark.asyncio
async def test_self_repair_returns_repair_plan():
    """Hive ENGINEER returns a repair plan when a turn fails."""
    repair_plan = [{"description": "retry with different params", "tool": "reading"}]
    host = _ActiveLoopHost(
        hive_on=True,
        hive_engine=_MockHiveEngine(verdict_map={
            "ENGINEER": f"REPAIR_PLAN: {json.dumps(repair_plan)}",
            "TESTER": "DIAGNOSIS: real bug\nIS_TRANSIENT: no",
        }),
    )
    host._init_task_ledger()
    result = {"success": False, "actions": [{"success": False, "error": "boom"}]}
    P = type("P", (), {"original_input": "fix it"})
    repair = await host._hive_self_repair(result, P())
    assert repair == [{**repair_plan[0], "params": {}}]


@pytest.mark.asyncio
async def test_self_repair_budget_exhausted():
    """Repair returns None after max attempts."""
    host = _ActiveLoopHost(hive_on=True)
    host._init_task_ledger()
    host._repair_count = host._max_repair_attempts()
    P = type("P", (), {"original_input": "x"})
    repair = await host._hive_self_repair({"success": False}, P())
    assert repair is None


@pytest.mark.asyncio
async def test_self_repair_disabled_when_hive_off():
    """Self-repair is a no-op when Hive is off."""
    host = _ActiveLoopHost(hive_on=False)
    P = type("P", (), {"original_input": "x"})
    repair = await host._hive_self_repair({"success": False}, P())
    assert repair is None


@pytest.mark.asyncio
async def test_hive_recovery_plan_normalizes_and_drops_unknown_steps():
    """Recovery JSON must be normalized before reaching the execution path."""
    host = _ActiveLoopHost(hive_on=True)
    host.tool_registry = _MetadataRegistry({"reading": _MetadataEntry(True)})
    reviewed = await host._review_hive_recovery_plan([
        None,
        {"tool": "reading", "params": "not-an-object"},
        {"description": "unknown", "tool": "not_registered"},
        {"description": "read safely", "tool": "reading", "params": {"path": "a"}},
    ], "read safely")
    assert reviewed == [{
        "description": "read safely",
        "tool": "reading",
        "params": {"path": "a"},
    }]


@pytest.mark.asyncio
async def test_hive_recovery_plan_is_blocked_when_safety_gate_rejects():
    host = _ActiveLoopHost(hive_on=True)

    async def reject(_steps, _user_input):
        return []

    host._gate_plan = reject
    reviewed = await host._review_hive_recovery_plan([
        {"description": "delete data", "tool": "deleting"},
    ], "delete data")
    assert reviewed == []


# ── Stall-driven replan tests (items #30–#31) ───────────────────────────

@pytest.mark.asyncio
async def test_replan_on_stall_no_stall():
    """No replan when the ledger has no stall (below threshold of 3)."""
    host = _ActiveLoopHost(hive_on=True)
    host._init_task_ledger()
    host._ledger_record({"description": "step1", "tool": "reading"}, False)
    P = type("P", (), {"original_input": "task"})
    replan = await host._hive_replan_on_stall(P())
    assert replan is None


@pytest.mark.asyncio
async def test_replan_on_stall_triggered():
    """Stall (4+ failures) triggers Hive replan."""
    new_plan = [{"description": "different approach", "tool": "code_search"}]
    host = _ActiveLoopHost(
        hive_on=True,
        hive_engine=_MockHiveEngine(verdict_map={
            "PLANNER": f"NEW_PLAN: {json.dumps(new_plan)}",
        }),
    )
    host._init_task_ledger()
    for i in range(4):
        host._ledger_record({"description": "same step", "tool": "reading"}, False)
    P = type("P", (), {"original_input": "task"})
    replan = await host._hive_replan_on_stall(P())
    assert replan == [{**new_plan[0], "params": {}}]

