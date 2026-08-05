import asyncio

import pytest

from queue.driver import QueueDriver


class _Loop:
    def __init__(self, success=True):
        self.success = success
        self.received = None

    async def stream_run(self, task_desc, **kwargs):
        self.received = (task_desc, kwargs)
        yield {"type": "status", "data": {"title": "working"}}
        yield {
            "type": "done",
            "data": {
                "success": self.success,
                "response": "done" if self.success else "failed",
                "error": "provider unavailable" if not self.success else "",
            },
        }


class _Kernel:
    def __init__(self, loop):
        self.loop = loop
        self.root = "."


def test_queue_driver_uses_canonical_stream_run_and_propagates_session():
    loop = _Loop()
    driver = QueueDriver(kernel=_Kernel(loop), queue=object())
    result = asyncio.run(driver.run_task({
        "id": 1,
        "payload": {
            "task_desc": "build it",
            "model": "local-model",
            "meta": {"session_id": "session-7"},
        },
    }))
    assert result == "done"
    assert loop.received == ("build it", {"model": "local-model", "voice_mode": False})


def test_queue_driver_does_not_mark_failed_turn_complete():
    driver = QueueDriver(kernel=_Kernel(_Loop(success=False)), queue=object())
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(driver.run_task({"id": 1, "payload": {"task_desc": "try"}}))
