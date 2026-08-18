from fastapi.testclient import TestClient
import json
import subprocess
import sys
from pathlib import Path

import apps.api as server
import security.core.auth as authentication
from nexus.work_items import create_work_item
from nexus.run_context import start_run_context


def _authed_client(monkeypatch):
    token = "work-item-api-test-token"
    monkeypatch.setattr(authentication, "_AUTH_TOKEN", token)
    client = TestClient(server.app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_work_item_api_lists_session_scoped_public_records(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    first = create_work_item(
        root=str(tmp_path),
        session_id="session-a",
        task_id="task-a",
        title="Ship the API",
        run_id="run-a",
        plan_id="plan-a",
    )
    create_work_item(root=str(tmp_path), session_id="session-b", task_id="task-b", title="Other work")

    with _authed_client(monkeypatch) as client:
        response = client.get("/api/work-items", params={"session_id": "session-a"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert [item["task_id"] for item in payload["work_items"]] == [first.task_id]
    assert payload["work_items"][0]["run_id"] == "run-a"
    assert payload["work_items"][0]["plan_id"] == "plan-a"
    assert payload["active_plan"]["plan_id"] == "plan-a"
    assert [step["task_id"] for step in payload["active_plan"]["steps"]] == [first.task_id]
    assert "root" not in payload["work_items"][0]


def test_work_item_api_restores_only_the_newest_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    old = create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="old-step",
        title="Old mission", plan_id="plan-old",
    )
    old.created_at = 1.0
    old.updated_at = 1000.0
    from nexus.work_items import persist_work_item
    persist_work_item(old)
    new = create_work_item(
        root=str(tmp_path), session_id="session-a", task_id="new-step",
        title="New mission", plan_id="plan-new",
    )
    new.created_at = 2.0
    persist_work_item(new)

    with _authed_client(monkeypatch) as client:
        payload = client.get("/api/work-items", params={"session_id": "session-a"}).json()

    assert {item["task_id"] for item in payload["work_items"]} == {"old-step", "new-step"}
    assert payload["active_plan"]["plan_id"] == "plan-new"
    assert [step["task_id"] for step in payload["active_plan"]["steps"]] == ["new-step"]


def test_work_item_api_get_is_durable_and_returns_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    item = create_work_item(
        root=str(tmp_path),
        session_id="session-a",
        task_id="task-a",
        title="Durable task",
    )

    with _authed_client(monkeypatch) as client:
        found = client.get(f"/api/work-items/session-a/{item.task_id}")
        missing = client.get("/api/work-items/session-a/missing")

    assert found.status_code == 200
    assert found.json()["work_item"]["title"] == "Durable task"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Work item not found"


def test_work_item_api_replays_missed_run_events_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "work_events"))
    create_work_item(
        root=str(tmp_path), session_id="replay", task_id="task-a",
        title="Recover task", status="approved",
    )
    event_path = Path(server.work_events_path("replay"))
    event_path.write_text(
        json.dumps({
            "event_id": "replay-start", "event_type": "run.started",
            "task_id": "task-a", "run_id": "run-a", "sequence": 1,
        }) + "\n" + "{partial\n" + json.dumps({
            "event_id": "replay-done", "event_type": "run.completed",
            "task_id": "task-a", "run_id": "run-a", "sequence": 2,
        }) + "\n",
        encoding="utf-8",
    )

    with _authed_client(monkeypatch) as client:
        response = client.get("/api/work-items/replay/task-a")

    assert response.status_code == 200
    assert response.json()["work_item"]["status"] == "applied"
    assert response.json()["work_item"]["run_id"] == "run-a"


def test_work_item_api_validates_limit_and_preserves_legacy_tasks_route(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))

    with _authed_client(monkeypatch) as client:
        invalid = client.get("/api/work-items", params={"limit": 0})
        legacy = client.get("/api/tasks")

    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "limit must be between 1 and 1000"
    assert legacy.status_code == 200
    assert isinstance(legacy.json()["tasks"], list)


def test_work_event_sequences_are_unique_across_worker_processes(tmp_path):
    events_dir = tmp_path / "events"
    script = (
        "import apps.api as server\n"
        f"server._WORK_EVENTS_DIR = {str(events_dir)!r}\n"
        "server._WORK_EVENT_SEQUENCES.clear()\n"
        "for index in range(10):\n"
        "    server._append_work_event('shared', {'id': f'worker-event-{index}', 'kind': 'tool', 'status': 'success'})\n"
    )
    project_root = Path(__file__).resolve().parents[2]
    processes = [subprocess.Popen([sys.executable, "-c", script], cwd=str(project_root)) for _ in range(2)]
    assert all(process.wait(timeout=60) == 0 for process in processes)

    records = [json.loads(line) for line in (events_dir / "shared.jsonl").read_text(encoding="utf-8").splitlines()]
    sequences = [record["sequence"] for record in records]
    assert len(sequences) == 20
    assert len(set(sequences)) == 20
    assert sorted(sequences) == list(range(1, 21))


def test_run_detail_opt_in_returns_bounded_complete_public_event_sequence(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "work_events"))
    server._WORK_EVENT_SEQUENCES.clear()
    server._WORK_EVENT_CACHE.clear()
    context = start_run_context(
        root=str(tmp_path), session_id="session-a", run_id="run-a", prompt="inspect", provider="test", model="test"
    )
    context.finish("success", "run.completed")
    for sequence, status in ((1, "running"), (2, "success"), (3, "success")):
        server._append_work_event("session-a", {
            "event_id": "same-event",
            "id": "same-event",
            "sequence": sequence,
            "turn_id": "run-a",
            "run_id": "run-a",
            "kind": "tool",
            "status": status,
        })
    server._append_work_event("session-a", {
        "event_id": "private",
        "sequence": 4,
        "turn_id": "run-a",
        "kind": "diagnostic",
        "status": "success",
        "visibility": "internal",
    })
    server._append_work_event("session-a", {
        "event_id": "other-run",
        "sequence": 5,
        "turn_id": "run-b",
        "kind": "tool",
        "status": "success",
    })

    with _authed_client(monkeypatch) as client:
        collapsed = client.get("/api/runs/session-a/run-a")
        complete = client.get("/api/runs/session-a/run-a", params={"include_events": "true", "limit": 2})
        invalid_limit = client.get("/api/runs/session-a/run-a", params={"include_events": "true", "limit": 1001})

    assert collapsed.status_code == 200
    assert collapsed.json()["events_mode"] == "collapsed"
    assert len(collapsed.json()["events"]) == 1
    assert complete.status_code == 200
    payload = complete.json()
    assert payload["events_mode"] == "complete"
    assert payload["events_truncated"] is True
    assert [event["sequence"] for event in payload["events"]] == [1, 2]
    assert all(event["event_id"] != "private" for event in payload["events"])
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()["detail"] == "limit must be between 1 and 1000"


def test_work_event_reads_and_append_survive_malformed_sequences_and_utf8(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "work_events"))
    server._WORK_EVENT_CACHE.clear()
    server._WORK_EVENT_SEQUENCES.clear()
    event_path = Path(server.work_events_path("hostile"))
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("wb") as handle:
        handle.write(b"{\"event_id\":\"bad-utf8\",\"sequence\":\"bad\"}\n\xff\xfe\n")
        handle.write(json.dumps({"event_id": "valid", "sequence": 4, "status": "success"}).encode() + b"\n")

    with _authed_client(monkeypatch) as client:
        response = client.get("/api/work-events", params={"session_id": "hostile"})
    assert response.status_code == 200
    assert response.json()["next_sequence"] == 4

    appended = server._append_work_event("hostile", {"event_id": "new", "status": "success"})
    assert appended["sequence"] == 5


def test_server_reads_legacy_event_session_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "work_events"))
    server._WORK_EVENT_CACHE.clear()
    legacy = Path(server._WORK_EVENTS_DIR) / "team_alpha.jsonl"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"event_id": "legacy-event", "sequence": 1, "status": "success"}) + "\n", encoding="utf-8")

    events = server.replay_work_events_after("team/alpha", 0, limit=20)

    assert [event["event_id"] for event in events] == ["legacy-event"]
