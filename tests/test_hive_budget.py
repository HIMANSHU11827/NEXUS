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
