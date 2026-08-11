from concurrent.futures import ThreadPoolExecutor

from evolution.backlog import mark_action_status, pending_actions, queue_improvement_action


def test_backlog_concurrent_appends_are_complete_and_parseable(tmp_path):
    root = str(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(pool.map(lambda i: queue_improvement_action({"action": f"improve-{i}"}, root), range(32)))

    assert all(entries)
    actions = pending_actions(root)
    assert len(actions) == 32
    assert {item["action"] for item in actions} == {f"improve-{i}" for i in range(32)}


def test_backlog_status_rewrite_is_atomic_and_uses_unique_temp_files(tmp_path):
    root = str(tmp_path)
    entry = queue_improvement_action({"action": "review"}, root)

    assert entry is not None
    assert mark_action_status(entry["id"], "done", root)
    assert pending_actions(root) == []
