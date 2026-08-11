from benchmarks.provider_soak import run_soak


CONFIG = {"providers": {"alpha": {"model": "alpha-model"}, "beta": {"model": "beta-model"}}}


class FakeProvider:
    def __init__(self, name, response="ok", error=None, key=True):
        self.provider_name = name
        self.model = f"{name}-model"
        self.endpoint = "https://example.test/v1"
        self._credential_id = f"env:{name}"
        self._error = error
        self._response = response
        self._key = key

    def validate_api_key(self):
        return self._key

    def generate(self, **_kwargs):
        if self._error:
            raise self._error
        return self._response


def test_dry_run_is_stable_and_never_calls_provider():
    calls = []

    class NoCall(FakeProvider):
        def generate(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("dry-run called provider")

    report = run_soak(mode="dry-run", config=CONFIG, providers=["beta", "alpha"],
                      reps=2, provider_resolver=lambda name: NoCall(name))
    assert report["providers"] == ["alpha", "beta"]
    assert [r["status"] for r in report["records"]] == ["planned"] * 4
    assert calls == []


def test_live_run_is_explicit_and_does_not_follow_fallback():
    resolved = []
    report = run_soak(mode="live", config=CONFIG, providers=["alpha"],
                      provider_resolver=lambda name: (resolved.append(name) or FakeProvider(name)), reps=2)
    assert resolved == ["alpha", "alpha"]
    assert report["status_counts"] == {"success": 2}


def test_missing_credentials_are_auth_failed_not_success():
    report = run_soak(mode="live", config=CONFIG, providers=["alpha"],
                      provider_resolver=lambda name: FakeProvider(name, key=False))
    record = report["records"][0]
    assert record["status"] == "auth_failed"
    assert record["health"]["healthy"] is False
    assert record["attempts"][0]["status"] == "failed"


def test_auth_and_network_failures_are_classified_and_redacted():
    auth = run_soak(mode="live", config=CONFIG, providers=["alpha"],
                    provider_resolver=lambda _: FakeProvider("alpha", error=RuntimeError("401 invalid api key sk-secret-value")))
    network = run_soak(mode="live", config=CONFIG, providers=["beta"],
                       provider_resolver=lambda _: FakeProvider("beta", error=ConnectionError("connection refused")))
    assert auth["records"][0]["status"] == "auth_failed"
    assert network["records"][0]["status"] == "unavailable"
    assert "sk-secret-value" not in str(auth)


def test_live_requires_explicit_configured_provider():
    import pytest
    with pytest.raises(ValueError, match="explicit"):
        run_soak(mode="live", config=CONFIG)
    with pytest.raises(ValueError, match="not configured"):
        run_soak(mode="live", config=CONFIG, providers=["gamma"], provider_resolver=lambda _: None)


def test_live_local_provider_preflight_avoids_model_call(monkeypatch):
    calls = []

    class LocalProvider(FakeProvider):
        def __init__(self, name):
            super().__init__(name)
            self.endpoint = "http://127.0.0.1:1234/v1"

        def generate(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("unreachable local provider should not be called")

    def refused(*_args, **_kwargs):
        raise OSError("refused")

    monkeypatch.setattr("benchmarks.provider_soak.socket.create_connection", refused)
    report = run_soak(
        mode="live", config={"providers": {"local": {}}}, providers=["local"],
        provider_resolver=lambda _name: LocalProvider("local"),
    )
    assert report["records"][0]["status"] == "unavailable"
    assert report["records"][0]["reason"] == "local_server_unreachable"
    assert calls == []
