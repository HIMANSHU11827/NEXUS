def test_health_projects_lifecycle_persistence(monkeypatch):
    import server

    monkeypatch.setattr(
        server,
        "_lifecycle_persistence_health",
        lambda: {"available": False, "operation": "save", "error": "disk full", "updated_at": 1.0},
    )
    # The health endpoint reports 503 while an embedded queue worker is
    # advertised but not running; simulate a live worker so this test stays
    # focused on the lifecycle-persistence payload.
    class _RunningTask:
        def done(self):
            return False

    monkeypatch.setattr(server, "_QUEUE_DRIVER_TASK", _RunningTask())

    result = server.health()

    assert result["status"] == "ok"
    assert result["queue_worker"] == "running"
    assert result["lifecycle_persistence"]["available"] is False
    assert result["lifecycle_persistence"]["operation"] == "save"


def test_lifecycle_health_failure_is_bounded_and_redacted(monkeypatch):
    import server

    class BrokenSupervisor:
        def get_stats(self):
            raise RuntimeError("token=sk-health-secret")

    import lifecycle
    monkeypatch.setattr(lifecycle, "get_component_supervisor", lambda: BrokenSupervisor())

    result = server._lifecycle_persistence_health()

    assert result["available"] is False
    assert "sk-health-secret" not in result["error"]
    assert "REDACTED" in result["error"]
