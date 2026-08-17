import json

from queues.alerts import dispatch_incident


def _incident():
    return {
        "state": "quarantined",
        "failure_count": 3,
        "max_restarts": 3,
        "window_seconds": 60,
        "failures": [100.0, 101.0, 102.0],
        "last_error": "worker crashed",
        "updated_at": 102.0,
    }


def test_alert_delivery_is_disabled_without_webhook(tmp_path):
    result = dispatch_incident(str(tmp_path), _incident())
    assert result["status"] == "disabled"
    assert list((tmp_path / ".nexus" / "alerts").glob("*.json"))


def test_alert_delivery_is_deduplicated_after_success(monkeypatch, tmp_path):
    calls = []

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout, json.loads(request.data)))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    first = dispatch_incident(str(tmp_path), _incident(), url="https://alerts.example.test/hook")
    second = dispatch_incident(str(tmp_path), _incident(), url="https://alerts.example.test/hook")
    assert first["status"] == "sent"
    assert second["deduplicated"] is True
    assert len(calls) == 1


def test_alert_delivery_persists_failure_for_restart_retry(monkeypatch, tmp_path):
    def fail_urlopen(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    result = dispatch_incident(str(tmp_path), _incident(), url="https://alerts.example.test/hook")
    assert result["status"] == "failed"
    assert "offline" in result["error"]


def test_alert_delivery_supports_distinct_supervisor_event(monkeypatch, tmp_path):
    payloads = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = dispatch_incident(
        str(tmp_path), _incident(), url="https://alerts.example.test/hook",
        event="nexus.supervisor.quarantined", source="supervisor",
    )
    assert result["status"] == "sent"
    assert payloads[0]["event"] == "nexus.supervisor.quarantined"
    assert payloads[0]["source"] == "supervisor"
