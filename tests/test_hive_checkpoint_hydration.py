import asyncio

import pytest

from hive.engine import NexusHiveEngine, SubAgent


@pytest.mark.asyncio
async def test_spawn_hive_hydrates_matching_agent_checkpoint(tmp_path):
    checkpoint_agent = SubAgent(
        "resume-agent",
        "resume this task",
        "ENGINEER",
        "old-hive",
        root=str(tmp_path),
    )
    checkpoint_agent.hive_id = "old-hive"
    checkpoint_agent.steps_used = 2
    checkpoint_agent.transcript = [{"role": "assistant", "content": "prior progress"}]
    checkpoint_agent.tool_calls = [{"step": 1, "tool": "read", "result": "done"}]
    checkpoint_agent.checkpoint()

    async def llm(messages):
        assert any(item.get("content") == "prior progress" for item in messages)
        return "FINAL ANSWER: resumed"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(llm)
    hive_id, agents = await engine.spawn_hive(
        [("resume this task", "ENGINEER")],
        parent_run_id="old-hive",
        agent_ids=["resume-agent"],
    )
    await asyncio.wait_for(engine._hive_tasks[hive_id], 1)

    assert agents[0].agent_id == "resume-agent"
    assert agents[0].hive_id == hive_id
    assert agents[0].steps_used >= 2
    assert agents[0].tool_calls[0]["tool"] == "read"
    await engine.aclose()


@pytest.mark.asyncio
async def test_spawn_hive_rejects_checkpoint_for_different_task(tmp_path):
    checkpoint_agent = SubAgent(
        "resume-agent",
        "original task",
        "ENGINEER",
        "old-hive",
        root=str(tmp_path),
    )
    checkpoint_agent.hive_id = "old-hive"
    checkpoint_agent.transcript = [{"role": "assistant", "content": "must not load"}]
    checkpoint_agent.checkpoint()

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(lambda _messages: "FINAL ANSWER: fresh")
    hive_id, agents = await engine.spawn_hive(
        [("different task", "ENGINEER")], agent_ids=["resume-agent"]
    )
    await asyncio.wait_for(engine._hive_tasks[hive_id], 1)

    assert agents[0].transcript == []
    await engine.aclose()


@pytest.mark.asyncio
async def test_spawn_hive_does_not_overwrite_duplicate_agent_ids(tmp_path):
    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    engine.set_llm_call(lambda _messages: "FINAL ANSWER: isolated")

    hive_id, agents = await engine.spawn_hive(
        [("first", "ENGINEER"), ("second", "ENGINEER")],
        agent_ids=["shared-agent", "shared-agent"],
    )
    await asyncio.wait_for(engine._hive_tasks[hive_id], 1)

    assert agents[0].agent_id == "shared-agent"
    assert agents[1].agent_id != "shared-agent"
    assert engine._agents[agents[0].agent_id] is agents[0]
    assert engine._agents[agents[1].agent_id] is agents[1]
    await engine.aclose()
