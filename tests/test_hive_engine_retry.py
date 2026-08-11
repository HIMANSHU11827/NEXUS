import asyncio

import pytest

from hive.engine import NexusHiveEngine, SubAgent


@pytest.mark.asyncio
async def test_subagent_retries_transient_failure_with_stable_identity(tmp_path):
    calls = []
    events = []

    async def llm(_messages):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary provider failure")
        return "recovered result"

    async def sink(event):
        events.append(event)

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=1)
    engine.set_sink(sink)
    agent = SubAgent(
        "agent-stable", "recover this", "WORKER", "hive-1",
        sink=sink, llm_call=llm, root=str(tmp_path), max_retries=1,
    )
    result = await engine._run_agent_with_retry(agent)

    assert result == "recovered result"
    assert agent.agent_id == "agent-stable"
    assert agent.attempts == 2
    assert agent.status == "success"
    assert any(event["event_type"] == "subagent.retry" for event in events)


@pytest.mark.asyncio
async def test_subagent_retry_limit_preserves_final_failure(tmp_path):
    async def llm(_messages):
        raise RuntimeError("persistent provider failure")

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=1)
    agent = SubAgent(
        "agent-fail", "fail", "WORKER", "hive-1",
        llm_call=llm, root=str(tmp_path), max_retries=1,
    )
    with pytest.raises(RuntimeError, match="persistent provider failure"):
        await engine._run_agent_with_retry(agent)
    assert agent.attempts == 2
    assert agent.status == "failed"


@pytest.mark.asyncio
async def test_subagent_checkpoint_survives_restart(tmp_path):
    async def llm(_messages):
        return "checkpointed answer"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    original = SubAgent(
        "agent-checkpoint", "remember this", "RESEARCHER", "hive-1",
        llm_call=llm, root=str(tmp_path), max_retries=0,
    )
    assert await engine._run_agent_with_retry(original) == "checkpointed answer"
    assert original.checkpoint_path.endswith("agent-checkpoint.json")

    restored = SubAgent(
        "agent-checkpoint", "remember this", "RESEARCHER", "hive-1",
        llm_call=llm, root=str(tmp_path), max_retries=0,
    )
    assert restored.restore_checkpoint() is True
    assert restored.status == "success"
    assert restored.result == "checkpointed answer"
    assert restored.transcript == []
