from __future__ import annotations

import json

import pytest

from nexus.work_items import (
    create_work_item,
    list_work_items,
    load_work_item,
    clear_work_item_projection_failure,
    pending_work_item_projection_failures,
    persist_work_item,
    project_work_item_event,
    record_work_item_projection_failure,
    replay_work_item_event_log,
)


def test_work_item_lifecycle_is_durable(tmp_path):
    item = create_work_item(root=str(tmp_path), session_id="s/1", title="Ship feature")
    assert item.status == "draft"
    item.transition("planned", reason="planner completed")
    item.transition("approved")
    item.transition("running", run_id="run/42")
    persist_work_item(item)

    restored = load_work_item(str(tmp_path), "s/1", item.task_id)
    assert restored is not None
    assert restored.status == "running"
    assert restored.run_id == "run_42"
    assert restored.version == 3

    restored.transition("ready_for_review")
    restored.transition("applied")
    persist_work_item(restored)
    assert load_work_item(str(tmp_path), "s/1", item.task_id).completed_at is not None


def test_invalid_transition_is_rejected(tmp_path):
    item = create_work_item(root=str(tmp_path), session_id="session", title="Task")
    with pytest.raises(ValueError, match="Invalid work-item transition"):
        item.transition("applied")


def test_atomic_persistence_leaves_valid_json(tmp_path):
    item = create_work_item(root=str(tmp_path), session_id="session", title="Task")
    payload = json.loads(item.path.read_text(encoding="utf-8"))
    assert payload["task_id"] == item.task_id
    assert not list(item.path.parent.glob("*.tmp"))


def test_list_work_items_is_session_scoped(tmp_path):
    first = create_work_item(root=str(tmp_path), session_id="one", title="First")
    create_work_item(root=str(tmp_path), session_id="two", title="Second")
    items = list_work_items(str(tmp_path), "one")
    assert [item.task_id for item in items] == [first.task_id]


def test_replay_continues_after_one_projection_failure(tmp_path, monkeypatch):
    first = create_work_item(
        root=str(tmp_path), session_id="replay", task_id="task-a", title="First", status="planned"
    )
    second = create_work_item(
        root=str(tmp_path), session_id="replay", task_id="task-b", title="Second", status="planned"
    )
    log_path = tmp_path / "events.jsonl"
    events = [
        {"event_id": "bad", "event_type": "run.started", "task_id": first.task_id, "run_id": "run-a"},
        {"event_id": "good", "event_type": "run.started", "task_id": second.task_id, "run_id": "run-b"},
    ]
    log_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    import nexus.work_items as work_items
    original = work_items.project_work_item_event

    def fail_first(*, root, session_id, event):
        if event.get("event_id") == "bad":
            raise RuntimeError("corrupt projection")
        return original(root=root, session_id=session_id, event=event)

    monkeypatch.setattr(work_items, "project_work_item_event", fail_first)
    assert replay_work_item_event_log(
        root=str(tmp_path), session_id="replay", event_log_path=str(log_path)
    ) == 2
    assert load_work_item(str(tmp_path), "replay", "task-a").status == "planned"
    assert load_work_item(str(tmp_path), "replay", "task-b").status == "running"
    pending = pending_work_item_projection_failures(
        event_log_path=str(log_path)
    )
    assert pending[0]["event_id"] == "bad"
    assert pending[0]["attempts"] == 1


def test_projection_failure_ledger_is_durable_and_clears_on_success(tmp_path):
    log_path = tmp_path / "events.jsonl"
    event = {
        "event_id": "event-1",
        "event_type": "run.completed",
        "task_id": "task-a",
    }

    record = record_work_item_projection_failure(
        event_log_path=str(log_path), event=event, error=RuntimeError("temporary")
    )
    assert record["attempts"] == 1
    assert record["next_retry_at"] > record["last_failed_at"]
    pending = pending_work_item_projection_failures(event_log_path=str(log_path))
    assert pending[0]["event_id"] == "event-1"
    assert pending[0]["last_error"] == "temporary"

    clear_work_item_projection_failure(event_log_path=str(log_path), event=event)
    assert pending_work_item_projection_failures(event_log_path=str(log_path)) == []
