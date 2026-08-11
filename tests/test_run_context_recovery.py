from nexus.run_context import (
    RunContext,
    load_run_context,
    recover_orphaned_runs,
    start_run_context,
)


def test_terminal_run_context_heartbeat_does_not_reopen_lease(tmp_path):
    context = start_run_context(
        root=str(tmp_path), session_id="heartbeat", run_id="terminal",
        prompt="done", lease_seconds=10,
    )
    context.finish("completed", "run.completed")
    before = context.to_dict()
    context.heartbeat(lease_seconds=999)
    after = context.to_dict()
    assert after["status"] == "completed"
    assert after["lease_expires_at"] is None
    assert after["updated_at"] == before["updated_at"]


def test_stale_heartbeat_cannot_reopen_a_terminal_run(tmp_path):
    live = start_run_context(
        root=str(tmp_path), session_id="race", run_id="run-1",
        prompt="work", lease_seconds=60,
    )
    stale = RunContext(**{
        key: value for key, value in live.to_dict().items()
        if key in RunContext.__dataclass_fields__
    })
    assert live.finish("completed", "run.completed") is True

    assert stale.heartbeat(lease_seconds=999) is False
    saved = load_run_context(str(tmp_path), "race", "run-1")
    assert saved["status"] == "completed"
    assert saved["lease_expires_at"] is None


def test_stale_owner_cannot_finish_or_heartbeat_live_run(tmp_path):
    live = start_run_context(
        root=str(tmp_path), session_id="owner", run_id="run-1",
        prompt="work", lease_seconds=60,
    )
    stale = RunContext(**{
        key: value for key, value in live.to_dict().items()
        if key in RunContext.__dataclass_fields__
    })
    stale.owner_process_id = live.owner_process_id + 100000

    assert stale.heartbeat(lease_seconds=999) is False
    assert stale.finish("failed", "run.failed") is False
    assert load_run_context(str(tmp_path), "owner", "run-1")["status"] == "running"
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
