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


def test_restart_reconciles_canonical_completion_without_rerunning_work(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "queue.sqlite"))
    control = ControlStore(str(tmp_path))
    task_id = queue.enqueue("perform one external side effect")
    leased = queue.lease(timeout_sec=0, worker_id="worker-a")
    assert leased and leased["id"] == task_id

    first = QueueDriver(kernel=_Kernel(_Loop()), queue=queue, control_store=control)
    meta = first._link_queue_task(leased, worker_id="worker-a")
    assert control.complete_run(
        run_id=meta["control_run_id"],
        lease_token=meta["control_lease_token"],
        evidence=[{"kind": "external_effect", "uri": "queue:side-effect"}],
    )

    # Simulate the process dying after canonical completion but before the
    # legacy queue acknowledgement. The expired queue lease is reclaimed.
    assert queue.requeue_expired_leases() == 1
    recovered = queue.lease(timeout_sec=30, worker_id="worker-b")
    assert recovered and recovered["id"] == task_id

    class ExplodingLoop:
        async def stream_run(self, *_args, **_kwargs):
            raise AssertionError("completed external work was rerun")
            yield  # pragma: no cover

    second = QueueDriver(
        kernel=_Kernel(ExplodingLoop()), queue=queue, control_store=control,
        idle_sleep=0.001,
    )
    linked = second._link_queue_task(recovered, worker_id="worker-b")
    assert linked["control_run_status"] == "succeeded"
    assert queue.complete(task_id, "reconciled", lease_token=recovered["lease_token"])
    assert queue.get(task_id)["state"] == "completed"
