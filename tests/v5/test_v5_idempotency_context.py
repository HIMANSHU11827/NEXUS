"""Idempotency identity propagation into the V5 turn/tool context."""

import asyncio

from nexus.main_agent.core import NexusLoopV5


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


def test_run_propagates_idempotency_and_absolute_deadline(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="run-parity")
    captured = {}

    async def fake_turn_events(*_args, **kwargs):
        captured.update(kwargs)
        yield {"type": "done", "data": {"success": True, "response": "ok"}}

    loop._turn_events = fake_turn_events
    result = asyncio.run(loop.run(
        "perform one side effect",
        task_id="task-2",
        idempotency_key="queue:test:2",
        deadline_at=12345.0,
    ))

    assert result["success"] is True
    assert captured["idempotency_key"] == "queue:test:2"
    assert captured["deadline_at"] == 12345.0


async def _collect(iterator):
    values = []
    async for item in iterator:
        values.append(item)
    return values
