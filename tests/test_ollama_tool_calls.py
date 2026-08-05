import json

from providers.ollama import OllamaProvider


def test_ollama_native_tool_envelope_is_parser_compatible():
    text = OllamaProvider._tool_envelope([
        {"type": "function", "function": {
            "name": "web_search", "arguments": {"query": "latest news"}
        }},
    ])
    assert text == '<function=web_search>{"query": "latest news"}'


def test_ollama_generate_forwards_tools_and_returns_native_call(monkeypatch):
    provider = OllamaProvider()
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"message": {"content": "", "tool_calls": [
                {"function": {
                    "name": "web_search", "arguments": {"query": "latest news"}
                }}
            ]}}

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
    )

    assert result == '<function=web_search>{"query": "latest news"}'
    assert captured["json"]["tools"] == tools


def test_ollama_stream_buffers_native_tool_call_fragments(monkeypatch):
    provider = OllamaProvider()

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            chunks = [
                {"message": {"tool_calls": [
                    {"index": 0, "function": {"name": "web_search", "arguments": {"query": "latest"}}},
                ]}, "done": False},
                {"message": {"tool_calls": [
                    {"index": 0, "function": {"name": "web_search", "arguments": {"query": "latest news"}}},
                ]}, "done": True},
            ]
            return [(json.dumps(chunk)).encode() for chunk in chunks]

    monkeypatch.setattr(provider.session, "post", lambda *args, **kwargs: Response())
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "search"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
    ))

    assert result == ['<function=web_search>{"query": "latest news"}']
