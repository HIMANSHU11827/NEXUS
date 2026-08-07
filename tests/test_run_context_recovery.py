from nexus.run_context import (
    load_run_context,
    recover_orphaned_runs,
    start_run_context,
)
from nexus.work_items import create_work_item, load_work_item, project_work_item_event


def test_orphaned_run_recovery_is_durable_idempotent_and_rejects_late_events(tmp_path):
    start_run_context(
        root=str(tmp_path), session_id="recovery", run_id="run-a",
        task_id="task-a", prompt="recover me",
    )
    create_work_item(
        root=str(tmp_path), session_id="recovery", task_id="task-a",
        title="Recover me", status="approved", run_id="run-a",
    )
    event_dir = tmp_path / "events"
    first = recover_orphaned_runs(
        root=str(tmp_path), session_id="recovery", event_log_dir=str(event_dir)
    )
    assert len(first) == 1
    assert load_run_context(str(tmp_path), "recovery", "run-a")["status"] == "failed"
    assert load_work_item(str(tmp_path), "recovery", "task-a").status == "failed"
    context_timestamp = load_run_context(str(tmp_path), "recovery", "run-a")["updated_at"]
    second = recover_orphaned_runs(
        root=str(tmp_path), session_id="recovery", event_log_dir=str(event_dir)
    )
    assert second == []
    assert load_run_context(str(tmp_path), "recovery", "run-a")["updated_at"] == context_timestamp
    assert project_work_item_event(
        root=str(tmp_path), session_id="recovery",
        event={
            "event_id": "late-complete", "event_type": "run.completed",
            "task_id": "task-a", "run_id": "run-a", "status": "success",
        },
    ) is None
    assert load_work_item(str(tmp_path), "recovery", "task-a").status == "failed"


def test_recovery_does_not_retire_a_live_leased_run(tmp_path):
    start_run_context(
        root=str(tmp_path), session_id="live", run_id="run-live", prompt="still working",
        lease_seconds=60,
    )
    assert recover_orphaned_runs(root=str(tmp_path), session_id="live", event_log_dir=str(tmp_path / "events")) == []
    context = load_run_context(str(tmp_path), "live", "run-live")
    assert context is not None
    assert context["status"] == "running"
    assert context["lease_expires_at"] > context["updated_at"]
