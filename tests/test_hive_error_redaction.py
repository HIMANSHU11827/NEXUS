import pytest

from hive.engine import SubAgent


@pytest.mark.asyncio
async def test_subagent_failure_event_redacts_secret(tmp_path):
    events = []

    async def sink(event):
        events.append(event)

    async def failing_llm(_messages):
        raise RuntimeError("provider failed with sk-live-hive-secret")

    agent = SubAgent(
        "agent-1", "research", "WORKER", "run-1", sink=sink,
        llm_call=failing_llm, root=str(tmp_path), max_retries=0,
    )
    with pytest.raises(RuntimeError):
        await agent.run()

    failure = next(event for event in events if event["event_type"] == "subagent.failed")
    message = failure["error"]["message"]
    assert "sk-live-hive-secret" not in message
    assert "***REDACTED***" in message


@pytest.mark.asyncio
async def test_tool_failure_observation_redacts_secret(tmp_path):
    async def failing_tool(_name, _params):
        raise RuntimeError("tool failed with sk-live-tool-secret")

    calls = iter([
        '<tool_call>{"tool":"read","params":{}}</tool_call>',
        "FINAL ANSWER: recovered",
    ])

    async def llm(_messages):
        return next(calls)

    agent = SubAgent(
        "agent-2", "inspect", "WORKER", "run-2", llm_call=llm,
        tool_registry=failing_tool, root=str(tmp_path), max_steps=2,
    )
    result = await agent.run()

    assert result == "FINAL ANSWER: recovered"
    transcript = "\n".join(item["content"] for item in agent.transcript)
    assert "sk-live-tool-secret" not in transcript
    assert "***REDACTED***" in transcript


@pytest.mark.asyncio
async def test_successful_tool_output_and_checkpoint_are_redacted(tmp_path):
    async def successful_tool(_name, _params):
        return "document contains sk-live-success-secret"

    calls = iter([
        '<tool_call>{"tool":"read","params":{"token":"sk-live-param-secret"}}</tool_call>',
        "FINAL ANSWER: recovered",
    ])

    async def llm(_messages):
        return next(calls)

    agent = SubAgent(
        "agent-3", "inspect", "WORKER", "run-3", llm_call=llm,
        tool_registry=successful_tool, root=str(tmp_path), max_steps=2,
    )
    await agent.run()

    transcript = "\n".join(item["content"] for item in agent.transcript)
    checkpoint = (tmp_path / ".nexus" / "hive" / "checkpoints" / "agent-3.json").read_text()
    assert "sk-live-success-secret" not in transcript + checkpoint
    assert "sk-live-param-secret" not in checkpoint
    assert "***REDACTED***" in transcript + checkpoint


@pytest.mark.asyncio
async def test_empty_llm_result_is_not_marked_success(tmp_path):
    async def empty_llm(_messages):
        return "   "

    agent = SubAgent(
        "agent-4", "empty", "WORKER", "run-4", llm_call=empty_llm,
        root=str(tmp_path), max_retries=0,
    )
    with pytest.raises(RuntimeError, match="empty result"):
        await agent.run()

    assert agent.status == "failed"


@pytest.mark.asyncio
async def test_tool_budget_exhaustion_cannot_finish_with_another_tool_call(tmp_path):
    async def llm(_messages):
        return '<tool_call>{"tool":"read","params":{}}</tool_call>'

    agent = SubAgent(
        "agent-5", "loop", "WORKER", "run-5", llm_call=llm,
        tool_registry={"read": lambda: "ok"}, root=str(tmp_path), max_steps=1,
    )
    with pytest.raises(RuntimeError, match="without a final answer"):
        await agent.run()

    assert agent.status == "failed"
