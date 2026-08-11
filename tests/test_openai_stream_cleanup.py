import pytest


def test_openai_http_stream_closes_response_on_completion(monkeypatch):
    from providers.openai import OpenAIProvider

    class Response:
        status_code = 200
        text = ""

        def __init__(self):
            self.closed = False

        def iter_lines(self, **_kwargs):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield b"data: [DONE]"

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        def post(self, *args, **kwargs):
            return response

    provider = object.__new__(OpenAIProvider)
    provider.model = "test-model"
    provider.endpoint = "https://provider.test/v1/chat/completions"
    provider.headers = {}
    provider.session = Session()
    monkeypatch.setattr(provider, "request_timeout", lambda *_args, **_kwargs: 30)

    assert list(provider.stream_generate("hello")) == ["ok"]
    assert response.closed is True


@pytest.mark.parametrize(
    "module_name,class_name",
    [
        ("providers.groq", "GroqProvider"),
        ("providers.xai", "XAIProvider"),
        ("providers.together", "TogetherProvider"),
        ("providers.fireworks", "FireworksProvider"),
        ("providers.mistral", "MistralProvider"),
        ("providers.lm_studio", "LMStudioProvider"),
        ("providers.universal", "UniversalProvider"),
        ("providers.qwen", "QwenProvider"),
        ("providers.perplexity", "PerplexityProvider"),
        ("providers.sambanova", "SambaNovaProvider"),
        ("providers.azure_openai", "AzureOpenAIProvider"),
        ("providers.cohere", "CohereProvider"),
        ("providers.nvidia", "NvidiaProvider"),
    ],
)
def test_openai_compatible_stream_adapters_close_response(monkeypatch, module_name, class_name):
    module = __import__(module_name, fromlist=[class_name])
    provider_class = getattr(module, class_name)

    class Response:
        status_code = 200
        text = ""
        closed = False

        def iter_lines(self, **_kwargs):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield b"data: [DONE]"

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        def post(self, *args, **kwargs):
            return response

    provider = object.__new__(provider_class)
    provider.model = "test-model"
    provider.endpoint = "https://provider.test/v1/chat/completions"
    provider.deployment = "test-deployment"
    provider.api_version = "2024-01-01"
    provider.api_key = "test-key"
    provider.provider_name = "test-provider"
    provider.headers = {}
    provider.session = Session()
    monkeypatch.setattr(provider, "request_timeout", lambda *_args, **_kwargs: 30)
    if class_name == "AzureOpenAIProvider":
        monkeypatch.setattr(provider, "validate_api_key", lambda: True)

    result = list(provider.stream_generate("hello"))
    if class_name != "CohereProvider":
        assert result == ["ok"]
    assert response.closed is True


def test_deepseek_http_stream_closes_response_on_completion(monkeypatch):
    from providers.deepseek import DeepSeekProvider

    class Response:
        status_code = 200
        text = ""
        closed = False

        def iter_lines(self, **_kwargs):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield b"data: [DONE]"

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        def post(self, *args, **kwargs):
            return response

    provider = object.__new__(DeepSeekProvider)
    provider.model = "test-model"
    provider.endpoint = "https://provider.test/v1/chat/completions"
    provider.headers = {}
    provider.session = Session()
    provider.api_key = "test-key"
    monkeypatch.setattr(provider, "validate_api_key", lambda: True)
    monkeypatch.setattr(provider, "request_timeout", lambda *_args, **_kwargs: 30)

    assert list(provider.stream_generate("hello")) == ["ok"]
    assert response.closed is True


def test_anthropic_http_stream_closes_response_on_completion(monkeypatch):
    from providers.anthropic import AnthropicProvider

    class Response:
        status_code = 200
        text = ""
        closed = False

        def iter_lines(self):
            yield b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}'
            yield b'data: {"type":"message_stop"}'

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        def post(self, *args, **kwargs):
            return response

    provider = object.__new__(AnthropicProvider)
    provider.model = "test-model"
    provider.endpoint = "https://provider.test/v1/messages"
    provider.headers = {}
    provider.session = Session()
    monkeypatch.setattr(provider, "request_timeout", lambda *_args, **_kwargs: 30)

    assert list(provider.stream_generate("hello")) == ["ok"]
    assert response.closed is True


def test_gemini_http_stream_closes_response_on_completion(monkeypatch):
    from providers.google_gemini import GoogleGeminiProvider

    class Response:
        status_code = 200
        closed = False

        def iter_lines(self):
            yield b'[ {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]} ]'

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        def post(self, *args, **kwargs):
            return response

    provider = object.__new__(GoogleGeminiProvider)
    provider.session = Session()
    provider.headers = {}
    monkeypatch.setattr(provider, "_payload", lambda *args: {})
    monkeypatch.setattr(provider, "_request_model", lambda *_args: "test-model")
    monkeypatch.setattr(provider, "_endpoint_for_model", lambda *args, **kwargs: "https://provider.test")
    monkeypatch.setattr(provider, "request_timeout", lambda *_args, **_kwargs: 30)

    assert list(provider.stream_generate("hello")) == ["ok"]
    assert response.closed is True


def test_ollama_http_stream_closes_response_on_completion(monkeypatch):
    from providers.ollama import OllamaProvider

    class Response:
        status_code = 200
        closed = False

        def iter_lines(self):
            yield b'{"message":{"content":"ok"},"done":true}'

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        def post(self, *args, **kwargs):
            return response

    provider = object.__new__(OllamaProvider)
    provider.model = "test-model"
    provider.endpoint = "http://provider.test/api/chat"
    provider.session = Session()
    provider.headers = {}
    monkeypatch.setattr(provider, "request_timeout", lambda *_args, **_kwargs: 30)

    assert list(provider.stream_generate("hello")) == ["ok"]
    assert response.closed is True
