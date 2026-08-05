import json

import pytest

from providers.azure_openai import AzureOpenAIProvider


def test_azure_tool_envelope_is_parser_compatible():
    text = AzureOpenAIProvider._tool_envelope([
        {"id": "call_1", "function": {
            "name": "web_search", "arguments": '{"query":"latest news"}',
        }},
    ])
    assert text == '<function=web_search>{"query": "latest news"}'


def test_azure_generate_forwards_tools_model_and_returns_native_call(monkeypatch):
    provider = AzureOpenAIProvider()
    provider.api_key = "live-test-key"
    provider.endpoint = "https://test-resource.openai.azure.com"
    provider.deployment = "gpt-4o-check"
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {
                    "name": "web_search", "arguments": '{"query":"latest news"}'
                }}
            ]}}]}

    def post(url, *args, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(provider.session, "post", post)
    tools = [{"type": "function", "function": {
        "name": "web_search", "parameters": {"type": "object"}
    }}]
    result = provider.generate(
        messages=[{"role": "user", "content": "search"}],
        tools=tools,
        tool_choice="auto",
        max_tokens=32,
    )

    assert result == '<function=web_search>{"query": "latest news"}'
    # Request body always carries the deployment as `model` plus native tools.
    assert captured["json"]["model"] == "gpt-4o-check"
    assert captured["json"]["tools"] == tools
    assert captured["json"]["tool_choice"] == "auto"
    assert captured["json"]["max_tokens"] == 32
    # URL is built from the endpoint, never a relative path.
    assert captured["url"].startswith("https://test-resource.openai.azure.com/openai/deployments/gpt-4o-check/chat/completions")


def test_azure_missing_endpoint_raises_readable_error():
    provider = AzureOpenAIProvider()
    provider.api_key = "live-test-key"
    provider.endpoint = ""
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        provider.generate(messages=[{"role": "user", "content": "search"}])


def test_azure_stream_buffers_native_tool_call_fragments(monkeypatch):
    provider = AzureOpenAIProvider()
    provider.api_key = "live-test-key"
    provider.endpoint = "https://test-resource.openai.azure.com"
    provider.deployment = "gpt-4o-check"

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            chunks = [
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"name": "web_search", "arguments": '{"query":'}},
                ]}}]},
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"arguments": '"latest news"}'}},
                ]}}]},
            ]
            return [
                ("data: " + json.dumps(chunk)).encode() for chunk in chunks
            ] + [b"data: [DONE]"]

    monkeypatch.setattr(provider.session, "post", lambda *args, **kwargs: Response())
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "search"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        tool_choice="auto",
    ))

    assert result == ['<function=web_search>{"query": "latest news"}']
