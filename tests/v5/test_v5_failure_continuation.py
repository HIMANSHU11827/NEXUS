"""Regression coverage for V5 continuing after tool execution failures."""

import asyncio
import os

import pytest

from nexus.main_agent.core import NexusLoopV5
from nexus.run_context import load_run_context


def _tool_call(name: str, arguments: str, call_id: str):
    return {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }],
            }
        }]
    }


def _final_response(content: str):
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_ordinary_tool_failure_is_observed_before_later_success(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="ordinary-failure-continuation")
    model_rounds = 0
    observed_messages = []

    async def model(messages, **_kwargs):
        nonlocal model_rounds
        model_rounds += 1
        observed_messages.append(list(messages))
        if model_rounds == 1:
            return _tool_call("fixture_tool", '{"attempt":"first"}', "first")
        if model_rounds == 2:
            return _tool_call("fixture_tool", '{"attempt":"retry"}', "retry")
        return _final_response("The retry completed successfully.")

    async def tool(call):
        if call.params["attempt"] == "first":
            raise RuntimeError("fixture tool failed")
        return "verified retry output"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **_kwargs: []
    loop._run_tool = tool

    result = await loop._run_direct_model_tool_loop("run the fixture check", max_rounds=3)

    assert result["success"] is True
    assert result["response"] == "The retry completed successfully."
    assert [action["success"] for action in result["actions"]] == [False, True]
    assert result["actions"][0]["repaired"] is True
    assert result["calls_executed"] == 2
    assert any(
        message.get("role") == "tool"
        and "fixture tool failed" in message.get("content", "")
        for message in observed_messages[1]
    )


@pytest.mark.asyncio
async def test_tool_timeout_becomes_observation_and_loop_finalizes_after_retry(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="timeout-continuation")
    model_rounds = 0
    seen_attempts = []
    # Pin retry to 1 so this test isolates the timeout->observation->model-retry
    # contract (no inner retry conflating the timed-out attempt).
    _prev = os.environ.get("NEXUS_TOOL_MAX_RETRIES")
    os.environ["NEXUS_TOOL_MAX_RETRIES"] = "1"
    try:
        async def model(messages, **_kwargs):
            nonlocal model_rounds
            model_rounds += 1
            if model_rounds == 1:
                return _tool_call("fixture_tool", '{"attempt":"timed-out"}', "timeout")
            if model_rounds == 2:
                return _tool_call("fixture_tool", '{"attempt":"after-timeout"}', "after-timeout")
            return _final_response("The timed-out check was recovered and verified.")

        async def tool(call):
            attempt = call.params["attempt"]
            seen_attempts.append(attempt)
            if attempt == "timed-out":
                raise asyncio.TimeoutError("fixture tool timed out")
            return "verified after timeout"

        loop._safe_model_call_raw = model
        loop._get_direct_tool_schemas = lambda **_kwargs: []
        loop._run_tool = tool

        result = await loop._run_direct_model_tool_loop("finish the timed check", max_rounds=3)

        assert result["success"] is True
        assert result["response"] == "The timed-out check was recovered and verified."
        assert seen_attempts == ["timed-out", "after-timeout"]
        assert result["actions"][0]["error"].startswith("Error: fixture tool timed out")
        assert result["actions"][0]["repaired"] is True
    finally:
        if _prev is None:
            os.environ.pop("NEXUS_TOOL_MAX_RETRIES", None)
        else:
            os.environ["NEXUS_TOOL_MAX_RETRIES"] = _prev
    assert result["actions"][1]["success"] is True


@pytest.mark.asyncio
async def test_tool_self_cancellation_is_observed_before_later_success(tmp_path):
    """A child/tool stop must not cancel the owning NEXUS turn."""
    loop = NexusLoopV5(str(tmp_path), session_id="self-cancel-continuation")
    model_rounds = 0

    async def model(messages, **_kwargs):
        nonlocal model_rounds
        model_rounds += 1
        if model_rounds == 1:
            return _tool_call("fixture_tool", '{"attempt":"stopped"}', "stopped")
        if model_rounds == 2:
            return _tool_call("fixture_tool", '{"attempt":"retry"}', "retry")
        return _final_response("The stopped tool was recovered and verified.")

    async def tool(call):
        if call.params["attempt"] == "stopped":
            raise asyncio.CancelledError("child operation stopped")
        return "verified after child stop"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **_kwargs: []
    loop._run_tool = tool

    result = await loop._run_direct_model_tool_loop("recover from a stopped fixture", max_rounds=3)

    assert result["success"] is True
    assert result["response"] == "The stopped tool was recovered and verified."
    assert [action["success"] for action in result["actions"]] == [False, True]
    assert result["actions"][0]["error"].startswith("Error: tool cancelled")


@pytest.mark.asyncio
async def test_tool_can_cancel_its_own_child_task_without_stopping_the_loop(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="child-task-cancel-continuation")
    model_rounds = 0

    async def model(_messages, **_kwargs):
        nonlocal model_rounds
        model_rounds += 1
        if model_rounds == 1:
            return _tool_call("fixture_tool", '{"attempt":"child-stop"}', "child-stop")
        if model_rounds == 2:
            return _tool_call("fixture_tool", '{"attempt":"retry"}', "retry")
        return _final_response("The child task stop was recovered.")

    async def tool(call):
        if call.params["attempt"] == "child-stop":
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        return "verified retry output"

    loop._safe_model_call_raw = model
    loop._get_direct_tool_schemas = lambda **_kwargs: []
    loop._run_tool = tool

    result = await loop._run_direct_model_tool_loop("recover from a child stop", max_rounds=3)

    assert result["success"] is True
    assert result["response"] == "The child task stop was recovered."
    assert result["actions"][0]["success"] is False
    assert result["actions"][1]["success"] is True


@pytest.mark.asyncio
async def test_preflight_exception_still_yields_terminal_done(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="preflight-failure")
    loop.sync_memory = lambda: (_ for _ in ()).throw(RuntimeError("preflight broke"))

    events = [event async for event in loop._turn_events("start safely", turn_id="preflight-1")]

    done = [event for event in events if event.get("type") == "done"]
    assert len(done) == 1
    assert done[0]["data"]["success"] is False
    assert "preflight broke" in done[0]["data"]["error"]


@pytest.mark.asyncio
async def test_run_started_sink_failure_closes_durable_context(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="started-event-failure")

    async def broken_sink(*_args, **_kwargs):
        raise RuntimeError("event sink broke")

    loop._emit_runtime_event = broken_sink
    events = [event async for event in loop._turn_events("start safely", turn_id="started-1")]

    done = [event for event in events if event.get("type") == "done"]
    assert len(done) == 1
    assert done[0]["data"]["success"] is False
    context = load_run_context(str(tmp_path), "started-event-failure", "started-1")
    assert context["status"] == "failed"
    assert context["terminal_event"] == "run.failed"
