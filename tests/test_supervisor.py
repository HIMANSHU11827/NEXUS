import sys

from nexus.supervisor import NexusSupervisor


def test_supervisor_persists_and_quarantines_crash_loop(tmp_path):
    supervisor = NexusSupervisor(
        str(tmp_path),
        command=[sys.executable, "-c", "import time; time.sleep(0.2)"],
        health_url="http://127.0.0.1:1/health",
        interval=0.01,
        startup_timeout=0.05,
        max_restarts=2,
        crash_window=60,
    )
    alerts = []
    supervisor._dispatch_quarantine_alert = lambda incident: alerts.append(incident) or {"status": "sent"}
    assert supervisor.run() == 2
    assert supervisor.is_quarantined() is True
    incident = supervisor._incident()
    assert incident["failure_count"] == 2
    assert "readiness" in incident["last_error"]
    assert len(alerts) == 1

    supervisor.clear_quarantine()
    assert supervisor.is_quarantined() is False


def test_supervisor_rejects_unhealthy_probe(tmp_path):
    supervisor = NexusSupervisor(str(tmp_path), health_url="http://127.0.0.1:1/health")
    assert supervisor.probe() is False


def test_supervisor_singleton_lock_rejects_live_duplicate_and_reclaims_stale(tmp_path):
    first = NexusSupervisor(str(tmp_path))
    second = NexusSupervisor(str(tmp_path))
    assert first._acquire_lock() is True
    assert second._acquire_lock() is False
    first._release_lock()

    lock_path = tmp_path / ".nexus" / "supervisor.lock"
    lock_path.parent.mkdir(exist_ok=True)
    lock_path.write_text('{"pid":999999,"started_at":0}', encoding="utf-8")
    assert second._acquire_lock() is True
    second._release_lock()
    assert not lock_path.exists()


def test_supervisor_returns_distinct_code_when_another_instance_owns_lock(tmp_path):
    owner = NexusSupervisor(str(tmp_path))
    contender = NexusSupervisor(str(tmp_path))
    assert owner._acquire_lock() is True
    try:
        assert contender.run() == 3
    finally:
        owner._release_lock()
