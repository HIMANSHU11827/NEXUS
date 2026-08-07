import asyncio

from nexus.control_store import ControlStore
from queue.driver import QueueDriver
from queue.store import TaskQueue


class _Loop:
    def __init__(self):
        self.kwargs = None

    async def stream_run(self, _prompt, **kwargs):
        self.kwargs = kwargs
        yield {"type": "done", "data": {"success": True, "response": "done"}}


class _Kernel:
    root = "."

    def __init__(self, loop):
        self.loop = loop


def test_queue_job_is_linked_to_control_task_and_v5_receives_task_id(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "queue.sqlite"))
    item = queue.enqueue("inspect the architecture", session_id="session-a")
    leased = queue.lease(worker_id="worker-a")
    loop = _Loop()
    driver = QueueDriver(kernel=_Kernel(loop), queue=queue, control_store=ControlStore(str(tmp_path)))
    asyncio.run(driver._run_with_heartbeat(driver._link_queue_task(leased) and leased, task_id=item, lease_token=leased["lease_token"], leased_at=0))
    assert loop.kwargs["task_id"].startswith("task_")
    assert loop.kwargs["turn_id"].startswith("run_")
    assert driver.control_store.pending_outbox()[-1]["event_type"] == "legacy.linked"
