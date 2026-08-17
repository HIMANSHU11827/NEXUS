import json

from models.providers.core.universal import UniversalProvider


def test_universal_native_tool_envelope_is_parser_compatible():
    text = UniversalProvider._tool_envelope([
        {"id": "call_1", "type": "function", "function": {
            "name": "web_search", "arguments": '{"query":"latest news"}',
        }},
    ])
    assert text == '<function=web_search>{"query": "latest news"}'


def test_universal_generate_forwards_tools_and_returns_native_call(monkeypatch):
    provider = UniversalProvider()
    provider.api_key = "live-test-key"
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {
                    "name": "web_search", "arguments": '{"query":"latest news"}'
                }}
            ]}}]}

    def post(*args, **kwargs):
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
    assert captured["json"]["tools"] == tools
    assert captured["json"]["tool_choice"] == "auto"


def test_universal_stream_buffers_native_tool_call_fragments(monkeypatch):
    provider = UniversalProvider()
    provider.api_key = "live-test-key"

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