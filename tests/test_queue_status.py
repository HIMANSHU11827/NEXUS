import json
import os
import time

from queues.status import QueueRuntimeStatus, read_incident, read_status, record_crash


def test_queue_status_publishes_atomic_heartbeat_and_detects_stale(tmp_path):
    path = tmp_path / ".nexus" / "queue.json"
    status = QueueRuntimeStatus(str(tmp_path), path=str(path), owner="worker-a")
    status.publish("running", stats={"leased": 2}, force=True)

    current = read_status(str(path), stale_after=30)
    assert current["healthy"] is True
    assert current["owner"] == "worker-a"
    assert current["stats"]["leased"] == 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["heartbeat_at"] = time.time() - 100
    path.write_text(json.dumps(payload), encoding="utf-8")
    stale = read_status(str(path), stale_after=30)
    assert stale["stale"] is True
    assert stale["healthy"] is False


def test_queue_status_marks_stopped(tmp_path):
    path = tmp_path / "queue.json"
    status = QueueRuntimeStatus(str(tmp_path), path=str(path))
    status.publish("running", force=True)
    status.stopped(stats={"completed": 1})
    result = read_status(str(path))
    assert result["state"] == "stopped"
    assert result["healthy"] is False


def test_missing_queue_status_is_unhealthy(tmp_path):
    result = read_status(str(tmp_path / "missing.json"))
    assert result["healthy"] is False
    assert result["stale"] is True


def test_crash_window_persists_and_quarantines(tmp_path):
    first = record_crash(str(tmp_path), "first", max_restarts=2, window_seconds=60)
    assert first["quarantined"] is False
    second = record_crash(str(tmp_path), "second", max_restarts=2, window_seconds=60)
    assert second["quarantined"] is True
    incident = read_incident(str(tmp_path))
    assert incident["quarantined"] is True
    assert incident["failure_count"] == 2
