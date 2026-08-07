"""Tests for the V5Hive sub-agent supervision redesign.

Covers (all against monkeypatched engine spawn/consolidate/cancel, asyncio):
1. spawn enforces a real timeout and cancels the sub-agent on expiry;
2. sub-agent states are persisted to ``~/.nexus/hive/subagents.jsonl`` and
   reloaded on a fresh host (restart);
3. untrusted / invalid ``[HIVE_RESULT]`` envelopes are NOT injected and the
   turn is marked failed with a ``subagent_untrusted`` note;
4. parent cancellation propagates to all active sub-agents before surfacing.
"""

import asyncio
import json
import logging
import os
import time
from types import SimpleNamespace

import pytest

from nexus.run_control import RunControlRegistry
from orchestrators.v5.hive import V5Hive, _HIVE_RESULT_MARKER

logger = logging.getLogger("test_redesign_hive")


class FakeAgent:
    def __init__(self, agent_id, persona="WORKER"):
        self.agent_id = agent_id
        self.persona = persona
        self.status = "pending"
        self.started_at = time.time()


class FakeEngine:
    """Minimal engine fake: records cancels, controllable consolidate."""

    def __init__(self):
        self.cancelled = []
        self.spawned = []
        self.consolidated = []
        self.consolidate_timeouts = []
        self._consolidate_delay = 0.0
        self._consolidate_result = ""
        self._decompose = [("research X", "RESEARCHER"), ("build Y", "ENGINEER")]

    def set_tool_registry(self, registry):
        pass

    def set_llm_call(self, llm_call):
        pass

    async def decompose_task(self, task, llm_call=None, **kwargs):
        return list(self._decompose)

    async def spawn_hive(self, tasks, **kwargs):
        agents = [
            FakeAgent(f"agent_{i}", persona) for i, (_, persona) in enumerate(tasks)
        ]
        self.spawned.append(tasks)
        return "hive_under_test", agents

    async def consolidate_hive(self, hive_id, timeout=None, llm_call=None, **kwargs):
        self.consolidated.append(hive_id)
        self.consolidate_timeouts.append(timeout)
        if self._consolidate_delay:
            await asyncio.sleep(self._consolidate_delay)
        return self._consolidate_result

    async def cancel_hive(self, hive_id):
        self.cancelled.append(hive_id)


def _make_host(tmp_path, engine=None):
    """Build a V5Hive mixin host wired to a temp state file + fake engine."""
    host = V5Hive()
    host.logger = logger
    host._v5_hive_engine = engine or FakeEngine()
    host._v5_hive_state_file = str(tmp_path / "subagents.jsonl")
    host._current_turn_id = "turn_1234"
    return host


def _perceived(context_summary="base", original_input="do the research"):
    return SimpleNamespace(
        context_summary=context_summary,
        original_input=original_input,
        metadata={},
    )


# ─────────────────────────────────────────────────────────────────────
# 1. Timeout enforcement + cancellation on expiry
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spawn_timeout_cancels_and_marks_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    engine._consolidate_delay = 10.0  # never finishes on time
    host = _make_host(tmp_path, engine)

    result = await host._maybe_spawn_hive("task", timeout_seconds=0.1)

    assert result is None
    # The sub-agent hive was cancelled through the engine.
    assert "hive_under_test" in engine.cancelled
    # The turn was marked failed with reason "timeout".
    assert host._v5_hive_turn_failure["status"] == "failed"
    assert host._v5_hive_turn_failure["reason"] == "timeout"
    # Persisted states moved to "timeout".
    states = host._hive_load_subagent_states()
    assert states and all(s["status"] == "timeout" for s in states.values())


@pytest.mark.asyncio
async def test_spawn_timeout_uses_default_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    monkeypatch.setenv("NEXUS_HIVE_TIMEOUT", "0.1")
    engine = FakeEngine()
    engine._consolidate_delay = 10.0
    host = _make_host(tmp_path, engine)

    result = await host._maybe_spawn_hive("task")  # no explicit timeout

    assert result is None
    assert "hive_under_test" in engine.cancelled
    assert host._v5_hive_turn_failure["reason"] == "timeout"


@pytest.mark.asyncio
async def test_hive_timeout_is_capped_by_parent_run_budget(monkeypatch, tmp_path):
    """Nested hive work must inherit the active run's remaining deadline."""
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    engine._consolidate_result = "bounded result"
    host = _make_host(tmp_path, engine)
    controls = RunControlRegistry()
    controls.register("turn_1234", deadline_at=time.monotonic() + 0.2)
    host._run_controls = controls

    result = await host._maybe_spawn_hive("task", timeout_seconds=30.0)

    assert result == "bounded result"
    # The engine sees the same bounded value, rather than an independent 30s
    # timeout that could outlive its parent run.
    assert engine.consolidated == ["hive_under_test"]
    assert 0 < engine.consolidate_timeouts[0] < 1.0



@pytest.mark.asyncio
async def test_parent_cancel_propagates_before_surfacing(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    engine._consolidate_delay = 10.0
    host = _make_host(tmp_path, engine)

    task = asyncio.create_task(host._maybe_spawn_hive("task", timeout_seconds=30.0))
    await asyncio.sleep(0.05)  # let spawn + remember complete
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Sub-agents were cancelled before the parent cancellation surfaced.
    assert "hive_under_test" in engine.cancelled
    states = host._hive_load_subagent_states()
    assert states and all(s["status"] == "cancelled" for s in states.values())


# ─────────────────────────────────────────────────────────────────────
# 2. State persistence + reload (restart)
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_persisted_and_reloaded(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    engine._consolidate_result = "findings done"
    host = _make_host(tmp_path, engine)

    result = await host._maybe_spawn_hive("task")
    assert result == "findings done"

    # File exists and is valid JSONL with role/status/parent/started_at.
    path = host._hive_state_file()
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(ln) for ln in f if ln.strip()]
    assert lines and all(r["id"] for r in lines)
    assert all(r["role"] in ("RESEARCHER", "ENGINEER") for r in lines)
    # Append-only JSONL: the last line per id is the current status.
    final_status = {}
    for r in lines:
        final_status[r["id"]] = r["status"]
    assert final_status and all(s == "succeeded" for s in final_status.values())
    assert len(final_status) == 2
    assert all(r["parent"] == "hive_under_test" for r in lines)
    assert all("started_at" in r for r in lines)

    # A fresh host (restart) reloads the prior sub-agents.
    host2 = V5Hive()
    host2.logger = logger
    host2._v5_hive_state_file = path
    reloaded = host2._hive_load_subagent_states()
    ids = {r["id"] for r in lines}
    assert set(reloaded.keys()) == ids
    assert len(ids) == 2
    assert all(s["status"] == "succeeded" for s in reloaded.values())


def test_module_load_persisted_states(tmp_path):
    """module-level loader surfaces prior sub-agents after a "restart"."""
    path = tmp_path / "subagents.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "a1", "status": "running", "role": "WORKER"}) + "\n")
    from orchestrators.v5.hive import load_persisted_subagent_states
    states = load_persisted_subagent_states(str(path))
    assert states["a1"]["status"] == "running"


# ─────────────────────────────────────────────────────────────────────
# 3. Untrusted / invalid [HIVE_RESULT] not injected
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_empty_envelope_not_injected(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    engine._consolidate_result = f"{_HIVE_RESULT_MARKER}:\n   "  # empty payload
    host = _make_host(tmp_path, engine)

    perceived = _perceived()
    await host._inject_hive_context(perceived)

    # Nothing injected into the main context.
    assert "HIVE_RESULT" not in perceived.context_summary
    assert perceived.context_summary == "base"
    # Turn marked failed with a subagent_untrusted note.
    assert host._v5_hive_turn_failure["status"] == "failed"
    assert host._v5_hive_turn_failure["subagent_untrusted"] is True
    assert host._v5_hive_turn_failure["reason"]


@pytest.mark.asyncio
async def test_empty_json_result_not_injected(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    envelope = f"{_HIVE_RESULT_MARKER}:\n" + json.dumps({"data": "", "result": ""})
    engine._consolidate_result = envelope
    host = _make_host(tmp_path, engine)

    perceived = _perceived()
    await host._inject_hive_context(perceived)

    assert "HIVE_RESULT" not in perceived.context_summary
    assert host._v5_hive_turn_failure["subagent_untrusted"] is True


@pytest.mark.asyncio
async def test_valid_envelope_injected(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    engine._consolidate_result = f"{_HIVE_RESULT_MARKER}:\nresearch completed"
    host = _make_host(tmp_path, engine)

    perceived = _perceived()
    await host._inject_hive_context(perceived)

    assert "HIVE_RESULT" in perceived.context_summary
    assert "research completed" in perceived.context_summary
    # No untrusted note when valid.
    assert not hasattr(host, "_v5_hive_turn_failure")


@pytest.mark.asyncio
async def test_valid_json_data_envelope_injected(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXUS_HIVE", "1")
    engine = FakeEngine()
    engine._consolidate_result = (
        f"{_HIVE_RESULT_MARKER}: " + json.dumps({"data": "parsed data payload"})
    )
    host = _make_host(tmp_path, engine)

    perceived = _perceived()
    await host._inject_hive_context(perceived)

    assert "parsed data payload" in perceived.context_summary
    assert "HIVE_RESULT" in perceived.context_summary


# ─────────────────────────────────────────────────────────────────────
# 4. Cancel propagation
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_propagates_to_active_subagents(tmp_path):
    engine = FakeEngine()
    host = _make_host(tmp_path, engine)

    # Simulate two active spawned sub-agents in one hive.
    host._hive_remember_spawn("hive_a", [FakeAgent("agent_1"), FakeAgent("agent_2")])

    n = await host._hive_cancel_active(reason="cancelled")

    assert n >= 1
    assert "hive_a" in engine.cancelled
    states = host._hive_load_subagent_states()
    assert states["agent_1"]["status"] == "cancelled"
    assert states["agent_2"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_propagates_to_reloaded_active_states(tmp_path):
    engine = FakeEngine()
    host = _make_host(tmp_path, engine)

    # Prior-process active state that still says "running".
    host._hive_update_subagent_state("agent_old", status="running", parent="hive_old")

    n = await host._hive_cancel_active(reason="cancelled")

    assert n >= 1
    assert "hive_old" in engine.cancelled
    assert host._hive_load_subagent_states()["agent_old"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_group_marks_timeout(tmp_path):
    engine = FakeEngine()
    host = _make_host(tmp_path, engine)
    host._hive_remember_spawn("hive_t", [FakeAgent("agent_t")])

    await host._hive_cancel_group("hive_t", reason="timeout")

    assert "hive_t" in engine.cancelled
    assert host._hive_load_subagent_states()["agent_t"]["status"] == "timeout"
