import asyncio
import json

import pytest
from starlette.requests import Request


def _request(payload):
    body = json.dumps(payload).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/chat",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "client": ("testclient", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive,
    )


@pytest.mark.asyncio
async def test_server_stream_disconnect_aborts_underlying_run(monkeypatch):
    import apps.api

    captured = {}

    class FakeLoop:
        is_running = False
        model = "default-model"
        work_event_sink = None

        def request_abort(self, run_id, reason=""):
            captured["abort"] = (run_id, reason)
            return True

        async def stream_run(self, prompt, **kwargs):
            try:
                yield {"type": "content", "data": "first"}
                await asyncio.sleep(30)
            finally:
                captured["stream_closed"] = True

    monkeypatch.setattr(server, "get_loop", lambda _sid: FakeLoop())
    monkeypatch.setattr(server, "set_active_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "start_chat_workflow", lambda *args: "")
    monkeypatch.setattr(server, "complete_chat_workflow", lambda *args, **kwargs: None)

    response = await server.chat(
        _request({
            "prompt": "disconnect",
            "session_id": "disconnect-session",
            "turn_id": "disconnect-turn",
            "stream": True,
        })
    )
    iterator = response.body_iterator
    first = await asyncio.wait_for(iterator.__anext__(), timeout=2.0)
    assert "first" in first

    await iterator.aclose()

    assert captured["abort"] == ("disconnect-turn", "client_disconnect")
    assert captured["stream_closed"] is True
