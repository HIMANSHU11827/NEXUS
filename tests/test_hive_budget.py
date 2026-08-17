import asyncio

import pytest

from hive.engine import NexusHiveEngine


@pytest.mark.asyncio
async def test_hive_concurrency_budget_limits_parallel_agents(tmp_path):
    active = 0
    peak = 0

    async def llm(messages):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        return f"done {messages[-1]['content']}"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0, max_concurrency=1)
    engine.set_llm_call(llm)
    hive_id, agents = await engine.spawn_hive([
        ("one", "WORKER"), ("two", "WORKER"), ("three", "WORKER"),
    ])
    await engine._hive_tasks[hive_id]

    assert peak == 1
    assert all(agent.status == "success" for agent in agents)


@pytest.mark.asyncio
async def test_hive_default_concurrency_remains_parallel(tmp_path):
    active = 0
    peak = 0

    async def llm(messages):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        return f"done {messages[-1]['content']}"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(llm)
    hive_id, _agents = await engine.spawn_hive([("one", "WORKER"), ("two", "WORKER")])
    await engine._hive_tasks[hive_id]
    assert peak == 2


def test_hive_default_concurrency_is_bounded_cap_not_unlimited(tmp_path, monkeypatch):
    """Regression (P27): the default constructor must not permit an unbounded
    parallel spawn; an explicit 0 preserves the documented legacy opt-out."""
    monkeypatch.delenv("NEXUS_HIVE_MAX_CONCURRENCY", raising=False)
    defaulted = NexusHiveEngine(str(tmp_path))
    assert defaulted.max_concurrency == 8
    assert defaulted._agent_semaphore is not None

    unlimited = NexusHiveEngine(str(tmp_path), max_concurrency=0)
    assert unlimited.max_concurrency == 0
    assert unlimited._agent_semaphore is None


def test_hive_default_concurrency_honors_env_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_HIVE_MAX_CONCURRENCY", "3")
    capped = NexusHiveEngine(str(tmp_path))
    assert capped.max_concurrency == 3

    monkeypatch.setenv("NEXUS_HIVE_MAX_CONCURRENCY", "not-an-int")
    safe = NexusHiveEngine(str(tmp_path))
    assert safe.max_concurrency == 8


@pytest.mark.asyncio
async def test_hive_aggregate_step_budget_fails_closed(tmp_path):
    calls = 0

    async def llm(messages):
        nonlocal calls
        calls += 1
        return f"done {messages[-1]['content']}"

    engine = NexusHiveEngine(
        str(tmp_path), max_agent_retries=0, max_concurrency=1, max_total_steps=2
    )
    engine.set_llm_call(llm)
    hive_id, agents = await engine.spawn_hive([
        ("one", "WORKER"), ("two", "WORKER"), ("three", "WORKER"),
    ])
    await engine._hive_tasks[hive_id]

    assert calls == 2
    assert [agent.status for agent in agents].count("success") == 2
    assert [agent.status for agent in agents].count("failed") == 1
    assert "aggregate step budget" in agents[-1].result.lower() or agents[-1].status == "failed"
    await engine.aclose()
