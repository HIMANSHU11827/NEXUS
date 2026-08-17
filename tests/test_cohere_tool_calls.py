from models.providers.api.cohere import CohereProvider


def test_cohere_native_tool_envelope_is_parser_compatible():
    text = CohereProvider._tool_envelope([
        {"name": "web_search", "parameters": {"query": "latest news"}},
    ])
    assert text == '<function=web_search>{"query": "latest news"}'


def test_cohere_generate_parses_native_tool_call_from_response(monkeypatch):
    provider = CohereProvider()
    provider.api_key = "live-test-key"
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {
                "text": "",
                "message": {"role": "assistant", "tool_calls": [
                    {"name": "web_search", "parameters": {"query": "latest news"}}
                ]},
            }

    def post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(provider.session, "post", post)
    result = provider.generate(
        messages=[{"role": "user", "content": "search"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
    )

    assert result == '<function=web_search>{"query": "latest news"}'
    # Cohere /v1/chat takes native parameter_definitions schemas, not OpenAI-style;
    # the raw OpenAI tools list must NOT be forwarded (would 422).
    assert "tools" not in captured["json"]


def test_cohere_generate_returns_text_when_no_tool_call(monkeypatch):
    provider = CohereProvider()
    provider.api_key = "live-test-key"

    class Response:
        status_code = 200

        def json(self):
            return {"text": "plain answer", "message": {"role": "assistant"}}

    monkeypatch.setattr(provider.session, "post", lambda *args, **kwargs: Response())
    result = provider.generate(
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == "plain answer"