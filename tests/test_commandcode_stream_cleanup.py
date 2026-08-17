def test_commandcode_http_stream_closes_response_on_completion(monkeypatch):
    from models.providers.api.commandcode import CommandCodeProvider

    class Response:
        status_code = 200
        text = ""

        def __init__(self):
            self.closed = False

        def iter_lines(self):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}'
            yield b"data: [DONE]"

        def close(self):
            self.closed = True

    response = Response()

    class Session:
        def post(self, *args, **kwargs):
            return response

    provider = object.__new__(CommandCodeProvider)
    provider.model = "test-model"
    provider.endpoint = "https://provider.test/v1/chat/completions"
    provider.api_key = "test-key"
    provider.headers = {}
    provider.session = Session()
    monkeypatch.setattr(provider, "_use_http_api", lambda: True)

    assert list(provider.stream_generate("hello")) == ["ok"]
    assert response.closed is True
