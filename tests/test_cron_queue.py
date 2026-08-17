from queues.store import STATE_QUEUED, TaskQueue


def test_cron_definition_and_history_survive_queue_reopen(tmp_path):
    db = str(tmp_path / "cron.db")
    queue = TaskQueue(db_path=db)
    job = queue.create_cron_job("cron_a", "Nightly", "run nightly", 60, next_run_at=10.0)
    assert job["id"] == "cron_a"
    manual = queue.enqueue_cron_run("cron_a", trigger="manual", now=20.0)
    assert manual and manual["task_id"]
    queue.update_cron_run(manual["run_id"], "completed")

    reopened = TaskQueue(db_path=db)
    assert reopened.get_cron_job("cron_a")["name"] == "Nightly"
    assert reopened.list_cron_runs("cron_a")[0]["status"] == "completed"


def test_due_cron_slots_materialize_once_with_deterministic_queue_key(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "cron.db"))
    queue.create_cron_job("cron_due", "Due", "do it", 1, next_run_at=100.0)
    first = queue.enqueue_due_cron_runs(now=100.0)
    second = queue.enqueue_due_cron_runs(now=100.0)
    assert len(first) == 1
    assert second == []
    task = queue.get(first[0]["task_id"])
    assert task["state"] == STATE_QUEUED
    assert task["payload"]["meta"]["cron_run_id"] == first[0]["run_id"]


def test_disabling_cron_preserves_runs_and_stops_future_materialization(tmp_path):
    queue = TaskQueue(db_path=str(tmp_path / "cron.db"))
    queue.create_cron_job("cron_off", "Off", "do it", 1, next_run_at=100.0)
    run = queue.enqueue_cron_run("cron_off", trigger="manual", now=100.0)
    assert run
    assert queue.delete_cron_job("cron_off") is True
    assert queue.get_cron_job("cron_off")["enabled"] is False
    assert len(queue.list_cron_runs("cron_off")) == 1
    assert queue.enqueue_due_cron_runs(now=1000.0) == []
