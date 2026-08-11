from providers.router import ModelRouter


class _Health:
    def mark_failure(self, *_args):
        pass

    def mark_success(self, *_args):
        pass


class _Provider:
    provider_name = "primary"
    model = "test-model"

    @staticmethod
    def validate_api_key():
        return True

    @staticmethod
    def generate(**_kwargs):
        raise RuntimeError("https://provider.test/?api_key=sk-secret-value")


def test_model_router_records_redacted_provider_failure():
    router = object.__new__(ModelRouter)
    router.health = _Health()
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    from providers.model_capabilities import ModelCapabilityRegistry
    router._model_capabilities = ModelCapabilityRegistry()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()

    try:
        router._invoke(_Provider(), "primary", [{"role": "user", "content": "hi"}])
    except Exception:
        pass

    entries = router.provider_attempts()
    assert any(entry["status"] == "failed" for entry in entries)
    assert "sk-secret-value" not in str(entries)


def test_model_router_allows_keyless_loopback_provider():
    class LocalProvider:
        provider_name = "lm_studio"
        endpoint = "http://127.0.0.1:1234/v1/chat/completions"
        model = "local-model"

        @staticmethod
        def validate_api_key():
            return False

        @staticmethod
        def generate(**_kwargs):
            return "local response"

    router = object.__new__(ModelRouter)
    router.health = _Health()
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    from providers.model_capabilities import ModelCapabilityRegistry
    router._model_capabilities = ModelCapabilityRegistry()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()

    assert router._provider_credentials_usable(LocalProvider(), "lm_studio") is True
    assert router._invoke(LocalProvider(), "lm_studio", [{"role": "user", "content": "hi"}]) == "local response"


def test_model_router_releases_profile_lease_after_successful_call():
    class LeaseStore:
        def __init__(self):
            self.released = []

        def release_lease(self, lease):
            self.released.append(lease)
            return True

    provider = type("LeasedProvider", (), {
        "provider_name": "primary",
        "model": "test-model",
        "validate_api_key": staticmethod(lambda: True),
        "generate": staticmethod(lambda **_kwargs: "ok"),
    })()
    store = LeaseStore()
    provider._profile_lease = "lease-token"
    provider._profile_store = store

    router = object.__new__(ModelRouter)
    router.health = _Health()
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    from providers.model_capabilities import ModelCapabilityRegistry
    router._model_capabilities = ModelCapabilityRegistry()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()

    assert router._invoke(provider, "primary", [{"role": "user", "content": "hi"}]) == "ok"
    assert store.released == ["lease-token"]
    assert not hasattr(provider, "_profile_lease")
    assert not hasattr(provider, "_profile_store")


def test_model_router_filters_model_limits_for_strict_provider_signature():
    calls = []

    class StrictProvider:
        provider_name = "primary"
        model = "test-model"

        @staticmethod
        def validate_api_key():
            return True

        @staticmethod
        def generate(messages):
            calls.append(messages)
            return "ok"

    router = object.__new__(ModelRouter)
    router.health = _Health()
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    from providers.model_capabilities import ModelCapabilityRegistry
    router._model_capabilities = ModelCapabilityRegistry()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()

    assert router._invoke(
        StrictProvider(), "primary", [{"role": "user", "content": "hi"}],
        max_tokens=128, timeout=3,
    ) == "ok"
    assert len(calls) == 1


def test_model_router_does_not_repeat_internal_type_error():
    calls = []

    class BuggyProvider:
        provider_name = "primary"
        model = "test-model"

        @staticmethod
        def validate_api_key():
            return True

        @staticmethod
        def generate(**_kwargs):
            calls.append(True)
            raise TypeError("adapter internal bug")

    router = object.__new__(ModelRouter)
    router.health = _Health()
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    from providers.model_capabilities import ModelCapabilityRegistry
    router._model_capabilities = ModelCapabilityRegistry()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()

    try:
        router._invoke(BuggyProvider(), "primary", [{"role": "user", "content": "hi"}])
    except Exception:
        pass
    assert calls == [True]


def test_model_router_releases_profile_lease_after_failed_call():
    class LeaseStore:
        def __init__(self):
            self.released = []

        def release_lease(self, lease):
            self.released.append(lease)
            return True

    provider = _Provider()
    store = LeaseStore()
    provider._profile_lease = "failed-lease"
    provider._profile_store = store

    router = object.__new__(ModelRouter)
    router.health = _Health()
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    from providers.model_capabilities import ModelCapabilityRegistry
    router._model_capabilities = ModelCapabilityRegistry()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()

    try:
        router._invoke(provider, "primary", [{"role": "user", "content": "hi"}])
    except Exception:
        pass

    assert store.released == ["failed-lease"]
    assert not hasattr(provider, "_profile_lease")


def test_model_router_releases_profile_lease_when_credentials_are_rejected():
    class LeaseStore:
        def __init__(self):
            self.released = []

        def release_lease(self, lease):
            self.released.append(lease)
            return True

    provider = _Provider()
    store = LeaseStore()
    provider._profile_lease = "credential-rejected-lease"
    provider._profile_store = store

    router = object.__new__(ModelRouter)
    router.health = _Health()
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)
    from providers.model_capabilities import ModelCapabilityRegistry
    router._model_capabilities = ModelCapabilityRegistry()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()
    router._provider_credentials_usable = lambda *_args: False

    try:
        router._invoke(provider, "primary", [{"role": "user", "content": "hi"}])
    except Exception:
        pass

    assert store.released == ["credential-rejected-lease"]
    assert not hasattr(provider, "_profile_lease")


def test_model_router_compacts_once_before_context_overflow_fallback():
    from providers.reliability import Classification, FailureClass, Strategy

    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.provider = object()
    router.factory = object()
    router.total_cloud_calls = 0
    router.health = _Health()
    router.attempts = __import__("providers.attempts", fromlist=["ProviderAttemptRecorder"]).ProviderAttemptRecorder()
    router._should_use_heavy_brain = lambda _messages: True
    router._fallback_mesh = lambda **_kwargs: []
    calls = []

    def invoke(_provider, _provider_id, messages, **_kwargs):
        calls.append(messages)
        if len(calls) == 1:
            raise __import__("providers.reliability", fromlist=["ProviderCallError"]).ProviderCallError(
                Classification(
                    failure_class=FailureClass.CONTEXT_OVERFLOW,
                    retryable=False,
                    strategy=Strategy.FALLBACK_MODEL,
                    message="context window exceeded",
                ),
                "primary",
            )
        return "recovered after compaction"

    router._invoke = invoke
    messages = [
        {"role": "system", "content": "system " * 2000},
        {"role": "user", "content": "request " * 2000},
        {"role": "assistant", "content": "reply " * 2000},
        {"role": "user", "content": "latest " * 2000},
        {"role": "assistant", "content": "tail " * 2000},
    ]

    result = router.generate(messages=messages)

    assert result == "recovered after compaction"
    assert len(calls) == 2
    assert len(calls[1]) < len(calls[0])
    assert calls[0] == messages
