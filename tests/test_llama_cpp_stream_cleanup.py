def test_llama_cpp_stream_closes_native_iterator_on_completion():
    from models.providers.local.llama_cpp import LlamaCPPProvider

    class NativeStream:
        def __init__(self):
            self.closed = False

        def __iter__(self):
            yield {"choices": [{"delta": {"content": "ok"}}]}

        def close(self):
            self.closed = True

    native_stream = NativeStream()

    class Llama:
        def create_chat_completion(self, **_kwargs):
            return native_stream

    provider = object.__new__(LlamaCPPProvider)
    provider.llm = Llama()

    assert list(provider.stream_generate("hello")) == ["ok"]
    assert native_stream.closed is True
