import time

import pytest

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


def test_durable_task_errors_are_redacted_and_bounded(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "redacted-errors.db"))
    task_id = queue.enqueue("error retention")
    leased = queue.lease(timeout_sec=30, worker_id="worker")
    assert leased and leased["id"] == task_id

    secret_error = "provider failed with sk-live-queue at C:\\private\\repo"
    assert queue.fail(task_id, secret_error, lease_token=leased["lease_token"])
    stored = queue.get(task_id)["error"]
    assert "sk-live-queue" not in stored
    assert "***REDACTED***" in stored


def test_durable_task_results_are_redacted_without_losing_json_shape(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "redacted-results.db"))
    task_id = queue.enqueue("result retention")
    leased = queue.lease(timeout_sec=30, worker_id="worker")
    assert leased and leased["id"] == task_id

    result = {
        "message": "ok",
        "provider": {"authorization": "Bearer sk-result-secret-value"},
        "items": ["safe", "api_key=another-secret-value"],
    }
    assert queue.complete(task_id, result, lease_token=leased["lease_token"])
    stored = queue.get(task_id)["result"]
    assert "sk-result-secret-value" not in stored
    assert "another-secret-value" not in stored
    assert "***REDACTED***" in stored
    assert '"message": "ok"' in stored


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


def test_expired_worker_cannot_renew_lease_before_reaper(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "expired-renew.db"))
    task_id = queue.enqueue("lease renewal race", max_attempts=3)
    stale = queue.lease(timeout_sec=0, worker_id="stale")
    assert stale and stale["lease_token"]

    assert queue.ack_lease(task_id, stale["lease_token"], timeout_sec=30) is False
    assert queue.requeue_expired_leases() == 1
    current = queue.lease(timeout_sec=30, worker_id="current")
    assert current and current["lease_token"] != stale["lease_token"]


def test_reaper_does_not_overwrite_renewed_lease(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "renew-race.db"))
    task_id = queue.enqueue("renew race", max_attempts=3)
    leased = queue.lease(timeout_sec=30, worker_id="worker")
    assert leased and leased["lease_token"]

    # Renewal changes the lease deadline after a reaper's conceptual snapshot.
    assert queue.ack_lease(task_id, leased["lease_token"], timeout_sec=30) is True
    assert queue.requeue_expired_leases() == 0

    current = queue.get(task_id)
    assert current["state"] == "leased"
    assert current["lease_token"] == leased["lease_token"]
    assert queue.complete(task_id, "current result", lease_token=leased["lease_token"]) is True


def test_enqueue_idempotency_key_returns_one_durable_task(tmp_path):
    db = str(tmp_path / "dedupe.db")
    first = TaskQueue(db_path=db)
    first_id = first.enqueue(
        "same milestone",
        idempotency_key="mission:m1:milestone:0:revision:r0",
    )
    second_id = TaskQueue(db_path=db).enqueue(
        "same milestone",
        idempotency_key="mission:m1:milestone:0:revision:r0",
    )
    assert second_id == first_id
    assert len(TaskQueue(db_path=db).list_unfinished()) == 1


def test_corrupted_payload_is_marked_not_silently_emptied(tmp_path):
    """Regression: a corrupt payload must stay diagnosable (P12)."""
    row = {"payload": "{not valid json", "id": "t1"}
    parsed = TaskQueue._row_to_dict(row)
    payload = parsed["payload"]
    assert payload.get("_payload_error"), payload
    assert "not valid json" in str(payload.get("_raw_payload"))


def test_corrupted_payload_driver_fails_with_clear_reason(tmp_path):
    """Regression: the driver explains corruption instead of 'no task_desc' (P12)."""
    import asyncio

    from queue.driver import QueueDriver

    class FakeQueue:
        db_path = str(tmp_path / "tasks.db")

    driver = QueueDriver(queue=FakeQueue())  # type: ignore[arg-type]
    task = {"payload": {"_payload_error": "invalid json payload: Expecting value", "_raw_payload": "{"}}
    with pytest.raises(ValueError, match="corrupted"):
        asyncio.run(driver.run_task(task))
