import asyncio
import copy
import os
import sqlite3
import threading
import time

import pytest

from queue.driver import LeaseOwnershipError, QueueDriver
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
    assert callable(loop.received[1]["execution_fence"])
    assert loop.received[1]["execution_fence"]() is True


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
    cancelled = asyncio.Event()

    class SlowLoop:
        async def stream_run(self, *_args, **_kwargs):
            try:
                await asyncio.sleep(5)
                yield {"type": "done", "data": {"success": True, "response": "late"}}
            except asyncio.CancelledError:
                cancelled.set()
                raise

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
    leased_at = time.time()
    with pytest.raises(LeaseOwnershipError, match="no longer owned"):
        asyncio.run(driver._run_with_heartbeat(
            {"payload": {"task_desc": "continue", "meta": {"control_run_id": "run", "control_lease_token": "token"}}},
            task_id=1, lease_token="queue-token", leased_at=leased_at,
        ))
    assert cancelled.is_set()


def test_heartbeat_exceptions_self_fence_before_lease_expiry():
    execution_started = asyncio.Event()
    execution_cancelled = asyncio.Event()

    class SlowLoop:
        async def stream_run(self, *_args, **_kwargs):
            execution_started.set()
            try:
                await asyncio.sleep(5)
                yield {"type": "done", "data": {"success": True, "response": "late"}}
            except asyncio.CancelledError:
                execution_cancelled.set()
                raise

    class BrokenRenewalQueue:
        def __init__(self):
            self.renewals = []

        def ack_lease(self, *_args, **_kwargs):
            self.renewals.append(time.time())
            raise sqlite3.OperationalError("database unavailable")

    queue = BrokenRenewalQueue()
    driver = QueueDriver(kernel=_Kernel(SlowLoop()), queue=queue, lease_timeout=1)
    driver.cancel_timeout = 0.2
    leased_at = time.time()

    with pytest.raises(LeaseOwnershipError) as caught:
        asyncio.run(driver._run_with_heartbeat(
            {
                "leased_until": leased_at + 1.0,
                "payload": {"task_desc": "continue", "meta": {}},
            },
            task_id=7,
            lease_token="queue-token",
            leased_at=leased_at,
        ))

    assert caught.value.uncertain is True
    assert execution_started.is_set()
    assert execution_cancelled.is_set()
    assert queue.renewals
    assert time.time() < leased_at + 1.0


def test_cancellation_resistant_lease_loss_is_always_uncertain():
    release = asyncio.Event()
    cancellation_seen = asyncio.Event()

    class ResistantLoop:
        async def stream_run(self, *_args, **_kwargs):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release.wait()
            yield {"type": "done", "data": {"success": True, "response": "late"}}

    class LostLeaseQueue:
        def __init__(self):
            self.quarantined = []

        def ack_lease(self, *_args, **_kwargs):
            return False

        def quarantine_uncertain(self, task_id, reason):
            self.quarantined.append((task_id, reason))
            return True

    async def scenario():
        queue = LostLeaseQueue()
        driver = QueueDriver(
            kernel=_Kernel(ResistantLoop()), queue=queue, lease_timeout=1,
        )
        driver.cancel_timeout = 0.05
        leased_at = time.time()
        with pytest.raises(LeaseOwnershipError) as caught:
            await driver._run_with_heartbeat(
                {"leased_until": leased_at + 1, "payload": {"task_desc": "work", "meta": {}}},
                task_id=8, lease_token="old-token", leased_at=leased_at,
            )
        assert caught.value.uncertain is True
        assert caught.value.quarantined is True
        assert queue.quarantined and queue.quarantined[0][0] == 8
        assert cancellation_seen.is_set()
        release.set()
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_uncertain_quarantine_invalidates_a_replacement_lease(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "uncertain.db"))
    task_id = queue.enqueue("effectful work")
    first = queue.lease(timeout_sec=1, worker_id="first")
    assert first and first["id"] == task_id
    # Simulate expiry followed by a replacement owner.
    with queue._lock:
        connection = queue._connect()
        try:
            connection.execute(
                "UPDATE tasks SET leased_until = ? WHERE id = ?", (time.time() - 1, task_id)
            )
            connection.commit()
        finally:
            connection.close()
    queue.requeue_expired_leases()
    replacement = queue.lease(timeout_sec=30, worker_id="replacement")
    assert replacement and replacement["id"] == task_id
    assert queue.owns_lease(task_id, replacement["lease_token"]) is True

    assert queue.quarantine_uncertain(task_id, "prior effect may still be running") is True
    record = queue.get(task_id)
    assert record["state"] == STATE_CANCELLED
    assert queue.owns_lease(task_id, replacement["lease_token"]) is False
    assert queue.complete(task_id, "replacement result", replacement["lease_token"]) is False


def test_uncertain_lease_fence_is_cancelled_without_automatic_replay():
    class SlowLoop:
        async def stream_run(self, *_args, **_kwargs):
            await asyncio.sleep(5)
            yield {"type": "done", "data": {"success": True, "response": "late"}}

    class Queue:
        def __init__(self):
            self.leased = False
            self.cancelled = []
            self.failed = []

        def requeue_expired_leases(self):
            return 0

        def lease(self, **_kwargs):
            if self.leased:
                return None
            self.leased = True
            now = time.time()
            # The lease's safety deadline (leased_until - fence_margin) is
            # deliberately already in the past: the heartbeat fences on its
            # very first iteration instead of after ~0.75s of wall-clock
            # sleeps, so this test never depends on real-time timing or the
            # wait_for() budget below. The renewal-retry timing path is
            # covered deterministically by
            # test_heartbeat_exceptions_self_fence_before_lease_expiry.
            return {
                "id": 9,
                "attempts": 1,
                "max_attempts": 3,
                "lease_token": "token",
                "leased_until": now + 0.05,
                "payload": {"task_desc": "one attempt", "meta": {}},
            }

        def ack_lease(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("database unavailable")

        def cancel(self, task_id, reason, lease_token=None):
            self.cancelled.append((task_id, reason, lease_token))
            return True

        def fail(self, *args, **kwargs):
            self.failed.append((args, kwargs))
            return True

    class Driver(QueueDriver):
        def _link_queue_task(self, task, worker_id="queue-worker"):
            return {}

    async def scenario():
        queue = Queue()
        driver = Driver(
            kernel=_Kernel(SlowLoop()),
            queue=queue,
            lease_timeout=1,
            idle_sleep=0.01,
        )
        driver._publish_runtime_status = lambda **_kwargs: None
        original_cancel = queue.cancel

        def cancel_and_stop(*args, **kwargs):
            result = original_cancel(*args, **kwargs)
            driver.stop()
            return result

        queue.cancel = cancel_and_stop
        # The fence now fires on the heartbeat's first iteration, so this
        # budget only needs to cover worker startup/teardown (which touches
        # the real ControlStore). 5s leaves generous headroom on loaded CI.
        await asyncio.wait_for(driver.run(), timeout=5)
        return driver, queue

    driver, queue = asyncio.run(scenario())
    assert driver.stats["leased"] == 1
    assert len(queue.cancelled) == 1
    assert "uncertain outcome after lease fencing" in queue.cancelled[0][1]
    assert queue.failed == []


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


def test_queue_worker_crash_loop_is_quarantined(monkeypatch):
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_CRASH_LIMIT", "2")
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_CRASH_WINDOW", "60")
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_REPLACEMENTS", "0")

    class Driver(QueueDriver):
        async def _worker(self, worker_id):
            raise RuntimeError("persistent worker crash")

    driver = Driver(queue=object(), idle_sleep=0.001)
    driver._publish_runtime_status = lambda **_kwargs: None

    with pytest.raises(RuntimeError, match="all queue workers quarantined"):
        asyncio.run(driver.run())
    assert "w1" in driver._quarantined_workers
    assert driver.stats["quarantined_workers"] == ["w1"]


def test_multi_worker_quarantine_isolates_the_crashed_worker(monkeypatch):
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_CRASH_LIMIT", "1")
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_CRASH_WINDOW", "60")
    monkeypatch.setenv("NEXUS_QUEUE_WORKER_REPLACEMENTS", "0")
    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()
    sibling_loops = {"n": 0}

    class Driver(QueueDriver):
        async def _worker(self, worker_id):
            if worker_id == "w1":
                raise RuntimeError("quarantine this worker")
            sibling_started.set()
            sibling_loops["n"] += 1
            while not self._stopping:
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    sibling_cancelled.set()
                    raise

    async def scenario():
        driver = Driver(queue=object(), workers=2, idle_sleep=0.001)
        driver.cancel_timeout = 0.2
        driver._publish_runtime_status = lambda **_kwargs: None
        run_task = asyncio.create_task(driver.run())
        await sibling_started.wait()
        for _ in range(200):
            if "w1" in driver._quarantined_workers:
                break
            await asyncio.sleep(0.01)
        # The crash-limit quarantine must not cancel the healthy sibling.
        assert "w1" in driver._quarantined_workers
        assert driver.stats["quarantined_workers"] == ["w1"]
        assert not sibling_cancelled.is_set()
        assert driver._stopping is False
        assert not run_task.done()
        driver.stop()
        await asyncio.wait_for(run_task, timeout=2)
        return driver

    driver = asyncio.run(scenario())
    assert not sibling_cancelled.is_set()
    assert driver._stopping is True
    assert sibling_loops["n"] >= 1


def test_worker_cleanup_is_bounded_when_cancellation_is_ignored():
    async def scenario():
        release = asyncio.Event()
        cancellation_seen = asyncio.Event()

        async def resistant_worker():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release.wait()

        driver = QueueDriver(queue=object())
        driver.cancel_timeout = 0.05
        worker = asyncio.create_task(resistant_worker())
        await asyncio.sleep(0)
        driver._tasks = [worker]
        started = time.monotonic()
        await driver._cancel_workers_bounded()
        elapsed = time.monotonic() - started
        assert cancellation_seen.is_set()
        assert elapsed < 0.25
        assert driver._tasks == []
        assert not worker.done()
        release.set()
        await asyncio.wait_for(worker, timeout=0.5)

    asyncio.run(scenario())


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
