import asyncio
import threading

import pytest

from hive.engine import SubAgent


@pytest.mark.asyncio
async def test_sync_hive_tool_runs_off_event_loop(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def blocking_tool():
        started.set()
        release.wait(timeout=2)
        return "completed"

    agent = SubAgent(
        "agent-boundary",
        "run tool",
        "WORKER",
        "run-boundary",
        root=str(tmp_path),
        tool_registry={"blocking": blocking_tool},
    )
    pending = asyncio.create_task(agent._execute_tool("blocking", {}))
    await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 1)

    # The loop remains responsive while the synchronous tool is blocked.
    await asyncio.wait_for(asyncio.sleep(0), 0.2)
    release.set()

    assert await asyncio.wait_for(pending, 1) == "completed"


@pytest.mark.asyncio
async def test_cancelled_sync_hive_model_cannot_mark_agent_success(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def blocking_llm(_messages):
        started.set()
        release.wait(timeout=2)
        return "late model result"

    agent = SubAgent(
        "agent-model-boundary",
        "wait for model",
        "WORKER",
        "run-model-boundary",
        root=str(tmp_path),
        llm_call=blocking_llm,
    )
    pending = asyncio.create_task(agent.run())
    await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert agent.status == "cancelled"
    assert agent.result == ""
    release.set()
