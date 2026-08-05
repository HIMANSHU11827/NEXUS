import json

from providers.anthropic import AnthropicProvider


def test_anthropic_tool_use_envelope_is_parser_compatible():
    text = AnthropicProvider._tool_envelope_from_content([
        {"type": "text", "text": "Let me search."},
        {"type": "tool_use", "id": "toolu_1", "name": "web_search", "input": {"query": "latest news"}},
    ])
    assert text == '<function=web_search>{"query": "latest news"}'


def test_anthropic_content_to_text_skips_tool_blocks():
    text = AnthropicProvider._content_to_text([
        {"type": "text", "text": "Hello"},
        {"type": "tool_use", "name": "web_search", "input": {}},
        {"type": "text", "text": "world"},
    ])
    assert text == "Hello\nworld"


def test_anthropic_generate_forwards_tools_and_returns_native_call(monkeypatch):
    provider = AnthropicProvider()
    provider.api_key = "live-test-key"
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"content": [
                {"type": "tool_use", "id": "toolu_1", "name": "web_search",
                 "input": {"query": "latest news"}},
            ]}

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
    assert captured["json"]["max_tokens"] == 32
    # Anthropic payload must stay in Anthropic shape: system separated,
    # and tool_choice as the native object form.
    msgs = captured["json"]["messages"]
    assert all(m["role"] != "system" for m in msgs)


def test_anthropic_stream_buffers_tool_use_blocks(monkeypatch):
    provider = AnthropicProvider()
    provider.api_key = "live-test-key"

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            events = [
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "tool_use", "id": "toolu_1", "name": "web_search", "input": {}}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta", "partial_json": '{"query":'}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta", "partial_json": '"latest news"}'}},
                {"type": "content_block_stop", "index": 0},
            ]
            return [
                ("data: " + json.dumps(event)).encode() for event in events
            ] + [b"data: {\"type\":\"message_stop\"}"]

    monkeypatch.setattr(provider.session, "post", lambda *args, **kwargs: Response())
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "search"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        tool_choice="auto",
    ))

    assert result == ['<function=web_search>{"query": "latest news"}']


def test_anthropic_stream_yields_text_and_accumulates_tools(monkeypatch):
    provider = AnthropicProvider()
    provider.api_key = "live-test-key"

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            events = [
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "text", "text": "Sure,"}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "text_delta", "text": " searching now."}},
                {"type": "content_block_stop", "index": 0},
                {"type": "content_block_start", "index": 1,
                 "content_block": {"type": "tool_use", "id": "toolu_2", "name": "bash", "input": {}}},
                {"type": "content_block_delta", "index": 1,
                 "delta": {"type": "input_json_delta", "partial_json": '{"command":"pwd"}'}},
                {"type": "content_block_stop", "index": 1},
            ]
            return [
                ("data: " + json.dumps(event)).encode() for event in events
            ] + [b"data: {\"type\":\"message_stop\"}"]

    monkeypatch.setattr(provider.session, "post", lambda *args, **kwargs: Response())
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "run it"}],
        tools=[{"type": "function", "function": {"name": "bash"}}],
        tool_choice="auto",
    ))

    assert result == ["Sure,", " searching now.", '<function=bash>{"command": "pwd"}']