from intelligence.moe_router import NexusMoERouter


class _Provider:
    def __init__(self, chunks, usage=None):
        self._chunks = chunks
        self._last_usage = usage
        self.model = "default-model"
        self.kwargs = {}

    def stream_generate(self, **kwargs):
        self.kwargs = kwargs
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


class _Factory:
    def __init__(self):
        self.providers = {
            "deepseek": _Provider(['Error: 401. {"error":"invalid key"}']),
            "fallback": _Provider(["hello"]),
        }

    def get_provider_by_name(self, _group, name, profile=None):
        return self.providers.get(name)

    @staticmethod
    def next_profile_fallback(_provider, _profile):
        return None

    @staticmethod
    def next_provider_fallback(provider):
        return "fallback" if provider == "deepseek" else None


def test_stream_auth_error_is_not_emitted_and_falls_back():
    router = object.__new__(NexusMoERouter)
    router.factory = _Factory()
    router.provider_override = "deepseek"
    router.profile_override = ""
    router._load_task_routing = lambda: {}

    result = list(router.stream_generate([{"role": "user", "content": "hello"}]))

    assert result == ["hello"]


def test_provider_error_classifier_handles_split_auth_response():
    router = object.__new__(NexusMoERouter)

    assert router._is_provider_error('Error: 401. {"error":{"message":"Authentication Fails"}}')
    assert router._looks_like_provider_error("[PROVIDER_ERROR]: All providers unavailable")
    assert not router._is_provider_error("A normal assistant response")


def test_exhausted_fallbacks_emit_provider_error_contract():
    router = object.__new__(NexusMoERouter)
    router.factory = _Factory()
    router.factory.providers["fallback"] = _Provider(["Error: fallback unavailable"])
    router.provider_override = "deepseek"
    router.profile_override = ""
    router._load_task_routing = lambda: {}

    result = list(router.stream_generate([{"role": "user", "content": "hello"}]))

    assert len(result) == 1
    assert result[0].startswith("[PROVIDER_ERROR]: All providers unavailable")


def test_run_scoped_provider_model_and_token_overrides_are_forwarded():
    router = object.__new__(NexusMoERouter)
    router.factory = _Factory()
    router.provider_override = "deepseek"
    router.profile_override = ""
    router._load_task_routing = lambda: {}

    result = list(router.stream_generate(
        [{"role": "user", "content": "hello"}],
        provider="fallback",
        model="chosen-model",
        max_tokens=123,
    ))

    selected = router.factory.providers["fallback"]
    assert result == ["hello"]
    assert selected.model == "chosen-model"
    assert selected.kwargs["max_tokens"] == 123
    assert router.provider_override == "deepseek"


def test_moe_router_exposes_provider_usage_after_stream():
    router = object.__new__(NexusMoERouter)
    router.factory = _Factory()
    router.factory.providers["deepseek"] = _Provider(
        ["hello"], {"prompt_tokens": 14, "completion_tokens": 3}
    )
    router.provider_override = "deepseek"
    router.profile_override = ""
    router._load_task_routing = lambda: {}

    assert list(router.stream_generate([{"role": "user", "content": "hello"}])) == ["hello"]
    assert router._last_usage == {"prompt_tokens": 14, "completion_tokens": 3}


def test_partial_stream_failure_does_not_mix_provider_answers():
    router = object.__new__(NexusMoERouter)
    router.factory = _Factory()
    router.factory.providers["deepseek"] = _Provider(["partial", RuntimeError("connection lost")])
    router.provider_override = "deepseek"
    router.profile_override = ""
    router._load_task_routing = lambda: {}

    result = list(router.stream_generate([{"role": "user", "content": "hello"}]))

    assert result[0] == "partial"
    assert result[1].startswith("[PROVIDER_ERROR]: connection lost")
    assert "hello" not in result


def test_offline_local_failure_is_clear_and_does_not_claim_remote_fallback():
    router = object.__new__(NexusMoERouter)
    router.factory = _Factory()
    router.factory.providers["lm_studio"] = _Provider(["Error: LM Studio not reachable"])
    router.factory.offline_mode = lambda: True
    router.factory.next_provider_fallback = lambda _provider: None
    router.provider_override = "lm_studio"
    router.profile_override = ""
    router._load_task_routing = lambda: {}

    result = list(router.stream_generate([{"role": "user", "content": "hello"}]))

    assert result == [
        "[PROVIDER_ERROR]: LM Studio is not reachable. Start the local server and load a model, then retry."
    ]
