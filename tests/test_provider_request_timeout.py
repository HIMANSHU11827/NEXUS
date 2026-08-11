import pytest

from providers.anthropic import AnthropicProvider
from providers.deepseek import DeepSeekProvider
from providers.google_gemini import GoogleGeminiProvider
from providers.groq import GroqProvider
from providers.openai import OpenAIProvider


class _Response:
    status_code = 500
    text = "test provider failure"

    def json(self):
        return {}


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _Response()


def _provider(provider_type):
    provider = object.__new__(provider_type)
    provider.session = _Session()
    provider.endpoint = "https://provider.test/v1"
    provider.headers = {}
    provider.model = "test-model"
    provider.api_key = "test-key"
    if provider_type is GoogleGeminiProvider:
        provider._endpoint_for_model = lambda _model, streaming=False: "https://provider.test/gemini"
    if provider_type is DeepSeekProvider:
        provider.validate_api_key = lambda: True
    return provider


@pytest.mark.parametrize(
    "provider_type",
    [OpenAIProvider, AnthropicProvider, GoogleGeminiProvider, GroqProvider, DeepSeekProvider],
)
def test_unary_provider_adapters_honor_router_timeout(provider_type):
    provider = _provider(provider_type)
    provider.generate(messages=[{"role": "user", "content": "hello"}], timeout=4.25)

    assert provider.session.calls
    assert provider.session.calls[0][1]["timeout"] == 4.25


@pytest.mark.parametrize("provider_type", [OpenAIProvider, AnthropicProvider, GroqProvider, DeepSeekProvider])
def test_streaming_provider_adapters_honor_router_timeout(provider_type):
    provider = _provider(provider_type)
    list(provider.stream_generate(messages=[{"role": "user", "content": "hello"}], timeout=3.5))

    assert provider.session.calls
    assert provider.session.calls[0][1]["timeout"] == 3.5


def test_invalid_provider_timeout_uses_adapter_default():
    provider = _provider(OpenAIProvider)
    provider.generate(messages=[{"role": "user", "content": "hello"}], timeout="invalid")

    assert provider.session.calls[0][1]["timeout"] == 60.0
