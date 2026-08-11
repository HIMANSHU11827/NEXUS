"""Idempotency identity propagation into the V5 turn/tool context."""

import asyncio

from orchestrators.v5.core import NexusLoopV5


def test_stream_run_propagates_idempotency_key_into_turn_context(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="idempotency-session")
    captured = {}

    async def fake_turn_events(*_args, **kwargs):
        captured.update(kwargs)
        yield {"type": "done", "data": {"success": True, "response": "ok"}}

    loop._turn_events = fake_turn_events
    events = list(asyncio.run(_collect(loop.stream_run(
        "perform one side effect",
        task_id="task-1",
        turn_id="run-1",
        idempotency_key="queue:test:1",
    ))))

    assert events[-1]["data"]["success"] is True
    assert captured["idempotency_key"] == "queue:test:1"


async def _collect(iterator):
    values = []
    async for item in iterator:
        values.append(item)
    return values
