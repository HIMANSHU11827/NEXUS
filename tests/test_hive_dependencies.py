import pytest

from hive.engine import NexusHiveEngine


@pytest.mark.asyncio
async def test_hive_dependency_waves_run_prerequisites_before_dependents(tmp_path):
    calls = []

    async def llm(messages):
        task = messages[-1]["content"]
        calls.append(task)
        return f"done: {task}"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(llm)
    hive_id, agents = await engine.spawn_hive(
        [("implement", "ENGINEER"), ("review", "REVIEWER")],
        dependencies={1: [0]},
    )
    await engine._hive_tasks[hive_id]

    assert calls == ["implement", "review"]
    assert [agent.status for agent in agents] == ["success", "success"]


@pytest.mark.asyncio
async def test_hive_failed_prerequisite_blocks_dependent(tmp_path):
    calls = []

    async def llm(messages):
        task = messages[-1]["content"]
        calls.append(task)
        if task == "implement":
            raise RuntimeError("implementation failed")
        return "should not run"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(llm)
    hive_id, agents = await engine.spawn_hive(
        [("implement", "ENGINEER"), ("review", "REVIEWER")],
        dependencies={1: [0]},
    )
    await engine._hive_tasks[hive_id]

    assert calls == ["implement"]
    assert agents[0].status == "failed"
    assert agents[1].status == "failed"
    assert "dependency failed" in agents[1].result


@pytest.mark.asyncio
async def test_hive_dependency_cycle_fails_closed(tmp_path):
    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(lambda _messages: "not executed")
    hive_id, agents = await engine.spawn_hive(
        [("a", "WORKER"), ("b", "WORKER")],
        dependencies={0: [1], 1: [0]},
    )
    await engine._hive_tasks[hive_id]
    assert all(agent.status == "failed" for agent in agents)
    assert all("dependency cycle" in agent.result for agent in agents)
