from nexus.control_store import ControlStore


def test_control_store_requires_dependencies_and_a_valid_lease(tmp_path):
    store = ControlStore(str(tmp_path))
    task = store.create_task(goal="Ship durable workflow", session_id="s1")
    plan = store.create_plan(task_id=task["task_id"], goal=task["goal"], steps=[
        {"step_id": "inspect", "title": "Inspect"},
        {"step_id": "implement", "title": "Implement", "dependencies": ["inspect"]},
    ])
    assert [step["step_id"] for step in store.ready_steps(plan["plan_id"])] == ["inspect"]
    first = store.start_run(step_id="inspect", worker_id="agent-1", process_id="proc-1")
    assert store.complete_run(run_id=first["run_id"], lease_token=first["lease_token"], evidence=[{"kind": "test", "uri": "tests/test_x.py"}])
    assert [step["step_id"] for step in store.ready_steps(plan["plan_id"])] == ["implement"]
    second = store.start_run(step_id="implement", worker_id="agent-2", process_id="proc-2")
    assert store.complete_run(run_id=second["run_id"], lease_token="stale") is False
    assert store.complete_run(run_id=second["run_id"], lease_token=second["lease_token"]) is True
    link = store.link_legacy_record(source_type="queue", source_id="42", task_id=task["task_id"], plan_id=plan["plan_id"], step_id="implement", run_id=second["run_id"])
    assert link["source_id"] == "42"
    assert [event["event_type"] for event in store.pending_outbox()] == ["task.created", "plan.created", "run.started", "run.completed", "run.started", "run.completed", "legacy.linked"]


def test_outbox_claim_ack_and_expired_lease_recovery(tmp_path):
    store = ControlStore(str(tmp_path))
    store.create_task(goal="publish me")
    first = store.claim_outbox("publisher-a", limit=1, lease_seconds=1)
    assert len(first) == 1
    event_id = first[0]["event_id"]
    assert store.claim_outbox("publisher-b", limit=10) == []
    assert store.mark_outbox_published(event_id, "publisher-b") is False
    assert store.mark_outbox_published(event_id, "publisher-a") is True
    assert not [item for item in store.pending_outbox() if item["event_id"] == event_id]

    store.create_task(goal="retry me")
    claimed = store.claim_outbox("publisher-a", limit=100, lease_seconds=1)
    retry_event = claimed[-1]["event_id"]
    assert store.release_outbox(retry_event, "publisher-a", "network down") is True
    reclaimed = store.claim_outbox("publisher-b", limit=100)
    assert any(item["event_id"] == retry_event for item in reclaimed)
