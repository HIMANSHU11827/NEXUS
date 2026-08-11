import asyncio

import gateway.platforms.slack as slack_module
from gateway.platforms.slack import SlackAdapter


class _WebClient:
    def __init__(self, token):
        self.token = token


class _Socket:
    def __init__(self, *, app_token, web_client):
        self.app_token = app_token
        self.web_client = web_client
        self.closed = False

    def on(self, _event):
        def decorator(callback):
            self.callback = callback
            return callback
        return decorator

    async def connect(self):
        raise ConnectionError("socket dropped")

    async def close(self):
        self.closed = True


def test_slack_socket_failure_updates_supervisor_health(monkeypatch):
    monkeypatch.setattr(slack_module, "HAS_SLACK", True)
    monkeypatch.setattr(slack_module, "AsyncWebClient", _WebClient)
    monkeypatch.setattr(slack_module, "SocketModeClient", _Socket)

    async def scenario():
        adapter = SlackAdapter(bot_token="bot", app_token="app")
        assert await adapter.connect() is True
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert adapter.health == "unavailable"
        assert adapter.state == "recovering"
        assert "socket dropped" in adapter.last_error
        await adapter.disconnect()

    asyncio.run(scenario())


def test_slack_disconnect_awaits_socket_task(monkeypatch):
    class WaitingSocket(_Socket):
        async def connect(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(slack_module, "HAS_SLACK", True)
    monkeypatch.setattr(slack_module, "AsyncWebClient", _WebClient)
    monkeypatch.setattr(slack_module, "SocketModeClient", WaitingSocket)

    async def scenario():
        adapter = SlackAdapter(bot_token="bot", app_token="app")
        assert await adapter.connect() is True
        task = adapter._socket_task
        await asyncio.sleep(0)
        await adapter.disconnect()
        assert adapter._socket_task is None
        assert task is not None and task.done()

    asyncio.run(scenario())
