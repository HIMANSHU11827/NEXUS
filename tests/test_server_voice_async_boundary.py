import asyncio
import threading
from types import SimpleNamespace


class _Request:
    async def json(self):
        return {"mode": "text", "session_id": "async-boundary"}


def test_voice_start_launches_child_from_worker_thread(monkeypatch):
    import apps.api

    main_thread = threading.get_ident()
    called = {}
    process = SimpleNamespace(pid=1234, poll=lambda: None)

    def fake_launcher(mode, session_id, owner_pid):
        called.update(mode=mode, session_id=session_id, owner_pid=owner_pid, thread=threading.get_ident())
        return process

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(server, "_VOICE_PROCESS", None)
    monkeypatch.setattr(server, "_start_voice_process_sync", fake_launcher)
    monkeypatch.setattr(server.asyncio, "sleep", no_sleep)

    result = asyncio.run(server.start_voice(_Request()))

    assert result["status"] == "success"
    assert called["mode"] == "text"
    assert called["session_id"] == "async-boundary"
    assert called["owner_pid"] == 0
    assert called["thread"] != main_thread
    server._VOICE_PROCESS = None
