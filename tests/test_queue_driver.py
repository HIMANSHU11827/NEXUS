import asyncio
import copy
import os
import sqlite3
import threading

import pytest

from queue.driver import QueueDriver
from queue.mission import Mission, MissionRunner, Milestone
from queue.store import STATE_CANCELLED, TaskQueue


class _MemoryQueue(TaskQueue):
    uri = "file:nexus_queue_regression?mode=memory&cache=shared"
    keeper = sqlite3.connect(uri, uri=True, check_same_thread=False)
    keeper.row_factory = sqlite3.Row

    def _connect(self):
        conn = sqlite3.connect(self.uri, uri=True, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def _memory_queue():
    queue = _MemoryQueue.__new__(_MemoryQueue)
    queue.db_path = ""
    queue.default_max_attempts = 3
    queue._lock = threading.Lock()
    queue._init_db()
    with queue._lock:
        conn = queue._connect()
        try:
            conn.execute("DELETE FROM tasks")
            conn.commit()
        finally:
            conn.close()
    return queue


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


class _SandboxLoop:
    def __init__(self):
        self.tiers = []

    async def stream_run(self, *_args, **_kwargs):
        if False:
            yield {}

    def _set_sandbox_tier(self, tier):
        self.tiers.append(tier)


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
    assert loop.received[0] == "build it"
    assert loop.received[1]["model"] == "local-model"
    assert loop.received[1]["voice_mode"] is False
    assert loop.received[1]["idempotency_key"].startswith("queue:")
    assert loop.received[1]["idempotency_key"].endswith(":1")


def test_queue_driver_does_not_mark_failed_turn_complete():
    driver = QueueDriver(kernel=_Kernel(_Loop(success=False)), queue=object())
    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(driver.run_task({"id": 1, "payload": {"task_desc": "try"}}))


def test_queue_driver_rejects_a_truncated_stream():
    class TruncatedLoop:
        async def stream_run(self, prompt, **kwargs):
            yield {"type": "content", "data": "partial"}

    driver = QueueDriver(kernel=_Kernel(TruncatedLoop()), queue=object())
    with pytest.raises(RuntimeError, match="without a terminal result"):
        asyncio.run(driver.run_task({"id": 1, "payload": {"task_desc": "try"}}))


def test_queue_driver_resumes_retry_from_durable_context():
    loop = _Loop()
    driver = QueueDriver(kernel=_Kernel(loop), queue=object())
    asyncio.run(driver.run_task({
        "id": 1,
        "attempts": 2,
        "payload": {
            "task_desc": "finish the migration",
            "meta": {"session_id": "session-7", "resume_context": "phase 2 is unfinished"},
        },
    }))
    assert "[NEXUS_RESUME_CONTEXT]" in loop.received[0]
    assert "phase 2 is unfinished" in loop.received[0]


def test_queue_driver_uses_isolated_queue_root_with_a_kernel():
    queue_root = os.path.abspath(os.path.join(".tmp", "queue-root-test"))
    os.makedirs(queue_root, exist_ok=True)
    queue = TaskQueue(db_path=os.path.join(queue_root, "queue.sqlite"), root=queue_root)
    driver = QueueDriver(kernel=_Kernel(_Loop()), queue=queue)
    assert driver.root == queue_root
    assert driver.control_store.root == queue_root


def test_queue_driver_discards_result_after_canonical_lease_loss():
    class SlowLoop:
        async def stream_run(self, *_args, **_kwargs):
            await asyncio.sleep(0.4)
            yield {"type": "done", "data": {"success": True, "response": "late"}}

    class QueueLease:
        def ack_lease(self, *_args, **_kwargs):
            return True

    class LostControlStore:
        def renew_run(self, **_kwargs):
            return False

    driver = QueueDriver(
        kernel=_Kernel(SlowLoop()), queue=QueueLease(),
        control_store=LostControlStore(), lease_timeout=1,
    )
    with pytest.raises(RuntimeError, match="lease lost before completion"):
        asyncio.run(driver._run_with_heartbeat(
            {"payload": {"task_desc": "continue", "meta": {"control_run_id": "run", "control_lease_token": "token"}}},
            task_id=1, lease_token="queue-token", leased_at=0,
        ))


def test_autonomous_driver_enforces_normal_sandbox_by_default(monkeypatch):
    loop = _SandboxLoop()
    driver = QueueDriver(kernel=_Kernel(loop), queue=object())
    monkeypatch.delenv("NEXUS_ALLOW_UNSANDBOXED_AUTONOMOUS", raising=False)
    assert driver._build_loop() is loop
    assert loop.tiers == ["normal"]


def test_queue_driver_supervises_unexpected_worker_crash():
    class Driver(QueueDriver):
        def __init__(self):
            super().__init__(queue=object(), idle_sleep=0.001)
            self.calls = 0

        async def _worker(self, worker_id):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated worker crash")
            self.stop()

    async def scenario():
        driver = Driver()
        task = asyncio.create_task(driver.run())
        await asyncio.wait_for(task, timeout=2)
        return driver

    driver = asyncio.run(scenario())
    assert driver.calls >= 2
    assert driver.stats["worker_restarts"] == 1


def test_enqueue_once_is_idempotent():
    queue = _memory_queue()
    first = queue.enqueue_once("same", idempotency_key="mission:m:0:r0")
    second = queue.enqueue_once("same", idempotency_key="mission:m:0:r0")
    assert first == second
    assert queue.pending_count() == 1


def test_lease_is_single_claim_across_queue_instances():
    queue = _memory_queue()
    queue.enqueue("one")
    workers = [_MemoryQueue.__new__(_MemoryQueue) for _ in range(8)]
    for worker in workers:
        worker.db_path = ""
        worker.default_max_attempts = 3
        worker._lock = threading.Lock()
    results = []
    threads = [threading.Thread(target=lambda q: results.append(q.lease()), args=(q,)) for q in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [row for row in results if row] == [row for row in results if row][:1]


class _MissionQueue:
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()

    def enqueue_once(self, task_desc, *, idempotency_key, **meta):
        with self.lock:
            if idempotency_key not in self.rows:
                self.rows[idempotency_key] = (task_desc, meta)
            return len(self.rows)


class _StaleMissionStore:
    def __init__(self, mission, barrier):
        self.mission = mission
        self.barrier = barrier

    def active(self):
        self.barrier.wait()
        return [copy.deepcopy(self.mission)]

    def save(self, mission):
        self.mission = copy.deepcopy(mission)

    def get(self, _mission_id):
        return copy.deepcopy(self.mission)


def test_concurrent_mission_runners_share_one_idempotent_enqueue():
    mission = Mission(
        id="m", goal="goal",
        milestones=[Milestone(index=0, task_desc="first")],
    )
    queue = _MissionQueue()
    barrier = threading.Barrier(2)
    runners = [
        MissionRunner(queue=queue, store=_StaleMissionStore(mission, barrier)),
        MissionRunner(queue=queue, store=_StaleMissionStore(mission, barrier)),
    ]
    threads = [threading.Thread(target=runner.advance) for runner in runners]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(queue.rows) == 1


def test_cancelled_lease_is_not_requeued():
    queue = _memory_queue()
    task_id = queue.enqueue("side effect", max_attempts=3)
    leased = queue.lease(timeout_sec=30, worker_id="test")
    assert leased and leased["id"] == task_id
    assert queue.cancel(task_id, "forced shutdown", leased["lease_token"])
    assert queue.get(task_id)["state"] == STATE_CANCELLED
    assert queue.pending_count() == 0
