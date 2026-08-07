from __future__ import annotations

import json

import pytest

from nexus.work_items import (
    create_work_item,
    list_work_items,
    load_work_item,
    persist_work_item,
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
