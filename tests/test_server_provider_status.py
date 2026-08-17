import apps.api


class _LocalProvider:
    endpoint = "http://127.0.0.1:1234/v1/chat/completions"


class _RemoteProvider:
    endpoint = "https://api.example.test/v1/chat/completions"


class _Factory:
    def get_provider_by_name(self, _group, name):
        return _LocalProvider() if name == "lm_studio" else _RemoteProvider()


def test_local_provider_status_reports_unreachable(monkeypatch):
    monkeypatch.setattr("models.providers.core.factory.NexusProviderFactory", lambda: _Factory())

    def refused(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(server.socket, "create_connection", refused)
    result = server._provider_reachability("lm_studio")
    assert result["configured"] is True
    assert result["reachable"] is False
    assert result["reason"] == "local_server_unreachable"


def test_remote_provider_status_defers_to_real_request(monkeypatch):
    monkeypatch.setattr("models.providers.core.factory.NexusProviderFactory", lambda: _Factory())

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


class _DiagnosticRouter:
    def provider_attempts(self):
        return [
            {"provider_id": "openai", "profile": "primary", "model": "gpt", "status": "failed",
             "failure_class": "rate_limit", "strategy": "fallback", "reason": "Bearer sk-live-secret", "timestamp": 10},
            {"provider_id": "ollama", "profile": "local", "model": "llama", "status": "success", "timestamp": 11},
        ]


class _DiagnosticBrain:
    base_router = _DiagnosticRouter()


class _DiagnosticLoop:
    brain = _DiagnosticBrain()


class _DiagnosticProfile:
    provider = "openai"
    name = "primary"
    active = True
    enabled = True
    cooldown_until = 123.0
    cooldown_reason = "rate_limit"
    error_count = 2


class _DiagnosticStore:
    def list_profiles(self):
        return [_DiagnosticProfile()]


def test_provider_diagnostics_are_bounded_and_secret_free(monkeypatch):
    monkeypatch.setattr(server, "_LOOPS", {"demo": _DiagnosticLoop()})
    monkeypatch.setattr("models.providers.core.profiles.load_profile_store", lambda: _DiagnosticStore())
    monkeypatch.setattr(server.time, "time", lambda: 100.0)

    result = server._provider_runtime_diagnostics()

    assert result["active"] == {"provider": "ollama", "profile": "local", "model": "llama"}
    assert result["fallback_attempts"] == 1
    assert result["cooldowns"][0]["cooldown_seconds"] == 23.0
    assert result["last_failure"]["failure_class"] == "rate_limit"
    assert "sk-live-secret" not in str(result)
    assert "credential_id" not in str(result)


def test_provider_list_includes_diagnostics_without_credentials(monkeypatch):
    monkeypatch.setattr(server, "_config_summary", lambda: {"providers": []})
    monkeypatch.setattr(server, "_provider_runtime_diagnostics", lambda: {
        "active": {"provider": "ollama", "profile": "local", "model": "llama"},
        "fallback_attempts": 0, "attempts": [], "cooldowns": [], "last_failure": None,
    })

    result = server.list_provider_config()

    assert "profile" in result["runtime"]
    assert result["diagnostics"]["active"]["provider"] == "ollama"
    assert "api_key" not in str(result).lower()


def test_status_endpoint_exposes_bounded_provider_diagnostics(monkeypatch):
    class Brain:
        def provider_attempts(self):
            return [{"provider_id": "openai", "status": "failed", "reason": "Bearer ***REDACTED***"}]

    class Loop:
        brain = Brain()

    monkeypatch.setattr(server, "_LOOPS", {"diagnostic": Loop()})
    monkeypatch.setattr(server, "_provider_reachability", lambda name: {"name": name, "configured": False, "reachable": None})
    result = server.get_status()
    assert result["provider_diagnostics"]["attempts"][0]["provider_id"] == "openai"
    assert result["provider_diagnostics"]["attempts"][0]["reason"] == "Bearer ***REDACTED***"
