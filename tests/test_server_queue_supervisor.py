"""Coverage for the API-owned durable queue worker."""

import asyncio


def test_embedded_queue_supervisor_restarts_after_driver_failure(monkeypatch, tmp_path):
    import server
    import queue.driver as queue_driver

    instances = []

    class FakeDriver:
        def __init__(self, **kwargs):
            instances.append(kwargs)
            self.stopped = False

        async def run(self):
            if len(instances) == 1:
                raise RuntimeError("simulated worker crash")
            server._QUEUE_DRIVER_STOPPING = True

        def stop(self):
            self.stopped = True

        async def shutdown(self, drain_timeout=0):
            self.stopped = True

    monkeypatch.setattr(queue_driver, "QueueDriver", FakeDriver)
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    server._QUEUE_DRIVER_STOPPING = False
    try:
        asyncio.run(server._queue_driver_supervisor())
    finally:
        server._QUEUE_DRIVER_STOPPING = False
        server._QUEUE_DRIVER = None

    assert len(instances) == 2
    assert instances[0]["root"] == str(tmp_path)
    assert instances[0]["workers"] >= 1


def test_health_reports_embedded_worker_readiness(monkeypatch):
    import server

    class DoneTask:
        def done(self):
            return True

    monkeypatch.setenv("NEXUS_EMBED_QUEUE_DRIVER", "true")
    monkeypatch.setattr(server, "_QUEUE_DRIVER_TASK", DoneTask())
    try:
        server.health()
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
    else:
        raise AssertionError("health must fail closed when the embedded worker is stopped")


def test_embedded_queue_supervisor_retries_constructor_failure(monkeypatch, tmp_path):
    import server
    import queue.driver as queue_driver

    attempts = []

    class FakeDriver:
        def __init__(self, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise OSError("database temporarily unavailable")

        async def run(self):
            server._QUEUE_DRIVER_STOPPING = True

        def stop(self):
            pass

        async def shutdown(self, drain_timeout=0):
            pass

    monkeypatch.setattr(queue_driver, "QueueDriver", FakeDriver)
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    server._QUEUE_DRIVER_STOPPING = False
    try:
        asyncio.run(server._queue_driver_supervisor())
    finally:
        server._QUEUE_DRIVER_STOPPING = False
        server._QUEUE_DRIVER = None

    assert len(attempts) == 2


def test_runtime_metrics_exposes_stale_safe_queue_status(monkeypatch, tmp_path):
    import server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("NEXUS_EMBED_QUEUE_DRIVER", raising=False)
    payload = server.runtime_metrics()
    assert payload["status"] == "success"
    assert payload["queue"]["mode"] == "embedded"
    assert payload["queue"]["runtime"]["healthy"] is False


def test_runtime_metrics_external_mode_when_worker_disabled(monkeypatch, tmp_path):
    import server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("NEXUS_EMBED_QUEUE_DRIVER", "false")
    payload = server.runtime_metrics()
    assert payload["status"] == "success"
    assert payload["queue"]["mode"] == "external"


def test_prometheus_metrics_exposes_runtime_health_and_quarantine(monkeypatch, tmp_path):
    import json
    import server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("NEXUS_EMBED_QUEUE_DRIVER", raising=False)
    incident_path = tmp_path / ".nexus" / "supervisor_incident.json"
    incident_path.parent.mkdir(parents=True)
    incident_path.write_text(json.dumps({"state": "quarantined", "failures": [1]}), encoding="utf-8")
    response = server.prometheus_metrics()
    body = response.body.decode("utf-8")
    assert response.media_type == "text/plain; version=0.0.4"
    assert "nexus_queue_runtime_healthy 0" in body
    assert "nexus_supervisor_quarantined 1" in body
    assert "nexus_hives_total 0" in body


def test_embedded_queue_supervisor_quarantines_repeated_crashes(monkeypatch, tmp_path):
    import server
    import queue.driver as queue_driver
    from queue.status import read_incident

    class CrashingDriver:
        def __init__(self, **kwargs):
            pass

        async def run(self):
            raise RuntimeError("persistent failure")

    monkeypatch.setattr(queue_driver, "QueueDriver", CrashingDriver)
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("NEXUS_QUEUE_MAX_RESTARTS", "1")
    monkeypatch.setenv("NEXUS_QUEUE_CRASH_WINDOW", "60")
    server._QUEUE_DRIVER_STOPPING = False
    try:
        asyncio.run(server._queue_driver_supervisor())
        assert read_incident(str(tmp_path))["quarantined"] is True
    finally:
        server._QUEUE_DRIVER_STOPPING = False
        server._QUEUE_DRIVER = None
