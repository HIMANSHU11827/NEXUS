import asyncio

import pytest

from nexus.main_agent.core import NexusLoopV5


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "timeout", "cancel"])
async def test_turn_boundary_always_cleans_run_context_heartbeat(tmp_path, outcome):
    loop = NexusLoopV5(str(tmp_path), session_id=f"heartbeat-{outcome}")
    stopped = asyncio.Event()
    heartbeat_exited = asyncio.Event()
    turn_id = f"turn-{outcome}"

    async def heartbeat():
        try:
            await asyncio.Event().wait()
        finally:
            heartbeat_exited.set()

    async def fake_impl(*_args, **_kwargs):
        task = asyncio.create_task(heartbeat())
        loop._run_context_heartbeats[turn_id] = (stopped, task)
        await asyncio.sleep(0)
        if outcome == "failure":
            raise RuntimeError("fixture failure")
        if outcome == "timeout":
            raise asyncio.TimeoutError("fixture timeout")
        if outcome == "cancel":
            raise asyncio.CancelledError("fixture cancel")
        yield {"type": "done", "data": {"turn_id": turn_id, "success": True}}

    loop._turn_events_impl = fake_impl
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            async for _event in loop._turn_events("work", turn_id=turn_id):
                pass
    else:
        events = [
            event async for event in loop._turn_events("work", turn_id=turn_id)
        ]
        assert any(event.get("type") == "done" for event in events)

    assert stopped.is_set()
    assert heartbeat_exited.is_set()
    assert turn_id not in loop._run_context_heartbeats


@pytest.mark.asyncio
async def test_v5_aclose_detaches_cancellation_resistant_background_task(
    tmp_path, monkeypatch
):
    loop = NexusLoopV5(str(tmp_path), session_id="bounded-close")
    release = asyncio.Event()
    cancellation_seen = asyncio.Event()

    async def resistant():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()

    task = asyncio.create_task(resistant())
    loop._background_tasks.add(task)
    monkeypatch.setenv("NEXUS_SHUTDOWN_TIMEOUT", "0.1")

    await asyncio.wait_for(loop.aclose(), 0.5)
    assert cancellation_seen.is_set()
    assert task in loop._detached_lifecycle_tasks
    assert loop._detached_lifecycle_task_count == 1
    assert loop.work_event_sink is None
    assert loop.runtime.work_event_sink is None

    release.set()
    await asyncio.wait_for(task, 0.5)
    await asyncio.sleep(0)
    assert task not in loop._detached_lifecycle_tasks
