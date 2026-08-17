"""Hive integrity regression tests (new tests only).

Covers the five hive-integrity requirements:
  (a) stable agent ids across checkpoints/restores
  (b) task correlation: parent_run_id, task ids, handoff records
  (c) parallel blackboard integrity and agent-failure isolation
  (d) per-agent partial-failure visibility
  (e) verified consolidation (no fabricated content for failed agents)
"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from hive.engine import NexusHiveEngine, SubAgent
from hive.state import HiveStateConflict


# ─────────────────────────── (a) stable agent ids ───────────────────────────


def test_agent_id_stable_across_checkpoint_and_restore(tmp_path):
    original = SubAgent(
        "agent-stable", "task", "WORKER", "hive-1", root=str(tmp_path)
    )
    original.steps_used = 3
    original.checkpoint()

    restored = SubAgent(
        "agent-stable", "task", "WORKER", "hive-1", root=str(tmp_path)
    )
    assert restored.restore_checkpoint() is True
    # The id is preserved, never regenerated, and the checkpoint is keyed by it.
    assert restored.agent_id == "agent-stable"
    assert restored.steps_used == 3
    assert restored.checkpoint_path.endswith("agent-stable.json")


@pytest.mark.asyncio
async def test_spawn_hive_preserves_manifest_agent_ids(tmp_path):
    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(lambda _messages: "ok")
    hive_id, agents = await engine.spawn_hive(
        [("t1", "WORKER"), ("t2", "WORKER")],
        agent_ids=["resume-a", "resume-b"],
    )
    await engine._hive_tasks[hive_id]

    assert [agent.agent_id for agent in agents] == ["resume-a", "resume-b"]
    assert agents[0].checkpoint_path.endswith("resume-a.json")
    await engine.aclose()


# ──────────────────────── (b) task correlation ──────────────────────────────


@pytest.mark.asyncio
async def test_agent_events_carry_parent_run_id_and_task_id(tmp_path):
    events = []

    async def sink(event):
        events.append(event)

    async def llm(_messages):
        return "FINAL ANSWER: done"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_sink(sink)
    agent = SubAgent(
        "corr-1", "correlate me", "WORKER", "run-parent",
        sink=sink, llm_call=llm, root=str(tmp_path), max_retries=0,
    )
    await engine._run_agent_with_retry(agent)

    correlated = [
        event for event in events
        if event["event_type"] in {"subagent.started", "subagent.result", "subagent.completed"}
    ]
    assert len(correlated) >= 3
    for event in correlated:
        assert event["run_id"] == "run-parent"
        assert event["parent_run_id"] == "run-parent"
        assert event["related_subagent"] == "corr-1"
        assert event["task_id"] == "corr-1"
        assert event["agent_id"] == "corr-1"
        assert event["hive_id"] == ""


@pytest.mark.asyncio
async def test_dependency_waves_emit_handoff_records(tmp_path):
    events = []

    async def sink(event):
        events.append(event)

    async def llm(_messages):
        return "done"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_sink(sink)
    engine.set_llm_call(llm)
    hive_id, agents = await engine.spawn_hive(
        [("base", "WORKER"), ("dependent", "WORKER")],
        dependencies={1: [0]},
        parent_run_id="hive-parent",
    )
    await engine._hive_tasks[hive_id]

    handoffs = [event for event in events if event["event_type"] == "handoff.completed"]
    assert len(handoffs) == 1
    assert handoffs[0]["payload"]["from"] == agents[0].agent_id
    assert handoffs[0]["payload"]["to"] == [agents[1].agent_id]
    assert handoffs[0]["hive_id"] == hive_id
    assert handoffs[0]["parent_run_id"] == "hive-parent"
    assert handoffs[0]["run_id"] == hive_id
    await engine.aclose()


# ─────────────── (c) parallel shared-state integrity ────────────────────────


def test_blackboard_cache_thread_safe_concurrent_posts(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    barrier = threading.Barrier(2)
    conflicts = []

    def writer(name):
        barrier.wait()
        try:
            engine.post_to_blackboard("shared", name, expected_version=0)
        except HiveStateConflict:
            conflicts.append(name)

    threads = [threading.Thread(target=writer, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Durable writes are serialized: exactly one writer wins, version stays 1.
    assert len(conflicts) == 1
    assert engine.get_blackboard_snapshot()["shared"]["version"] == 1
    # The in-memory cache agrees with the durable winner.
    assert engine.get_live_signals()["shared"] in {"a", "b"}


@pytest.mark.asyncio
async def test_agent_failure_does_not_corrupt_blackboard(tmp_path):
    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.post_to_blackboard("signal", {"v": 1}, writer="setup")

    async def failing_llm(_messages):
        raise RuntimeError("boom")

    agent = SubAgent(
        "fail-1", "x", "WORKER", "run-1",
        llm_call=failing_llm, root=str(tmp_path), max_retries=0,
    )
    with pytest.raises(RuntimeError):
        await engine._run_agent_with_retry(agent)

    assert engine.get_live_signals()["signal"] == {"v": 1}
    assert engine.get_blackboard_snapshot()["signal"]["version"] == 1


# ─────────────────── (d) partial failure visibility ─────────────────────────


@pytest.mark.asyncio
async def test_agent_records_redacted_error_and_survives_checkpoint(tmp_path):
    async def failing_llm(_messages):
        raise RuntimeError("provider failed with sk-hive-redact-123")

    agent = SubAgent(
        "fail-redact", "x", "WORKER", "run-1",
        llm_call=failing_llm, root=str(tmp_path), max_retries=0,
    )
    with pytest.raises(RuntimeError):
        await agent.run()

    assert agent.status == "failed"
    assert agent.error
    assert "sk-hive-redact-123" not in agent.error

    restored = SubAgent("fail-redact", "x", "WORKER", "run-1", root=str(tmp_path))
    assert restored.restore_checkpoint() is True
    assert restored.status == "failed"
    assert restored.error == agent.error


def test_concat_results_surfaces_failure_reasons_per_agent(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    ok_agent = SimpleNamespace(
        agent_id="a1", persona="WORKER", task="ok task",
        result="good result", status="success", tool_calls=[], error="",
    )
    bad_agent = SimpleNamespace(
        agent_id="a2", persona="REVIEWER", task="bad task",
        result="partial", status="failed", tool_calls=[],
        error="provider timeout",
    )
    out = engine._concat_results([ok_agent, bad_agent])

    assert "✓" in out and "✗" in out
    assert "good result" in out
    assert "provider timeout" in out


def test_assess_quorum_reports_failed_agents_with_reasons(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    engine._hives["hive_q"] = [
        SimpleNamespace(
            agent_id="q-ok", persona="WORKER", task="vote",
            result="VOTE: A", status="success", tool_calls=[], error="",
        ),
        SimpleNamespace(
            agent_id="q-bad", persona="WORKER", task="vote",
            result="", status="failed", tool_calls=[], error="disk full",
        ),
    ]

    assessment = engine.assess_quorum("hive_q", quorum=2)

    assert assessment["accepted"] is False
    assert assessment["failed"] == [
        {"agent_id": "q-bad", "persona": "WORKER", "status": "failed", "error": "disk full"}
    ]


@pytest.mark.asyncio
async def test_partial_failure_consolidation_marks_success_and_failure(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    engine._hives["hive_partial"] = [
        SimpleNamespace(
            agent_id="ok-1", persona="WORKER", task="t1",
            result="verified finding", status="success", tool_calls=[], error="",
        ),
        SimpleNamespace(
            agent_id="bad-1", persona="REVIEWER", task="t2",
            result="", status="failed", tool_calls=[],
            error="partial-error: crashed",
        ),
    ]

    out = await engine.consolidate_hive("hive_partial", timeout=1)

    assert "✓" in out
    assert "✗" in out
    assert "partial-error: crashed" in out


# ─────────────────────── (e) verified consolidation ─────────────────────────


@pytest.mark.asyncio
async def test_llm_consolidation_appends_verified_failed_agents_footnote(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    engine._hives["hive_mixed"] = [
        SimpleNamespace(
            agent_id="ok-1", persona="WORKER", task="t1",
            result="verified finding", status="success", tool_calls=[], error="",
        ),
        SimpleNamespace(
            agent_id="bad-1", persona="REVIEWER", task="t2",
            result="", status="failed", tool_calls=[], error="provider exploded",
        ),
    ]

    async def llm(_messages):
        return "merged answer"

    out = await engine.consolidate_hive("hive_mixed", timeout=1, llm_call=llm)

    # The LLM ignored the failed agent entirely; the deterministic footnote
    # must still surface it so the failure never vanishes.
    assert out.startswith("merged answer")
    assert "FAILED AGENTS (verified, not consolidated):" in out
    assert "bad-1" in out
    assert "provider exploded" in out


@pytest.mark.asyncio
async def test_llm_consolidation_failure_falls_back_without_fabrication(tmp_path):
    engine = NexusHiveEngine(str(tmp_path))
    engine._hives["hive_fb"] = [
        SimpleNamespace(
            agent_id="ok-1", persona="WORKER", task="t1",
            result="real finding", status="success", tool_calls=[], error="",
        ),
    ]

    async def exploding_llm(_messages):
        raise RuntimeError("consolidator down")

    out = await engine.consolidate_hive("hive_fb", timeout=1, llm_call=exploding_llm)

    # Concatenation fallback contains only verified child content.
    assert "real finding" in out
    assert "consolidator down" not in out
