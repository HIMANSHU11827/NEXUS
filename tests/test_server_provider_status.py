import server


class _LocalProvider:
    endpoint = "http://127.0.0.1:1234/v1/chat/completions"


class _RemoteProvider:
    endpoint = "https://api.example.test/v1/chat/completions"


class _Factory:
    def get_provider_by_name(self, _group, name):
        return _LocalProvider() if name == "lm_studio" else _RemoteProvider()


def test_local_provider_status_reports_unreachable(monkeypatch):
    monkeypatch.setattr("providers.factory.NexusProviderFactory", lambda: _Factory())

    def refused(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(server.socket, "create_connection", refused)
    result = server._provider_reachability("lm_studio")
    assert result["configured"] is True
    assert result["reachable"] is False
    assert result["reason"] == "local_server_unreachable"


def test_remote_provider_status_defers_to_real_request(monkeypatch):
    monkeypatch.setattr("providers.factory.NexusProviderFactory", lambda: _Factory())

    def fail_if_probed(*_args, **_kwargs):
        raise AssertionError("remote provider should not be probed")

    monkeypatch.setattr(server.socket, "create_connection", fail_if_probed)
    result = server._provider_reachability("openrouter")
    assert result == {
        "name": "openrouter",
        "configured": True,
        "reachable": None,
        "reason": "remote_probe_deferred",
    }


def test_status_endpoint_exposes_provider_reachability(monkeypatch):
    monkeypatch.setattr(server, "_provider_reachability", lambda name: {
        "name": name,
        "configured": True,
        "reachable": False,
        "reason": "local_server_unreachable",
        "endpoint": "http://127.0.0.1:1234/v1/chat/completions",
    })
    monkeypatch.setitem(server._RUNTIME_SETTINGS, "provider", "lm_studio")

    result = server.get_status()

    assert result["health"] == "degraded"
    assert result["provider_status"]["name"] == "lm_studio"
    assert result["provider_status"]["reachable"] is False
