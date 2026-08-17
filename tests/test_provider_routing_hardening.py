"""Provider routing / fallback / reliability hardening regression tests.

All tests are offline and deterministic: clients, factories and providers are
monkeypatched or built via ``object.__new__`` — no network, no sleeps beyond
tiny retry budgets.

Covers:
- factory ``default_provider: auto`` resolution (keyless running locals first,
  keyed remotes second, useful diagnostic when nothing is available)
- ``NEXUS_PROVIDER`` / ``NEXUS_MODEL`` env overrides at the factory entry path
- retry wall-clock budget in ``call_with_reliability`` (sync + async), so
  retries respect the caller's timeout budget and total time stays bounded
- per-provider fallback diagnostics (provider id, model, failure class,
  elapsed, redacted) plus skipped-attempt telemetry in the router mesh
- profile-lease release on early generator close for non-stream adapters
- model_bench empty-config safety, tier hard-filtering, malformed annotations
"""

import asyncio
import time

import pytest

from providers.factory import NexusProviderFactory
from providers.model_bench import rank_models, score_model
from providers.reliability import (
    Classification,
    FailureClass,
    ProviderCallError,
    RetryPolicy,
    Strategy,
    call_with_reliability,
    classify_failure,
)
from providers.router import ModelRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Health:
    def __init__(self):
        self.failures = []
        self.successes = []

    def mark_failure(self, provider, error):
        self.failures.append((provider, str(error)))

    def mark_success(self, provider, _latency):
        self.successes.append(provider)

    @staticmethod
    def normalize_error(error):
        return str(error)


class _FakeLoader:
    def __init__(self, cfg):
        self._cfg = cfg

    def get(self, _key, default=None):
        return self._cfg


def _factory(monkeypatch, cfg, available, providers_by_name, env_model=""):
    """Build a fresh (non-singleton) factory with fakes injected."""
    from providers import auto_detect

    monkeypatch.setattr(
        auto_detect, "detect_available_providers", lambda: dict(available)
    )
    monkeypatch.setattr(NexusProviderFactory, "_auto_health", lambda self: None)
    factory = object.__new__(NexusProviderFactory)
    factory.loader = _FakeLoader(cfg)
    factory.group = "cloud"
    factory.name = str(cfg.get("default_provider") or "")
    factory._consecutive_errors = 0
    factory._provider = None
    factory.get_provider_by_name = providers_by_name
    if env_model:
        monkeypatch.setenv("NEXUS_MODEL", env_model)
    return factory


def _router(monkeypatch, **overrides):
    from providers.attempts import ProviderAttemptRecorder
    from providers.reliability import CircuitBreakerRegistry

    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.health = _Health()
    router.attempts = ProviderAttemptRecorder()
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    attrs = {
        "provider": None,
        "factory": None,
        "last_failure": None,
        "_fallback_mesh": lambda **_kwargs: [],
    }
    attrs.update(overrides)
    for name, value in attrs.items():
        setattr(router, name, value)
    return router


class _LeaseStore:
    def __init__(self):
        self.released = []

    def release_lease(self, lease):
        self.released.append(lease)
        return True


# ---------------------------------------------------------------------------
# (a) factory auto resolution + env overrides
# ---------------------------------------------------------------------------

def test_factory_auto_prefers_running_keyless_local(monkeypatch):
    local = type("Local", (), {
        "provider_name": "lm_studio",
        "endpoint": "http://127.0.0.1:1234/v1/chat/completions",
        "model": "",
        "api_key": "",
        "validate_api_key": staticmethod(lambda: True),
    })()
    remote = type("Remote", (), {
        "provider_name": "openai",
        "endpoint": "https://api.openai.com",
        "model": "gpt-4o",
        "api_key": "sk-abc123",
        "validate_api_key": staticmethod(lambda: True),
    })()
    factory = _factory(
        monkeypatch,
        cfg={"default_provider": "auto", "fallback_chain": []},
        available={"openai": "sk-abc123", "lm_studio": "__local__"},
        providers_by_name=lambda _group, name: local if name == "lm_studio" else remote,
    )
    assert factory.get_provider() is local


def test_factory_auto_falls_back_to_keyed_remote(monkeypatch):
    remote = type("Remote", (), {
        "provider_name": "deepseek",
        "endpoint": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "sk-abc123",
        "validate_api_key": staticmethod(lambda: True),
    })()
    factory = _factory(
        monkeypatch,
        cfg={"default_provider": "auto", "fallback_chain": []},
        available={"deepseek": "sk-abc123"},
        providers_by_name=lambda _group, name: remote if name == "deepseek" else None,
    )
    assert factory.get_provider() is remote


def test_factory_auto_returns_none_and_logs_diagnostic(monkeypatch, caplog):
    bad = type("Bad", (), {
        "provider_name": "openai",
        "endpoint": "https://api.openai.com",
        "model": "",
        "api_key": "",
        "validate_api_key": staticmethod(lambda: False),
    })()
    factory = _factory(
        monkeypatch,
        cfg={"default_provider": "auto", "fallback_chain": []},
        available={"openai": "sk-abc123"},
        providers_by_name=lambda _group, name: bad if name == "openai" else None,
    )
    with caplog.at_level("WARNING", logger="providers.factory"):
        assert factory.get_provider() is None
    assert "auto" in caplog.text
    assert "openai" in caplog.text
    assert "no usable credential" in caplog.text


def test_factory_env_provider_override_wins_over_config(monkeypatch):
    chosen = type("EnvProvider", (), {
        "provider_name": "openrouter",
        "endpoint": "https://openrouter.ai",
        "model": "configured-model",
        "api_key": "sk-abc123",
        "validate_api_key": staticmethod(lambda: True),
    })()
    factory = _factory(
        monkeypatch,
        cfg={"default_provider": "deepseek", "fallback_chain": []},
        available={},
        providers_by_name=lambda _group, name: chosen if name == "openrouter" else None,
        env_model="env-model-42",
    )
    monkeypatch.setenv("NEXUS_PROVIDER", "openrouter")
    assert factory.get_provider() is chosen
    assert chosen.model == "env-model-42"


def test_factory_offline_auto_rejects_remote_only(monkeypatch):
    remote = type("Remote", (), {
        "provider_name": "openai",
        "endpoint": "https://api.openai.com",
        "model": "",
        "api_key": "sk-abc123",
        "validate_api_key": staticmethod(lambda: True),
    })()
    factory = _factory(
        monkeypatch,
        cfg={"default_provider": "auto", "fallback_chain": []},
        available={"openai": "sk-abc123"},
        providers_by_name=lambda _group, name: remote if name == "openai" else None,
    )
    monkeypatch.setenv("NEXUS_OFFLINE_MODE", "1")
    assert factory.get_provider() is None


def test_factory_auto_with_health_degraded_skips_provider(monkeypatch):
    class _DegradedHealth:
        def is_degraded(self, provider_id):
            return provider_id == "openai"

    degraded = type("Remote", (), {
        "provider_name": "openai",
        "endpoint": "https://api.openai.com",
        "model": "",
        "api_key": "sk-abc123",
        "validate_api_key": staticmethod(lambda: True),
    })()
    healthy = type("Healthy", (), {
        "provider_name": "groq",
        "endpoint": "https://api.groq.com",
        "model": "",
        "api_key": "sk-abc123",
        "validate_api_key": staticmethod(lambda: True),
    })()
    monkeypatch.setattr(
        NexusProviderFactory, "_auto_health", lambda self: _DegradedHealth()
    )
    from providers import auto_detect

    monkeypatch.setattr(
        auto_detect, "detect_available_providers",
        lambda: {"openai": "sk-abc123", "groq": "sk-abc123"},
    )
    factory = object.__new__(NexusProviderFactory)
    factory.loader = _FakeLoader({"default_provider": "auto", "fallback_chain": []})
    factory.group = "cloud"
    factory.name = "auto"
    factory._consecutive_errors = 0
    factory._provider = None
    factory.get_provider_by_name = (
        lambda _group, name: degraded if name == "openai" else healthy
    )
    assert factory.get_provider() is healthy


# ---------------------------------------------------------------------------
# (f) retry wall-clock budget
# ---------------------------------------------------------------------------

def test_retry_budget_bounds_sync_retry_time():
    calls = {"n": 0}

    def flaky(**_kwargs):
        calls["n"] += 1
        raise ConnectionError("transient")

    start = time.monotonic()
    with pytest.raises(ProviderCallError):
        call_with_reliability(
            "prov",
            flaky,
            policy=RetryPolicy(max_attempts=5, base_delay=10.0, jitter=0.0),
            timeout=0.05,
        )
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"retries blew the budget: {elapsed:.2f}s"
    assert calls["n"] < 5, "budget did not cut the retry attempts"


def test_retry_budget_caps_retry_after():
    def rate_limited(**_kwargs):
        raise ProviderCallError(
            Classification(
                failure_class=FailureClass.RATE_LIMIT,
                retryable=True,
                strategy=Strategy.BACKOFF,
                retry_after=10.0,
                message="429 too many requests",
            ),
            "prov",
        )

    start = time.monotonic()
    with pytest.raises(ProviderCallError):
        call_with_reliability(
            "prov",
            rate_limited,
            policy=RetryPolicy(max_attempts=4, jitter=0.0),
            timeout=0.15,
        )
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"Retry-After exceeded the budget: {elapsed:.2f}s"


async def test_retry_budget_cancels_inflight_async_attempt():
    calls = {"n": 0}

    async def slow(**_kwargs):
        calls["n"] += 1
        await asyncio.sleep(30)
        return "too slow"

    start = time.monotonic()
    with pytest.raises(ProviderCallError):
        await call_with_reliability(
            "prov",
            slow,
            policy=RetryPolicy(max_attempts=3, base_delay=0.1, jitter=0.0),
            timeout=0.1,
        )
    assert time.monotonic() - start < 2.0
    assert calls["n"] == 1, "a cancelled in-flight attempt must not be retried"


async def test_retry_budget_still_propagates_cancellation():
    calls = {"n": 0}

    async def cancelled(**_kwargs):
        calls["n"] += 1
        raise asyncio.CancelledError("operator stopped")

    with pytest.raises(asyncio.CancelledError):
        await call_with_reliability(
            "prov",
            cancelled,
            policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter=0.0),
            timeout=1.0,
        )
    assert calls["n"] == 1


def test_classify_auth_not_retried_but_transient_retried():
    assert classify_failure(body="401 invalid api key").retryable is False
    assert classify_failure(body="403 forbidden").retryable is False
    assert classify_failure(body="HTTP error 400 bad request").retryable is False
    assert classify_failure(body="error 422 unprocessable").retryable is False
    assert classify_failure(body="429 too many requests").retryable is True
    assert classify_failure(body="connection reset").retryable is True
    assert classify_failure(body="request timed out").retryable is True


# ---------------------------------------------------------------------------
# (b/g) fallback mesh diagnostics + attempt telemetry
# ---------------------------------------------------------------------------

def test_fallback_mesh_surfaces_per_provider_diagnostics():
    def fake_invoke(provider, provider_id, messages, **kwargs):
        if provider_id == "openrouter":
            raise ProviderCallError(classify_failure(body="429 rate limit"), provider_id)
        raise RuntimeError("connection lost")

    router = _router(
        monkeypatch=None,
        provider=None,
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: object())})(),
        _invoke=fake_invoke,
    )

    result = router._generate_with_fallbacks(
        [{"role": "user", "content": "hi"}],
        ["openrouter", "gemini"],
        model="test-model",
    )
    assert result.startswith("Error: ")
    assert "openrouter" in result and "rate_limit" in result
    assert "gemini" in result and "network_error" in result
    assert "test-model" in result
    assert "0.0s" in result


def test_fallback_diagnostics_never_embed_api_keys(monkeypatch):
    def fake_invoke(provider, provider_id, messages, **kwargs):
        raise RuntimeError("https://provider.test/?api_key=sk-secret-value")

    router = _router(
        monkeypatch=monkeypatch,
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: object())})(),
        _invoke=fake_invoke,
    )
    result = router._generate_with_fallbacks(
        [{"role": "user", "content": "hi"}], ["openrouter"]
    )
    assert "sk-secret-value" not in result


def test_fallback_circuit_open_records_skipped_attempt_and_bounds_loop(monkeypatch):
    from providers.reliability import CircuitBreakerRegistry

    router = _router(
        monkeypatch=monkeypatch,
        _breakers=CircuitBreakerRegistry.from_config(None),
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: object())})(),
        _invoke=lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("unreachable: breaker must block the call")
        ),
    )
    breaker = router.breakers.get("openrouter")
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()

    result = router._generate_with_fallbacks(
        [{"role": "user", "content": "hi"}],
        ["openrouter", "openrouter", "openrouter"],
    )
    assert "circuit open" in result
    assert result.count("circuit open") == 3  # one diagnostic per mesh entry
    entries = router.provider_attempts()
    assert any(e["status"] == "skipped" and e["reason"] == "circuit open" for e in entries)


def test_fallback_mesh_success_records_and_returns():
    calls = []

    def fake_invoke(provider, provider_id, messages, **kwargs):
        calls.append(provider_id)
        return "ok"

    router = _router(
        monkeypatch=None,
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: object())})(),
        _invoke=fake_invoke,
    )
    result = router._generate_with_fallbacks(
        [{"role": "user", "content": "hi"}],
        ["openrouter", "gemini"],
        model="m",
    )
    assert result == "ok"
    assert calls == ["openrouter"]  # first viable provider wins; no unbounded loop
    entries = router.provider_attempts()
    assert any(e["status"] == "fallback" for e in entries)


def test_fallback_all_failed_still_bounded_no_infinite_loop(monkeypatch):
    def fake_invoke(provider, provider_id, messages, **kwargs):
        raise ProviderCallError(classify_failure(body="503 temporarily"), provider_id)

    router = _router(
        monkeypatch=monkeypatch,
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: object())})(),
        _invoke=fake_invoke,
    )
    mesh = [f"provider-{i}" for i in range(5)]
    result = router._generate_with_fallbacks(
        [{"role": "user", "content": "hi"}], mesh, model="m"
    )
    assert result.startswith("Error: ")
    for pid in mesh:
        assert pid in result
    entries = router.provider_attempts()
    assert len([e for e in entries if e["status"] == "fallback"]) == 5


# ---------------------------------------------------------------------------
# (c) stream lease release for non-stream adapters + payload diagnostics
# ---------------------------------------------------------------------------

def test_stream_releases_lease_when_consumer_closes_nonstream_adapter():
    class NonStreamProvider:
        provider_name = "primary"
        model = "test-model"

        @staticmethod
        def validate_api_key():
            return True

        @staticmethod
        def generate(**_kwargs):
            return "full answer"

    primary = NonStreamProvider()
    store = _LeaseStore()
    primary._profile_lease = "nonstream-lease"
    primary._profile_store = store

    router = _router(
        monkeypatch=None,
        provider=primary,
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: None)})(),
    )
    stream = router.stream_generate(messages=[{"role": "user", "content": "hello"}])
    assert next(stream) == "full answer"
    stream.close()

    assert store.released == ["nonstream-lease"]
    assert not hasattr(primary, "_profile_lease")


def test_stream_error_payload_includes_provider_class_and_elapsed(monkeypatch):
    class PartialProvider:
        provider_name = "primary"
        model = "test-model"

        @staticmethod
        def validate_api_key():
            return True

        def stream_generate(self, **_kwargs):
            yield "partial"
            raise RuntimeError("connection lost")

    router = _router(
        monkeypatch=monkeypatch,
        provider=PartialProvider(),
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: None)})(),
    )
    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))

    assert result[0] == "partial"
    assert result[1].startswith("[PROVIDER_ERROR]: connection lost")
    assert "primary" in result[1]
    assert "network_error" in result[1]
    assert "0.0s" in result[1]


def test_stream_fallback_error_payload_identifies_failing_provider(monkeypatch):
    class FallbackProvider:
        provider_name = "fallback-one"
        model = ""

        @staticmethod
        def validate_api_key():
            return True

        def stream_generate(self, **_kwargs):
            yield "partial"
            raise RuntimeError("fallback lost")

    router = _router(
        monkeypatch=monkeypatch,
        provider=type("P", (), {
            "provider_name": "primary",
            "model": "",
            "validate_api_key": staticmethod(lambda: True),
            "stream_generate": staticmethod(lambda **_: (_ for _ in ()).throw(RuntimeError("primary unavailable"))),
        })(),
        factory=type("F", (), {"get_provider_by_id": staticmethod(lambda pid: FallbackProvider())})(),
        _fallback_mesh=lambda **_kwargs: ["fallback-one", "fallback-two"],
    )
    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))

    assert result[0] == "partial"
    assert result[1].startswith("[PROVIDER_ERROR]: fallback lost")
    assert "fallback-one" in result[1]


# ---------------------------------------------------------------------------
# (e) model_bench empty config / tier filtering / malformed annotations
# ---------------------------------------------------------------------------

def test_rank_models_empty_and_missing_annotations_are_safe():
    assert rank_models("coding", []) == ["deepseek"]  # deterministic fallback
    assert score_model("chat", None) == 0.0
    assert score_model(None, "openai") == 0.0
    assert rank_models("chat", ["mystery-provider"]) == ["mystery-provider"]


def test_fast_tier_excludes_high_cost_and_high_latency():
    annotations = {
        "cheap": {"cost_per_1m": 0.3, "latency_ms": 800, "quality": 0.6},
        "pricey": {"cost_per_1m": 8.0, "latency_ms": 400, "quality": 0.9},
        "slow": {"cost_per_1m": 0.3, "latency_ms": 15000, "quality": 0.9},
    }
    fast = rank_models("chat", ["cheap", "pricey", "slow"], annotations=annotations, tier="fast")
    assert fast == ["cheap"]
    balanced = rank_models("chat", ["cheap", "pricey", "slow"], annotations=annotations, tier="balanced")
    assert "pricey" in balanced
    quality = rank_models("chat", ["cheap", "pricey", "slow"], annotations=annotations, tier="quality")
    assert set(quality) == {"cheap", "pricey", "slow"}


def test_rank_models_ignores_malformed_annotations_without_raising():
    annotations = {"weird": {"cost_per_1m": "very expensive", "latency_ms": None}}
    result = rank_models("chat", ["weird"], annotations=annotations, tier="fast")
    assert result == ["weird"]  # relaxed best-score ordering still yields a mesh


def test_fast_tier_filters_real_provider_yml_annotations():
    from providers.model_bench import _provider_annotations

    openrouter = _provider_annotations("openrouter")
    if not openrouter.get("cost_per_1m"):
        pytest.skip("provider.yml model_capabilities annotations not present")
    ranked = rank_models("coding", ["deepseek", "openrouter"], tier="fast")
    assert "deepseek" in ranked
    assert "openrouter" not in ranked  # cost 2.5 > fast tier cap of 1.5
