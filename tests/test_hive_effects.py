import pytest

from hive.effects import HiveEffectLedger
from hive.engine import NexusHiveEngine, SubAgent


def test_effect_ledger_replays_completed_effect(tmp_path):
    ledger = HiveEffectLedger(str(tmp_path))
    key = ledger.key("agent", "task", 1, "write", {"path": "x"})
    assert ledger.claim(key, "agent", "write")[0] == "execute"
    ledger.complete(key, "written")
    assert ledger.claim(key, "agent", "write") == ("replay", "written")


def test_effect_ledger_refuses_live_duplicate(tmp_path):
    ledger = HiveEffectLedger(str(tmp_path), lease_seconds=60)
    key = ledger.key("agent", "task", 1, "write", {"path": "x"})
    assert ledger.claim(key, "agent", "write")[0] == "execute"
    decision, message = ledger.claim(key, "agent-2", "write")
    assert decision == "uncertain"
    assert "duplicate" in message


@pytest.mark.asyncio
async def test_subagent_tool_retry_replays_completed_effect(tmp_path):
    calls = []
    responses = iter([
        '<tool_call>{"tool":"write","params":{"path":"x"}}</tool_call>',
        "final answer",
    ])

    async def llm(_messages):
        return next(responses)

    async def write(**_params):
        calls.append("write")
        return "written"

    engine = NexusHiveEngine(str(tmp_path), max_agent_retries=0)
    agent = SubAgent(
        "agent-effect", "perform write", "ENGINEER", "hive-1",
        llm_call=llm, tool_registry={"write": write}, root=str(tmp_path), max_steps=2,
        effect_ledger=engine.effect_ledger,
    )
    result = await agent.run()
    assert result == "final answer"
    assert calls == ["write"]

    # A fresh agent with the same identity/step gets the durable result rather
    # than invoking the side effect again.
    responses2 = iter([
        '<tool_call>{"tool":"write","params":{"path":"x"}}</tool_call>',
        "final answer",
    ])

    async def llm2(_messages):
        return next(responses2)

    restored = SubAgent(
        "agent-effect", "perform write", "ENGINEER", "hive-1",
        llm_call=llm2, tool_registry={"write": write}, root=str(tmp_path), max_steps=2,
        effect_ledger=engine.effect_ledger,
    )
    assert await restored.run() == "final answer"
    assert calls == ["write"]


@pytest.mark.asyncio
async def test_subagent_reconciles_uncertain_effect_without_duplicate_execution(tmp_path):
    calls = []
    responses = iter([
        '<tool_call>{"tool":"write","params":{"path":"x"}}</tool_call>',
        "final answer",
    ])

    async def llm(_messages):
        return next(responses)

    async def write(**_params):
        calls.append("write")
        return "duplicate would be dangerous"

    ledger = HiveEffectLedger(str(tmp_path), lease_seconds=60)
    key = ledger.key("agent-reconcile", "perform write", 1, "write", {"path": "x"})
    assert ledger.claim(key, "crashed-process", "write")[0] == "execute"

    async def reconcile(effect_key, tool, params):
        assert effect_key == key
        assert tool == "write"
        assert params == {"path": "x"}
        return "already written"

    agent = SubAgent(
        "agent-reconcile", "perform write", "ENGINEER", "hive-1",
        llm_call=llm, tool_registry={"write": write}, root=str(tmp_path), max_steps=2,
        effect_ledger=ledger, effect_reconciler=reconcile,
    )
    assert await agent.run() == "final answer"
    assert calls == []
    assert ledger.claim(key, "later-retry", "write") == ("replay", "already written")


@pytest.mark.asyncio
async def test_uncertain_effect_fails_closed_when_reconciliation_is_unknown(tmp_path):
    calls = []
    responses = iter([
        '<tool_call>{"tool":"write","params":{"path":"x"}}</tool_call>',
        "final answer",
    ])

    llm_calls = []

    async def llm(messages):
        llm_calls.append(messages)
        if len(llm_calls) > 1:
            assert "OUTCOME UNCERTAIN" in messages[-1]["content"]
        return next(responses)

    async def write(**_params):
        calls.append("write")
        return "written"

    ledger = HiveEffectLedger(str(tmp_path), lease_seconds=60)
    key = ledger.key("agent-unknown", "perform write", 1, "write", {"path": "x"})
    assert ledger.claim(key, "crashed-process", "write")[0] == "execute"

    agent = SubAgent(
        "agent-unknown", "perform write", "ENGINEER", "hive-1",
        llm_call=llm, tool_registry={"write": write}, root=str(tmp_path), max_steps=2,
        effect_ledger=ledger, effect_reconciler=lambda *_args: None,
    )
    assert await agent.run() == "final answer"
    assert calls == []


@pytest.mark.asyncio
async def test_cancelled_sync_effect_remains_uncertain_for_safe_retry(tmp_path):
    import asyncio
    import threading

    started = threading.Event()
    release = threading.Event()

    def write(**_params):
        started.set()
        release.wait(timeout=2)
        return "side effect completed after cancellation"

    ledger = HiveEffectLedger(str(tmp_path), lease_seconds=60)
    agent = SubAgent(
        "agent-cancelled-effect", "perform write", "ENGINEER", "hive-1",
        tool_registry={"write": write}, root=str(tmp_path),
        effect_ledger=ledger,
    )
    pending = asyncio.create_task(agent._execute_tool_guarded("write", {}, 1))
    await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    release.set()
    await asyncio.sleep(0.05)

    key = ledger.key(agent.agent_id, agent.task, 1, "write", {})
    decision, message = ledger.claim(key, "retry-agent", "write")
    assert decision == "uncertain"
    assert "duplicate" in message
