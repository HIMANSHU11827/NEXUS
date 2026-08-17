import json

from models.providers.api.google_gemini import GoogleGeminiProvider


def test_gemini_tools_to_functionDeclarations():
    """OpenAI-style tools are converted to Gemini functionDeclarations."""
    tools = [
        {"type": "function", "function": {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}
        }},
        {"type": "function", "function": {
            "name": "no_params",
            "description": "No parameters tool"
        }},
    ]
    result = GoogleGeminiProvider._tools_to_gemini(tools)
    assert result == [
        {"functionDeclarations": [
            {"name": "web_search", "description": "Search the web",
             "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}},
            {"name": "no_params", "description": "No parameters tool"},
        ]}
    ]


def test_gemini_tools_to_functionDeclarations_empty():
    assert GoogleGeminiProvider._tools_to_gemini([]) is None
    assert GoogleGeminiProvider._tools_to_gemini(None) is None


def test_gemini_parse_text_parts():
    parts = [{"text": "Hello"}, {"text": " world"}]
    result = GoogleGeminiProvider._parse_parts(parts)
    assert result == "Hello\n world"


def test_gemini_parse_functionCall_parts():
    parts = [
        {"functionCall": {"name": "web_search", "args": {"q": "latest news"}}},
    ]
    result = GoogleGeminiProvider._parse_parts(parts)
    assert result == '<function=web_search>{"q": "latest news"}'


def test_gemini_parse_mixed_parts():
    parts = [
        {"text": "Let me search"},
        {"functionCall": {"name": "web_search", "args": {"q": "news"}}},
    ]
    result = GoogleGeminiProvider._parse_parts(parts)
    assert result == 'Let me search\n<function=web_search>{"q": "news"}'


def test_gemini_generate_sends_tools_and_parses_functionCall(monkeypatch):
    provider = GoogleGeminiProvider()
    provider.api_key = "test-key"
    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "web_search", "args": {"q": "news"}}}
            ]}}]}

    def post(*args, **kwargs):
        captured["url"] = args[0] if args else ""
        captured["json"] = kwargs.get("json", {})
        return Response()

    monkeypatch.setattr(provider.session, "post", post)

    tools = [{"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web",
        "parameters": {"type": "object"}
    }}]
    result = provider.generate(
        messages=[{"role": "user", "content": "search for news"}],
        tools=tools,
    )

    assert result == '<function=web_search>{"q": "news"}'
    # Verify Gemini-format tools were sent
    sent_tools = captured["json"].get("tools", [])
    assert sent_tools == [
        {"functionDeclarations": [
            {"name": "web_search", "description": "Search the web",
             "parameters": {"type": "object"}}
        ]}
    ]


def test_gemini_generate_text_only_still_works(monkeypatch):
    provider = GoogleGeminiProvider()
    provider.api_key = "test-key"

    class Response:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Hello world"}]}}]}

    monkeypatch.setattr(provider.session, "post", lambda *a, **kw: Response())
    result = provider.generate(messages=[{"role": "user", "content": "hi"}])
    assert result == "Hello world"


def test_gemini_stream_parses_functionCall(monkeypatch):
    provider = GoogleGeminiProvider()
    provider.api_key = "test-key"

    class Response:
        status_code = 200

        def iter_lines(self, **kwargs):
            return [
                b'[,{"candidates":[{"content":{"parts":[{"text":"Looking up"}]}}]},',
                b',{"candidates":[{"content":{"parts":[{"functionCall":{"name":"web_search","args":{"q":"test"}}}]}}]},',
                b"]",
            ]

    monkeypatch.setattr(provider.session, "post", lambda *a, **kw: Response())
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "search"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
    ))
    assert result == ['Looking up', '<function=web_search>{"q": "test"}']
