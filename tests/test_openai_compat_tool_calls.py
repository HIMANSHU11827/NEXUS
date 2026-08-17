"""Parametrized native tool-calling tests for OpenAI-compatible providers.

Each provider here serves an OpenAI-style /chat/completions endpoint, so the
tests are identical other than the class under test. The VLMProvider stream is
a passthrough to generate(), so its stream assertions use a non-streaming
response body instead of SSE fragments.
"""
import json

import pytest

from models.providers.api.commandcode import CommandCodeProvider
from models.providers.api.fireworks import FireworksProvider
from models.providers.api.groq import GroqProvider
from models.providers.api.mistral import MistralProvider
from models.providers.api.nvidia import NvidiaProvider
from models.providers.api.qwen import QwenProvider
from models.providers.api.sambanova import SambaNovaProvider
from models.providers.api.together import TogetherProvider
from models.providers.core.vlm import VLMProvider
from models.providers.api.xai import XAIProvider


OPENAI_COMPAT_PROVIDERS = [
    GroqProvider,
    FireworksProvider,
    MistralProvider,
    TogetherProvider,
    QwenProvider,
    XAIProvider,
    SambaNovaProvider,
    NvidiaProvider,
    CommandCodeProvider,
    VLMProvider,
]

STREAM_SSE_PROVIDERS = [
    p for p in OPENAI_COMPAT_PROVIDERS if p is not VLMProvider
]

TOOLS = [{"type": "function", "function": {
    "name": "web_search", "parameters": {"type": "object"},
}}]
ARG_FRAGMENT1 = '{"query":'
ARG_FRAGMENT2 = '"latest news"}'
EXPECTED_ENVELOPE = '<function=web_search>{"query": "latest news"}'


def _make_provider(cls):
    provider = cls()
    provider.api_key = "live-test-key"
    return provider


class ToolResponse:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {
                "name": "web_search", "arguments": '{"query":"latest news"}',
            }},
        ]}}]}


class ToolStreamResponse:
    status_code = 200

    def iter_lines(self, **kwargs):
        chunks = [
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"name": "web_search", "arguments": ARG_FRAGMENT1}},
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": ARG_FRAGMENT2}},
            ]}}]},
        ]
        return [
            ("data: " + json.dumps(chunk)).encode() for chunk in chunks
        ] + [b"data: [DONE]"]


@pytest.mark.parametrize("cls", OPENAI_COMPAT_PROVIDERS, ids=lambda c: c.__name__)
def test_tool_envelope_is_parser_compatible(cls):
    text = cls._tool_envelope([
        {"id": "call_1", "type": "function", "function": {
            "name": "web_search", "arguments": '{"query":"latest news"}',
        }},
    ])
    assert text == EXPECTED_ENVELOPE


@pytest.mark.parametrize("cls", OPENAI_COMPAT_PROVIDERS, ids=lambda c: c.__name__)
def test_generate_forwards_tools_and_returns_native_call(monkeypatch, cls):
    provider = _make_provider(cls)
    captured = {}

    def post(*args, **kwargs):
        captured.update(kwargs)
        return ToolResponse()

    monkeypatch.setattr(provider.session, "post", post)
    result = provider.generate(
        messages=[{"role": "user", "content": "search"}],
        tools=TOOLS,
        tool_choice="auto",
    )

    assert result == EXPECTED_ENVELOPE
    assert captured["json"]["tools"] == TOOLS
    assert captured["json"]["tool_choice"] == "auto"


@pytest.mark.parametrize("cls", STREAM_SSE_PROVIDERS, ids=lambda c: c.__name__)
def test_stream_buffers_native_tool_call_fragments(monkeypatch, cls):
    provider = _make_provider(cls)

    monkeypatch.setattr(provider.session, "post", lambda *args, **kwargs: ToolStreamResponse())
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "search"}],
        tools=TOOLS,
        tool_choice="auto",
    ))

    assert result == [EXPECTED_ENVELOPE]


def test_vlm_stream_forwards_tools_to_generate(monkeypatch):
    provider = _make_provider(VLMProvider)
    captured = {}

    def post(*args, **kwargs):
        captured.update(kwargs)
        return ToolResponse()

    monkeypatch.setattr(provider.session, "post", post)
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "search"}],
        tools=TOOLS,
        tool_choice="auto",
    ))

    assert result == [EXPECTED_ENVELOPE]
    assert captured["json"]["tools"] == TOOLS
    assert captured["json"]["tool_choice"] == "auto"
