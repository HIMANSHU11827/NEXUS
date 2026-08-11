import asyncio
import threading

import gateway.platforms.sms as sms_module
from gateway.platforms.sms import SMSAdapter


class _App:
    def route(self, *_args, **_kwargs):
        def decorator(callback):
            self.callback = callback
            return callback
        return decorator


class _Server:
    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.closed = False

    def serve_forever(self):
        self.started.set()
        self.stopped.wait(timeout=2)

    def shutdown(self):
        self.stopped.set()

    def server_close(self):
        self.closed = True


def test_sms_webhook_runs_off_event_loop_and_shutdown_joins(monkeypatch):
    server = _Server()
    monkeypatch.setattr(sms_module, "HAS_FLASK", True)
    monkeypatch.setattr(sms_module, "Flask", lambda _name: _App())
    monkeypatch.setattr(sms_module, "make_server", lambda *args, **kwargs: server)
    monkeypatch.setenv("TWILIO_WEBHOOK_PORT", "18081")

    async def scenario():
        adapter = SMSAdapter(account_sid="sid", auth_token="token", from_number="from")
        task = asyncio.create_task(adapter._run_webhook())
        adapter._webhook_server = task

        assert await asyncio.to_thread(server.started.wait, 1.0)
        await adapter.disconnect()

        assert task.done()
        assert server.closed is True

    asyncio.run(scenario())
