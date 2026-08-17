import json
import os
import queue
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _server_mocks():
    patches = [
        patch("dotenv.load_dotenv"),
        patch("nexus.main_agent.NexusLoop"),
        patch("security.core.auth.check_auth", return_value=MagicMock()),
        patch("security.core.auth.is_public_path", return_value=True),
        patch("security.core.auth.AuthUser"),
        patch("security.core.auth.validate_dashboard_token", return_value=True),
        patch("yaml.safe_load", return_value={}),
        patch("yaml.safe_dump"),
    ]
    for item in patches:
        item.start()
    for mod in list(sys.modules.keys()):
        if mod.startswith("apps.api"):
            del sys.modules[mod]
    yield
    for item in patches:
        item.stop()


def _reset(server, tmp_path):
    server._CHECKPOINTS_ROOT = str(tmp_path / "checkpoints")
    server._WORK_EVENTS_DIR = str(tmp_path / "work_events")
    server._CHECKPOINT_GUARD.clear()
    server._CHECKPOINT_STREAM_PUSHERS.clear()
    server._WORK_EVENT_SEQUENCES.clear()
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    (ws / "existing.txt").write_text("hello", encoding="utf-8")
    (ws / "keep").mkdir(exist_ok=True)
    (ws / "keep" / "nested.md").write_text("# keep", encoding="utf-8")
    server._workspace_root = lambda: str(ws)
    return ws


def _wait_for(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_checkpoint_create_list_restore_and_delete(tmp_path):
    import apps.api
    from apps.api import app

    ws = _reset(server, tmp_path)
    meta = server._create_workspace_checkpoint(str(ws), "session-ck", "run-ck")
    assert meta["checkpoint_id"]
    assert meta["file_count"] == 2
    assert meta["size_bytes"] > 0

    with TestClient(app) as client:
        list_response = client.get("/api/checkpoints?session_id=session-ck")
        other_response = client.get("/api/checkpoints?session_id=other-session")

    assert list_response.status_code == 200
    checkpoints = list_response.json()["checkpoints"]
    assert len(checkpoints) == 1
    assert checkpoints[0]["checkpoint_id"] == meta["checkpoint_id"]
    assert checkpoints[0]["file_count"] == 2
    assert checkpoints[0]["session_id"] == "session-ck"
    assert other_response.json()["checkpoints"] == []

    (ws / "existing.txt").write_text("changed", encoding="utf-8")
    (ws / "added.py").write_text("x = 1", encoding="utf-8")
    (ws / "keep" / "nested.md").unlink()

    with TestClient(app) as client:
        restore_response = client.post(
            f"/api/checkpoints/{meta['checkpoint_id']}/restore",
            json={"session_id": "session-ck"},
        )

    assert restore_response.status_code == 200
    payload = restore_response.json()
    assert payload["ok"] is True
    assert payload["restored"] == 2
    assert payload["removed"] == 1
    assert payload["failed"] == 0
    assert payload["failures"] == []
    assert payload["workspace_root"] == str(ws)
    assert (ws / "existing.txt").read_text(encoding="utf-8") == "hello"
    assert not (ws / "added.py").exists()
    assert (ws / "keep" / "nested.md").read_text(encoding="utf-8") == "# keep"

    with TestClient(app) as client:
        delete_response = client.delete(
            f"/api/checkpoints/{meta['checkpoint_id']}?session_id=session-ck"
        )
        gone_response = client.get("/api/checkpoints?session_id=session-ck")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}
    assert gone_response.json()["checkpoints"] == []


def test_timed_out_run_unregisters_checkpoint_stream_pusher(tmp_path):
    import apps.api

    _reset(server, tmp_path)

    class Loop:
        work_event_sink = None

    out_queue = queue.Queue()
    _, live_sink = server.bind_live_work_event_sink(Loop(), "checkpoint-session", "run-timeout", out_queue)

    live_sink({"event_type": "run.started", "run_id": "run-timeout", "turn_id": "run-timeout", "kind": "run"})
    assert "run-timeout" in server._CHECKPOINT_STREAM_PUSHERS

    live_sink({"event_type": "run.timed_out", "run_id": "run-timeout", "turn_id": "run-timeout", "kind": "run"})
    assert "run-timeout" not in server._CHECKPOINT_STREAM_PUSHERS

    server._emit_checkpoint_created("checkpoint-session", "run-timeout", "run-timeout", {"checkpoint_id": "late"})
    assert not any(item[0] == "event" and item[1].get("event_type") == "checkpoint.created" for item in list(out_queue.queue))


def test_checkpoint_restore_wrong_session_is_404(tmp_path):
    import apps.api
    from apps.api import app

    ws = _reset(server, tmp_path)
    meta = server._create_workspace_checkpoint(str(ws), "session-ck", "run-ck")

    with TestClient(app) as client:
        restore_response = client.post(
            f"/api/checkpoints/{meta['checkpoint_id']}/restore",
            json={"session_id": "other-session"},
        )
        delete_response = client.delete(
            f"/api/checkpoints/{meta['checkpoint_id']}?session_id=other-session"
        )

    assert restore_response.status_code == 404
    assert delete_response.status_code == 404


def test_checkpoint_missing_and_corrupt_errors(tmp_path):
    import apps.api
    from apps.api import app

    ws = _reset(server, tmp_path)

    with TestClient(app) as client:
        missing_restore = client.post("/api/checkpoints/does-not-exist/restore", json={"session_id": "s"})
        missing_delete = client.delete("/api/checkpoints/does-not-exist?session_id=s")
        missing_list = client.get("/api/checkpoints?session_id=s")

    assert missing_restore.status_code == 404
    assert missing_delete.status_code == 404
    assert missing_list.json()["checkpoints"] == []

    ckpt_root = os.path.join(server._CHECKPOINTS_ROOT, "abc123")
    os.makedirs(ckpt_root, exist_ok=True)
    with open(os.path.join(ckpt_root, "metadata.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    with open(os.path.join(ckpt_root, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write("[]")
    os.makedirs(os.path.join(ckpt_root, "snapshot"), exist_ok=True)

    with TestClient(app) as client:
        corrupt = client.post("/api/checkpoints/abc123/restore", json={"session_id": "s"})

    assert corrupt.status_code == 400
    assert "corrupt" in corrupt.json()["detail"]


def test_checkpoint_restore_conflict_when_in_progress(tmp_path):
    import apps.api
    from apps.api import app

    ws = _reset(server, tmp_path)
    meta = server._create_workspace_checkpoint(str(ws), "session-ck", "run-ck")
    lock = threading.Lock()
    lock.acquire()
    server._CHECKPOINT_RESTORE_LOCKS[meta["checkpoint_id"]] = lock

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/checkpoints/{meta['checkpoint_id']}/restore",
                json={"session_id": "session-ck"},
            )
    finally:
        lock.release()

    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"]


def test_checkpoint_snapshot_skips_venv_and_generated_dirs(tmp_path):
    import apps.api

    ws = _reset(server, tmp_path)
    (ws / ".venv").mkdir()
    (ws / ".venv" / "lib.py").write_text("skip", encoding="utf-8")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "dep.js").write_text("skip", encoding="utf-8")
    (ws / "models").mkdir()
    (ws / "models" / "model.bin").write_text("skip", encoding="utf-8")
    (ws / "app").mkdir()
    (ws / "app" / "main.py").write_text("print(1)", encoding="utf-8")
    (ws / "data.pkl").write_text("skip", encoding="utf-8")

    meta = server._create_workspace_checkpoint(str(ws), "session-ck", "run-ck")
    snapshot_root = os.path.join(server._CHECKPOINTS_ROOT, meta["checkpoint_id"], "snapshot")

    assert os.path.exists(os.path.join(snapshot_root, "existing.txt"))
    assert os.path.exists(os.path.join(snapshot_root, "app", "main.py"))
    assert not os.path.exists(os.path.join(snapshot_root, ".venv", "lib.py"))
    assert not os.path.exists(os.path.join(snapshot_root, "node_modules", "dep.js"))
    assert not os.path.exists(os.path.join(snapshot_root, "models", "model.bin"))
    assert not os.path.exists(os.path.join(snapshot_root, "data.pkl"))


def test_checkpoint_trigger_fires_on_canonical_envelope(tmp_path):
    """Canonical envelopes use `type` (not `event_type`) and nest state in payload."""
    import apps.api

    ws = _reset(server, tmp_path)
    canonical = {
        "event_id": "run_abc",
        "run_id": "abc123",
        "conversation_id": "session-canonical",
        "type": "run.status",
        "title": "Executing tools",
        "status": "running",
        "timestamp": time.time(),
        "payload": {
            "kind": "run",
            "action": "Executing tools",
            "payload": {"state": "execution"},
            "visibility": "public",
            "state": "execution",
        },
        "session_id": "session-canonical",
    }
    server._append_work_event("session-canonical", canonical)

    assert _wait_for(lambda: server._CHECKPOINT_GUARD.get("abc123") == "done")

    log_path = server.work_events_path("session-canonical")
    lines = [json.loads(line) for line in open(log_path, encoding="utf-8")]
    created = [line for line in lines if line.get("event_type") == "checkpoint.created"]
    assert len(created) == 1
    assert created[0]["run_id"] == "abc123"
    assert created[0]["file_count"] == 2
    assert created[0]["checkpoint_id"]


def test_checkpoint_trigger_ignores_unrelated_events(tmp_path):
    import apps.api

    ws = _reset(server, tmp_path)
    server._append_work_event(
        "session-ignore",
        {
            "event_id": "x1",
            "run_id": "run-ignore",
            "type": "file.created",
            "status": "success",
            "payload": {"kind": "file", "path": "a.txt"},
        },
    )
    server._append_work_event(
        "session-ignore",
        {
            "event_id": "x2",
            "run_id": "run-ignore",
            "type": "run.completed",
            "status": "success",
            "payload": {"kind": "run"},
        },
    )
    time.sleep(0.5)
    assert not any(
        line.get("event_type") == "checkpoint.created"
        for line in (json.loads(line) for line in open(server.work_events_path("session-ignore"), encoding="utf-8"))
    )


def test_checkpoint_trigger_appends_created_event(tmp_path):
    import apps.api

    ws = _reset(server, tmp_path)
    server._workspace_root = lambda: str(ws)
    server._append_work_event(
        "session-trigger",
        {
            "event_type": "run.status",
            "state": "execution",
            "run_id": "run-trigger",
            "turn_id": "turn-trigger",
        },
    )

    assert _wait_for(lambda: server._CHECKPOINT_GUARD.get("run-trigger") == "done")

    log_path = server.work_events_path("session-trigger")
    assert log_path.endswith("session-trigger.jsonl")
    lines = [json.loads(line) for line in open(log_path, encoding="utf-8")]
    created = [line for line in lines if line.get("event_type") == "checkpoint.created"]
    assert len(created) == 1
    assert created[0]["turn_id"] == "turn-trigger"
    assert created[0]["run_id"] == "run-trigger"
    assert created[0]["kind"] == "checkpoint"
    assert created[0]["file_count"] == 2
    assert created[0]["checkpoint_id"]

    meta = server._load_checkpoint_meta(
        os.path.join(server._CHECKPOINTS_ROOT, created[0]["checkpoint_id"])
    )
    assert meta["session_id"] == "session-trigger"

    server._append_work_event(
        "session-trigger",
        {"event_type": "run.status", "state": "execution", "run_id": "run-trigger", "turn_id": "turn-trigger"},
    )
    time.sleep(0.3)
    lines = [json.loads(line) for line in open(log_path, encoding="utf-8")]
    assert len([line for line in lines if line.get("event_type") == "checkpoint.created"]) == 1
