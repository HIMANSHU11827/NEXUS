from providers.llama_cpp import LlamaCPPProvider


class FakeLlama:
    def __init__(self):
        self.calls = []

    def create_chat_completion(self, messages, stream=False, **kwargs):
        self.calls.append({"messages": messages, "stream": stream, **kwargs})
        if stream:
            return [
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"name": "web_search", "arguments": '{"query":'}},
                ]}}]},
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "function": {"name": "", "arguments": '"latest news"}'}},
                ]}}]},
            ]
        return {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {
                "name": "web_search", "arguments": '{"query": "latest news"}'
            }}
        ]}}]}


def _provider():
    provider = LlamaCPPProvider()
    provider.llm = FakeLlama()
    return provider


def test_llama_cpp_native_tool_envelope_is_parser_compatible():
    text = LlamaCPPProvider._tool_envelope([
        {"id": "call_1", "function": {
            "name": "web_search", "arguments": '{"query":"latest news"}',
        }},
    ])
    assert text == '<function=web_search>{"query": "latest news"}'


def test_llama_cpp_generate_forwards_tools_and_returns_native_call():
    provider = _provider()
    tools = [{"type": "function", "function": {
        "name": "web_search", "parameters": {"type": "object"}
    }}]
    result = provider.generate(
        messages=[{"role": "user", "content": "search"}],
        tools=tools,
        tool_choice="auto",
    )

    assert result == '<function=web_search>{"query": "latest news"}'
    call = provider.llm.calls[0]
    assert call["tools"] == tools
    assert call["tool_choice"] == "auto"
    assert call["stream"] is False


def test_llama_cpp_stream_buffers_native_tool_call_fragments():
    provider = _provider()
    tools = [{"type": "function", "function": {"name": "web_search"}}]
    result = list(provider.stream_generate(
        messages=[{"role": "user", "content": "search"}],
        tools=tools,
    ))

    assert result == ['<function=web_search>{"query": "latest news"}']
    call = provider.llm.calls[0]
    assert call["tools"] == tools
    assert call["stream"] is True
