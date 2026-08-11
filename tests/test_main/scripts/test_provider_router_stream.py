from providers.router import ModelRouter


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


class _Provider:
    def __init__(self, name, chunks):
        self.provider_name = name
        self._chunks = chunks

    @staticmethod
    def validate_api_key():
        return True

    def stream_generate(self, **_kwargs):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


class _Factory:
    def __init__(self, providers):
        self.providers = providers

    def get_provider_by_id(self, provider_id):
        return self.providers.get(provider_id)


def test_streaming_provider_error_uses_fallback_and_is_not_marked_success():
    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = _Provider("deepseek", ['Error: 401. {"error":"invalid key"}'])
    router.health = _Health()
    router.factory = _Factory({"fallback": _Provider("fallback", ["hello"] )})
    router._fallback_mesh = lambda **_kwargs: ["fallback"]

    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))

    assert result == ["hello"]
    assert router.health.failures[0][0] == "deepseek"
    assert "deepseek" not in router.health.successes
    assert router.health.successes == ["fallback"]


def test_stream_fallback_releases_lease_when_credentials_are_rejected():
    class Store:
        def __init__(self):
            self.released = []

        def release_lease(self, lease):
            self.released.append(lease)

    rejected = _Provider("fallback", [])
    rejected.validate_api_key = staticmethod(lambda: False)
    store = Store()
    rejected._profile_lease = "fallback-credential-lease"
    rejected._profile_store = store

    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = _Provider("primary", [RuntimeError("temporary outage")])
    router.health = _Health()
    router.factory = _Factory({"fallback": rejected})
    router._fallback_mesh = lambda **_kwargs: ["fallback"]

    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))

    assert result[-1].startswith("[PROVIDER_ERROR]")
    assert store.released == ["fallback-credential-lease"]
    assert not hasattr(rejected, "_profile_lease")


def test_transient_primary_stream_failure_retries_before_fallback():
    class FlakyProvider(_Provider):
        def __init__(self):
            super().__init__("primary", [])
            self.calls = 0

        def stream_generate(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("temporary connection lost")
            yield "recovered"

    from providers.reliability import CircuitBreakerRegistry, RetryPolicy

    primary = FlakyProvider()
    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = primary
    router.health = _Health()
    router.factory = _Factory({})
    router._fallback_mesh = lambda **_kwargs: []
    router._breakers = CircuitBreakerRegistry.from_config({"failure_threshold": 5})
    router.retry_policy = RetryPolicy(max_attempts=2, base_delay=0, jitter=0)

    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))

    assert result == ["recovered"]
    assert primary.calls == 2
    assert router.health.successes == ["primary"]


def test_context_overflow_stream_compacts_once_before_retry():
    class OverflowProvider(_Provider):
        def __init__(self):
            super().__init__("primary", [])
            self.calls = []

        def stream_generate(self, **kwargs):
            self.calls.append(kwargs["messages"])
            if len(self.calls) == 1:
                raise RuntimeError("413 context length exceeded")
            yield "recovered"

    from providers.reliability import CircuitBreakerRegistry, RetryPolicy

    primary = OverflowProvider()
    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = primary
    router.health = _Health()
    router.factory = _Factory({})
    router._fallback_mesh = lambda **_kwargs: []
    router._breakers = CircuitBreakerRegistry.from_config({"failure_threshold": 5})
    router.retry_policy = RetryPolicy(max_attempts=1, base_delay=0, jitter=0)
    messages = [
        {"role": "system", "content": "system " * 2000},
        {"role": "user", "content": "request " * 2000},
        {"role": "assistant", "content": "reply " * 2000},
        {"role": "user", "content": "latest " * 2000},
        {"role": "assistant", "content": "tail " * 2000},
    ]

    assert list(router.stream_generate(messages=messages)) == ["recovered"]
    assert len(primary.calls) == 2
    assert len(primary.calls[1]) < len(primary.calls[0])


def test_streaming_provider_releases_profile_lease_after_completion():
    class LeaseStore:
        def __init__(self):
            self.released = []

        def release_lease(self, lease):
            self.released.append(lease)
            return True

    primary = _Provider("primary", ["ok"])
    store = LeaseStore()
    primary._profile_lease = "stream-lease"
    primary._profile_store = store

    from providers.reliability import CircuitBreakerRegistry, RetryPolicy

    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = primary
    router.health = _Health()
    router.factory = _Factory({})
    router._fallback_mesh = lambda **_kwargs: []
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)

    assert list(router.stream_generate(messages=[{"role": "user", "content": "hello"}])) == ["ok"]
    assert store.released == ["stream-lease"]
    assert not hasattr(primary, "_profile_lease")


def test_streaming_provider_releases_profile_lease_when_consumer_closes_early():
    class LeaseStore:
        def __init__(self):
            self.released = []

        def release_lease(self, lease):
            self.released.append(lease)
            return True

    class LongProvider(_Provider):
        def stream_generate(self, **_kwargs):
            yield "first"
            yield "never consumed"

    primary = LongProvider("primary", [])
    store = LeaseStore()
    primary._profile_lease = "early-close-lease"
    primary._profile_store = store

    from providers.reliability import CircuitBreakerRegistry, RetryPolicy

    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = primary
    router.health = _Health()
    router.factory = _Factory({})
    router._fallback_mesh = lambda **_kwargs: []
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)

    stream = router.stream_generate(messages=[{"role": "user", "content": "hello"}])
    assert next(stream) == "first"
    stream.close()

    assert store.released == ["early-close-lease"]
    assert not hasattr(primary, "_profile_lease")


def test_streaming_provider_renews_an_expiring_profile_lease():
    from dataclasses import dataclass
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy

    @dataclass(frozen=True)
    class Lease:
        expires_at: float

    class LeaseStore:
        def __init__(self):
            self.renewed = []
            self.released = []

        def renew_lease(self, lease, *, ttl_seconds):
            self.renewed.append((lease, ttl_seconds))
            return Lease(expires_at=10**12)

        def release_lease(self, lease):
            self.released.append(lease)
            return True

    primary = _Provider("primary", ["ok"])
    store = LeaseStore()
    original = Lease(expires_at=0)
    primary._profile_lease = original
    primary._profile_store = store

    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = primary
    router.health = _Health()
    router.factory = _Factory({})
    router._fallback_mesh = lambda **_kwargs: []
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)

    assert list(router.stream_generate(messages=[{"role": "user", "content": "hello"}])) == ["ok"]
    assert store.renewed == [(original, 60.0)]
    assert store.released == [Lease(expires_at=10**12)]


def test_streaming_provider_stops_when_profile_lease_renewal_is_lost():
    from dataclasses import dataclass
    from providers.reliability import CircuitBreakerRegistry, RetryPolicy

    @dataclass(frozen=True)
    class Lease:
        expires_at: float

    class LeaseStore:
        def __init__(self):
            self.released = []

        def renew_lease(self, _lease, *, ttl_seconds):
            return None

        def release_lease(self, lease):
            self.released.append(lease)
            return True

    primary = _Provider("primary", ["not delivered"])
    store = LeaseStore()
    lease = Lease(expires_at=0)
    primary._profile_lease = lease
    primary._profile_store = store

    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = primary
    router.health = _Health()
    router.factory = _Factory({})
    router._fallback_mesh = lambda **_kwargs: []
    router._breakers = CircuitBreakerRegistry.from_config(None)
    router.retry_policy = RetryPolicy(max_attempts=1)

    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))
    assert result and result[-1].startswith("[PROVIDER_ERROR]:")
    assert "profile lease lost" in result[-1]
    assert store.released == [lease]


def test_partial_primary_stream_failure_does_not_splice_in_fallback_answer():
    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = _Provider("primary", ["partial", RuntimeError("connection lost")])
    router.health = _Health()
    router.factory = _Factory({"fallback": _Provider("fallback", ["different answer"])})
    router._fallback_mesh = lambda **_kwargs: ["fallback"]

    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))

    assert result[0] == "partial"
    assert result[1].startswith("[PROVIDER_ERROR]: connection lost")
    assert "different answer" not in result
    assert router.health.successes == []


def test_partial_fallback_failure_does_not_splice_in_second_fallback():
    router = object.__new__(ModelRouter)
    router.mode = "CLOUD"
    router.total_cloud_calls = 0
    router.provider = _Provider("primary", [RuntimeError("primary unavailable")])
    router.health = _Health()
    router.factory = _Factory({
        "fallback-one": _Provider("fallback-one", ["partial", RuntimeError("fallback lost")]),
        "fallback-two": _Provider("fallback-two", ["different answer"]),
    })
    router._fallback_mesh = lambda **_kwargs: ["fallback-one", "fallback-two"]

    result = list(router.stream_generate(messages=[{"role": "user", "content": "hello"}]))

    assert result[0] == "partial"
    assert result[1].startswith("[PROVIDER_ERROR]: fallback lost")
    assert "different answer" not in result
    assert router.health.successes == []
