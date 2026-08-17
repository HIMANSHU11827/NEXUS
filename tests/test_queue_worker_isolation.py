"""Worker isolation tests for the NEXUS queue driver.

A worker that hits its crash-limit quarantine must terminate alone: siblings
keep leasing and completing tasks, a replacement worker (bounded by
``NEXUS_QUEUE_WORKER_REPLACEMENTS``) may take the dead slot, and ``run()``
reports total failure only when every worker is actually dead. Cancellation
must never be mistaken for a crash.
"""

import asyncio
import time

import pytest

from queue.driver import QueueDriver
from queue.store import TaskQueue


class _Loop:
    def __init__(self, delay=0.0, success=True):
        self.delay = delay
        self.success = success
        self.received = None

    async def stream_run(self, task_desc, **kwargs):
        self.received = (task_desc, kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
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


class _NoopControlStore:
    def reap_expired_runs(self, *args, **kwargs):
        return 0

    def renew_run(self, *args, **kwargs):
        return True

    def complete_run(self, *args, **kwargs):
        return None

    def fail_run(self, *args, **kwargs):
        return None


def _crash_env(monkeypatch, limit=1, window=60, replacements=0):
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_CRASH_LIMIT", str(limit))
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_CRASH_WINDOW", str(window))
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_REPLACEMENTS", str(replacements))


async def _wait_until(predicate, timeout=5.0, step=0.005):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition was not met within %.1fs" % timeout)
        await asyncio.sleep(step)


def test_one_worker_crash_does_not_cancel_siblings(tmp_path, monkeypatch):
    _crash_env(monkeypatch, limit=1, window=60, replacements=0)
    queue = TaskQueue(db_path=str(tmp_path / "q.db"))

    class Driver(QueueDriver):
        def _link_queue_task(self, task, worker_id="queue-worker"):
            return {}

        async def _worker(self, worker_id):
            if worker_id == "w1":
                raise RuntimeError("simulated glue failure on w1")
            await super()._worker(worker_id)

    for index in range(3):
        queue.enqueue(f"task {index}", max_attempts=1)
    driver = Driver(
        kernel=_Kernel(_Loop()), queue=queue, workers=2, idle_sleep=0.005,
        control_store=_NoopControlStore(),
    )
    driver._publish_runtime_status = lambda **_kwargs: None

    async def scenario():
        run_task = asyncio.create_task(driver.run())
        await _wait_until(
            lambda: driver.stats["completed"] == 3
            and "w1" in driver._quarantined_workers
        )
        # w1 is quarantined and isolated; the surviving worker drained the queue.
        assert driver.stats["completed"] == 3
        assert driver.stats["quarantined_workers"] == ["w1"]
        assert driver.stats["worker_restarts"] == 1
        assert driver._stopping is False
        assert not run_task.done()
        driver.stop()
        await asyncio.wait_for(run_task, timeout=2)
        return driver

    driver = asyncio.run(scenario())
    assert queue.pending_count() == 0
    assert queue.list_states()["completed"] == 3


def test_all_workers_crashed_raises(tmp_path, monkeypatch):
    _crash_env(monkeypatch, limit=1, window=60, replacements=0)

    class Driver(QueueDriver):
        async def _worker(self, worker_id):
            raise RuntimeError("broken glue on " + worker_id)

    driver = Driver(queue=object(), workers=2, idle_sleep=0.001)
    driver._publish_runtime_status = lambda **_kwargs: None

    with pytest.raises(RuntimeError, match="all queue workers quarantined"):
        asyncio.run(driver.run())
    assert set(driver._quarantined_workers) == {"w1", "w2"}
    assert driver._tasks == []
    assert driver.stats["quarantined_workers"] == ["w1", "w2"]


def test_worker_replacement_takes_over_after_quarantine(tmp_path, monkeypatch):
    _crash_env(monkeypatch, limit=1, window=60, replacements=1)
    queue = TaskQueue(db_path=str(tmp_path / "q.db"))

    class Driver(QueueDriver):
        def _link_queue_task(self, task, worker_id="queue-worker"):
            return {}

        async def _worker(self, worker_id):
            if worker_id == "w1":
                raise RuntimeError("simulated glue failure on w1")
            await super()._worker(worker_id)

    queue.enqueue("first task", max_attempts=1)
    driver = Driver(
        kernel=_Kernel(_Loop()), queue=queue, workers=1, idle_sleep=0.005,
        control_store=_NoopControlStore(),
    )
    driver._publish_runtime_status = lambda **_kwargs: None

    async def scenario():
        run_task = asyncio.create_task(driver.run())
        # w1 crashes immediately; the replacement must finish the first task.
        await _wait_until(
            lambda: driver.stats["completed"] == 1 and driver._replacement_count == 1
        )
        assert "w1" in driver._quarantined_workers
        assert driver._replacement_count == 1
        assert driver.stats["completed"] == 1
        # Work enqueued AFTER the crash must be picked up by the replacement.
        queue.enqueue("post-crash task", max_attempts=1)
        await _wait_until(lambda: driver.stats["completed"] == 2)
        assert driver.stats["completed"] == 2
        assert not run_task.done()
        driver.stop()
        await asyncio.wait_for(run_task, timeout=2)
        return driver

    driver = asyncio.run(scenario())
    assert queue.list_states()["completed"] == 2
    assert driver.stats["quarantined_workers"] == ["w1"]


def test_cancellation_is_never_treated_as_worker_crash():
    async def scenario():
        started = asyncio.Event()

        class BlockingDriver(QueueDriver):
            async def _worker(self, worker_id):
                started.set()
                await asyncio.Event().wait()

        driver = BlockingDriver(queue=object())
        worker = asyncio.ensure_future(driver._supervised_worker("w1"))
        await started.wait()
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        return driver

    driver = asyncio.run(scenario())
    assert driver.stats["worker_restarts"] == 0
    assert not driver._worker_failures


def test_stop_during_task_exits_cleanly_without_quarantine(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "q.db"))
    queue.enqueue("slow task", max_attempts=1)

    class Driver(QueueDriver):
        def _link_queue_task(self, task, worker_id="queue-worker"):
            return {}

    driver = Driver(
        kernel=_Kernel(_Loop(delay=0.15)), queue=queue, workers=1,
        idle_sleep=0.005, control_store=_NoopControlStore(),
    )
    driver._publish_runtime_status = lambda **_kwargs: None

    async def scenario():
        run_task = asyncio.create_task(driver.run())
        await _wait_until(lambda: driver._active >= 1)
        driver.stop()
        await asyncio.wait_for(run_task, timeout=3)
        return driver

    driver = asyncio.run(scenario())
    assert driver.stats["completed"] == 1
    assert driver.stats["worker_restarts"] == 0
    assert not driver._quarantined_workers
    assert queue.list_states()["completed"] == 1