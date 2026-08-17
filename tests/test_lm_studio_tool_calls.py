import json

from models.providers.core.health import ProviderCapabilityRegistry
from models.providers.local.lm_studio import LMStudioProvider
from models.providers.core.model_capabilities import ModelCapabilityRegistry


def test_lm_studio_native_tool_envelope_is_parser_compatible():
    text = LMStudioProvider._tool_envelope([
        {"id": "call_1", "index": 0, "function": {
            "name": "bash", "arguments": '{"command":"Get-Location"}',
        }},
    ])
    assert text == '<function=bash>{"command": "Get-Location"}'


def test_lm_studio_capabilities_preserve_tool_schemas():
    assert ProviderCapabilityRegistry().get("lm_studio").tool_calling is True
    assert ModelCapabilityRegistry.from_loader().get("lm_studio", "qwen").tools is True


def test_lm_studio_native_call_and_payload_preserve_schemas(monkeypatch):
    provider = LMStudioProvider()
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {
                    "name": "bash", "arguments": '{"command":"Get-Location"}'
                }}
            ]}}]}

    def post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(provider.session, "post", post)
    tools = [{"type": "function", "function": {
        "name": "bash", "parameters": {"type": "object"}
    }}]
    result = provider.generate(
        messages=[{"role": "user", "content": "where am I?"}],
        tools=tools,
        tool_choice="auto",
        stream=True,
    )

    assert result == '<function=bash>{"command": "Get-Location"}'
    assert captured["json"]["tools"] == tools
    assert captured["json"]["tool_choice"] == "auto"
    assert captured["json"]["stream"] is False


def test_lm_studio_stream_buffers_text_when_native_tools_are_enabled(monkeypatch):
    provider = LMStudioProvider()
    captured = {}

    class Response:
        status_code = 200

        def iter_lines(self):
            chunks = [
                {"choices": [{"delta": {"content": "partial"}}]},
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"name": "bash", "arguments": '{"command":'}},
                ]}}]},
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"arguments": '"Get-Location"}'}},
                ]}}]},
                {"choices": [{"delta": {}}]},
            ]
            return [("data: " + json.dumps(chunk)).encode() for chunk in chunks] + [b"data: [DONE]"]

    def post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(provider.session, "post", post)
    tools = [{"type": "function", "function": {"name": "bash"}}]
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "where am I?"}],
        tools=tools,
        tool_choice="auto",
        stream=False,
    ))
    assert result == ['<function=bash>{"command": "Get-Location"}']
    assert captured["json"]["tools"] == tools
    assert captured["json"]["tool_choice"] == "auto"
    assert captured["json"]["stream"] is True


def test_lm_studio_stream_preserves_multiple_native_calls_by_index(monkeypatch):
    provider = LMStudioProvider()

    class Response:
        status_code = 200

        def iter_lines(self):
            chunks = [
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 1, "function": {"name": "second", "arguments": "{}"}},
                    {"index": 0, "function": {"name": "first", "arguments": "{"}},
                ]}}]},
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"arguments": "}"}},
                ]}}]},
            ]
            return [
                ("data: " + json.dumps(chunk)).encode() for chunk in chunks
            ] + [b"data: [DONE]"]

    monkeypatch.setattr(provider.session, "post", lambda *args, **kwargs: Response())
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "call both"}],
        tools=[{"type": "function", "function": {"name": "first"}}],
    ))

    assert result == [
        '<function=first>{}\n<function=second>{}',
    ]
