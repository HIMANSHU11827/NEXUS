import time

from queue.store import STATE_RETRYING, TaskQueue


def test_retry_backoff_is_respected(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "tasks.db"))
    task_id = queue.enqueue("retry me", max_attempts=3)
    leased = queue.lease(timeout_sec=30, worker_id="test")
    assert leased and leased["id"] == task_id

    assert queue.fail(task_id, "temporary failure", requeue_after=0.2)
    assert queue.get(task_id)["state"] == STATE_RETRYING
    assert queue.lease(timeout_sec=30, worker_id="test") is None
    assert queue.pending_count() == 0

    time.sleep(0.25)
    retry = queue.lease(timeout_sec=30, worker_id="test")
    assert retry and retry["id"] == task_id


def test_retrying_tasks_survive_queue_reopen(tmp_path):
    db = str(tmp_path / "restart.db")
    first = TaskQueue(db_path=db)
    task_id = first.enqueue("survive restart", max_attempts=2)
    assert first.lease(timeout_sec=30, worker_id="test")["id"] == task_id
    assert first.fail(task_id, "retry", requeue_after=0)

    reopened = TaskQueue(db_path=db)
    retry = reopened.lease(timeout_sec=30, worker_id="reopened")
    assert retry and retry["id"] == task_id


def test_expired_worker_cannot_overwrite_new_lease(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "lease-race.db"))
    task_id = queue.enqueue("lease race", max_attempts=3)
    stale = queue.lease(timeout_sec=0, worker_id="stale")
    assert stale and stale["lease_token"]
    assert queue.requeue_expired_leases() == 1
    current = queue.lease(timeout_sec=30, worker_id="current")
    assert current and current["lease_token"] != stale["lease_token"]

    assert queue.complete(task_id, "stale result", lease_token=stale["lease_token"]) is False
    assert queue.complete(task_id, "current result", lease_token=current["lease_token"]) is True
    assert queue.get(task_id)["result"] == '"current result"'
