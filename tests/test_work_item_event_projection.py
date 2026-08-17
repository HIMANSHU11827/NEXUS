import apps.api
import json
import subprocess
import sys
import time

from nexus.work_items import (
    create_work_item,
    load_work_item,
    project_work_item_event,
    reconcile_checklist_work_item,
    replay_work_item_event_log,
)


def _event(event_type, *, event_id, task_id="task-a", run_id="run-a"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "task_id": task_id,
        "run_id": run_id,
        "status": {
            "run.started": "running",
            "run.completed": "success",
            "run.failed": "failed",
            "run.timed_out": "failed",
            "run.cancelled": "cancelled",
        }[event_type],
    }


def test_canonical_run_events_project_one_item_and_replay_is_idempotent(tmp_path):
    item = create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="task-a",
        title="Execute task", status="approved",
    )

    started = project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.started", event_id="evt-start"),
    )
    assert started.status == "running"
    assert started.run_id == "run-a"

    completed = project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.completed", event_id="evt-complete"),
    )
    assert completed.status == "applied"
    version = completed.version
    updated_at = completed.updated_at

    replayed = project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.completed", event_id="evt-complete"),
    )
    assert replayed.status == "applied"
    assert replayed.version == version
    assert replayed.updated_at == updated_at
    assert load_work_item(str(tmp_path), "session-a", item.task_id).status == "applied"


def test_failed_timeout_and_cancelled_events_project_from_running(tmp_path):
    for event_type, expected in (("run.failed", "failed"), ("run.timed_out", "failed"), ("run.cancelled", "cancelled")):
        task_id = f"task-{event_type.replace('.', '-')}"
        create_work_item(
            root=str(tmp_path), session_id="session-a", task_id=task_id,
            title=expected, status="approved",
        )
        project_work_item_event(
            root=str(tmp_path), session_id="session-a",
            event=_event("run.started", event_id=f"start-{expected}", task_id=task_id),
        )
        result = project_work_item_event(
            root=str(tmp_path), session_id="session-a",
            event=_event(event_type, event_id=f"terminal-{expected}", task_id=task_id),
        )
        assert result.status == expected


def test_run_started_bridges_planned_checklist_item_before_terminal_projection(tmp_path):
    create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="task-planned",
        title="Planned task", status="planned",
    )

    started = project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.started", event_id="planned-start", task_id="task-planned"),
    )
    assert started.status == "running"
    assert started.run_id == "run-a"

    completed = project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.completed", event_id="planned-complete", task_id="task-planned"),
    )
    assert completed.status == "applied"


def test_server_append_projects_public_event_without_recursive_event_write(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "events"))
    server._WORK_EVENT_SEQUENCES.clear()
    server._WORK_EVENT_CACHE.clear()
    create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="task-a",
        title="Server projection", status="approved",
    )

    event = server.append_work_event("session-a", _event("run.started", event_id="server-start"))
    assert event["type"] == "run.started"
    item = load_work_item(str(tmp_path), "session-a", "task-a")
    assert item.status == "running"
    assert len(server.list_work_events("session-a", limit=10)) == 1


def test_restart_replay_recovers_projection_and_skips_partial_lines(tmp_path):
    create_work_item(
        root=str(tmp_path), session_id="restart", task_id="task-a",
        title="Recover me", status="approved",
    )
    log = tmp_path / "events.jsonl"
    records = [
        {**_event("run.started", event_id="restart-start"), "sequence": 1},
        {**_event("run.completed", event_id="restart-complete"), "sequence": 2},
    ]
    with log.open("w", encoding="utf-8") as handle:
        handle.write("{\"event_type\":\"run.started\"\n")
        for record in records:
            handle.write(json.dumps(record) + "\n")

    assert replay_work_item_event_log(
        root=str(tmp_path), session_id="restart", event_log_path=str(log)
    ) == 2
    recovered = load_work_item(str(tmp_path), "restart", "task-a")
    assert recovered.status == "applied"
    version = recovered.version
    updated_at = recovered.updated_at

    # A fresh process replay is a durable no-op because the event ledger is
    # persisted inside the WorkItem metadata.
    assert replay_work_item_event_log(
        root=str(tmp_path), session_id="restart", event_log_path=str(log)
    ) == 2
    replayed = load_work_item(str(tmp_path), "restart", "task-a")
    assert replayed.version == version
    assert replayed.updated_at == updated_at


def test_projection_ignores_events_without_explicit_task_identity(tmp_path):
    create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="task-a",
        title="Unidentified", status="approved",
    )
    assert project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.started", event_id="missing-task", task_id=""),
    ) is None
    assert load_work_item(str(tmp_path), "session-a", "task-a").status == "approved"


def test_same_state_replay_is_a_true_no_op(tmp_path):
    create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="task-a",
        title="No drift", status="approved",
    )
    project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.started", event_id="start"),
    )
    before = load_work_item(str(tmp_path), "session-a", "task-a")
    time.sleep(0.01)
    replay = project_work_item_event(
        root=str(tmp_path), session_id="session-a",
        event=_event("run.started", event_id="late-duplicate"),
    )
    assert replay.to_dict() == before.to_dict()


def test_legacy_server_append_projects_lifecycle_event(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "events"))
    server._WORK_EVENT_SEQUENCES.clear()
    server._WORK_EVENT_CACHE.clear()
    create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="task-a",
        title="Legacy append", status="approved",
    )

    server._append_work_event("session-a", _event("run.started", event_id="legacy-start"))
    item = load_work_item(str(tmp_path), "session-a", "task-a")
    assert item.status == "running"
    assert item.run_id == "run-a"


def test_reopening_failed_or_cancelled_item_clears_run_and_rejects_delayed_events(tmp_path):
    for index, terminal in enumerate(("run.failed", "run.cancelled")):
        task_id = f"retry-{index}"
        create_work_item(
            root=str(tmp_path), session_id="retry-session", task_id=task_id,
            title="Retry me", status="approved",
        )
        project_work_item_event(
            root=str(tmp_path), session_id="retry-session",
            event=_event("run.started", event_id=f"start-{index}", task_id=task_id, run_id=f"old-{index}"),
        )
        project_work_item_event(
            root=str(tmp_path), session_id="retry-session",
            event=_event(terminal, event_id=f"terminal-{index}", task_id=task_id, run_id=f"old-{index}"),
        )
        reopened = reconcile_checklist_work_item(
            root=str(tmp_path), session_id="retry-session", task_id=task_id,
            title="Retry me", checklist_status="pending",
        )
        assert reopened.status == "planned"
        assert reopened.run_id == ""

        delayed = project_work_item_event(
            root=str(tmp_path), session_id="retry-session",
            event=_event(terminal, event_id=f"late-{index}", task_id=task_id, run_id=f"old-{index}"),
        )
        assert delayed is None
        assert load_work_item(str(tmp_path), "retry-session", task_id).status == "planned"


def test_reconcile_is_cross_process_serialized_and_leaves_valid_json(tmp_path):
    script = """
import sys
from nexus.work_items import reconcile_checklist_work_item
root, session, task = sys.argv[1:]
for index in range(20):
    reconcile_checklist_work_item(
        root=root, session_id=session, task_id=task,
        title=f'worker-{index}',
        checklist_status='in_progress' if index % 2 else 'pending',
    )
"""
    processes = [
        subprocess.Popen([sys.executable, "-c", script, str(tmp_path), "parallel", "task-a"], cwd=str(tmp_path))
        for _ in range(2)
    ]
    assert all(process.wait(timeout=20) == 0 for process in processes)
    item = load_work_item(str(tmp_path), "parallel", "task-a")
    assert item is not None
    assert item.status in {"planned", "running"}
    assert item.version >= 1


def test_bounded_event_id_cache_does_not_reopen_a_retried_item(tmp_path):
    create_work_item(
        root=str(tmp_path), session_id="ledger", task_id="task-a",
        title="Many retries", status="approved",
    )
    for index in range(300):
        run_id = f"run-{index}"
        project_work_item_event(
            root=str(tmp_path), session_id="ledger",
            event=_event("run.started", event_id=f"start-{index}", run_id=run_id),
        )
        project_work_item_event(
            root=str(tmp_path), session_id="ledger",
            event=_event("run.failed", event_id=f"failed-{index}", run_id=run_id),
        )
        reconcile_checklist_work_item(
            root=str(tmp_path), session_id="ledger", task_id="task-a",
            title="Many retries", checklist_status="pending",
        )
    item = load_work_item(str(tmp_path), "ledger", "task-a")
    assert item.status == "planned"
    assert len(item.metadata["_projected_work_event_ids"]) <= 256
    assert len(item.metadata["_retired_run_ids"]) == 300
    assert project_work_item_event(
        root=str(tmp_path), session_id="ledger",
        event=_event("run.failed", event_id="very-late", run_id="run-0"),
    ) is None
    assert load_work_item(str(tmp_path), "ledger", "task-a").status == "planned"


def test_retry_tombstones_survive_more_than_event_ledger_retention(tmp_path):
    create_work_item(
        root=str(tmp_path), session_id="ledger-long", task_id="task-a",
        title="Many retries", status="approved",
    )
    for index in range(513):
        run_id = f"run-{index}"
        project_work_item_event(
            root=str(tmp_path), session_id="ledger-long",
            event=_event("run.started", event_id=f"start-{index}", run_id=run_id),
        )
        project_work_item_event(
            root=str(tmp_path), session_id="ledger-long",
            event=_event("run.failed", event_id=f"failed-{index}", run_id=run_id),
        )
        reconcile_checklist_work_item(
            root=str(tmp_path), session_id="ledger-long", task_id="task-a",
            title="Many retries", checklist_status="pending",
        )
    assert project_work_item_event(
        root=str(tmp_path), session_id="ledger-long",
        event=_event("run.started", event_id="very-late-start", run_id="run-0"),
    ) is None
    assert load_work_item(str(tmp_path), "ledger-long", "task-a").status == "planned"


def test_replay_skips_nonnumeric_sequence(tmp_path):
    create_work_item(
        root=str(tmp_path), session_id="malformed", task_id="task-a",
        title="Replay", status="approved",
    )
    log = tmp_path / "events.jsonl"
    log.write_text(
        json.dumps({**_event("run.started", event_id="bad", run_id="run-a"), "sequence": "bad"})
        + "\n"
        + json.dumps({**_event("run.started", event_id="good", run_id="run-a"), "sequence": 1})
        + "\n",
        encoding="utf-8",
    )
    assert replay_work_item_event_log(
        root=str(tmp_path), session_id="malformed", event_log_path=str(log)
    ) == 2
    assert load_work_item(str(tmp_path), "malformed", "task-a").status == "running"
