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
