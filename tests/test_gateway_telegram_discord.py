"""Behavioral tests for the Telegram and Discord gateway adapters.

These exercise the REAL adapter code paths (connect / message normalisation /
send_text / disconnect) using lightweight in-process fake transports, so the
suite runs green anywhere without network access or real API tokens.

The adapters are env-gated:
  * ``connect()`` returns ``False`` when no bot token is configured, and when the
    underlying SDK is not importable.
  * Tests that would truly require live credentials are skipped unless the
    relevant ``*_BOT_TOKEN`` env var is present.
"""

from __future__ import annotations

import asyncio
import os
import types

import pytest

import gateway.platforms.telegram as tg_module
import gateway.platforms.discord as dc_module
from gateway.base import MessageEvent, MessageType, SendResult
from gateway.platforms.discord import DiscordAdapter
from gateway.platforms.telegram import TelegramAdapter


# --------------------------------------------------------------------------- #
# Fake Telegram transport
# --------------------------------------------------------------------------- #
class FakeTeleBot:
    """Minimal stand-in for ``telebot.async_telebot.AsyncTeleBot``."""

    def __init__(self, token: str):
        self.token = token
        self.sent: list[dict] = []
        self.typing_calls: list[tuple] = []
        self.stopped = False

    def message_handler(self, *args, **kwargs):
        def decorator(coro):
            return coro
        return decorator

    async def infinity_polling(self):
        return None

    async def stop_polling(self):
        self.stopped = True

    async def send_message(self, chat_id, text, reply_to_message_id=None):
        self.sent.append(
            {"chat_id": chat_id, "text": text, "reply_to": reply_to_message_id}
        )
        return types.SimpleNamespace(message_id=len(self.sent))

    async def send_chat_action(self, chat_id, action):
        self.typing_calls.append((chat_id, action))


def make_tele_message(
    text="hello",
    from_user_id=99,
    chat_id=42,
    message_id=7,
    content_type="text",
    reply_to_message=None,
):
    return types.SimpleNamespace(
        text=text,
        from_user=types.SimpleNamespace(id=from_user_id),
        chat=types.SimpleNamespace(id=chat_id),
        message_id=message_id,
        content_type=content_type,
        reply_to_message=reply_to_message,
        attachments=[],
    )


# --------------------------------------------------------------------------- #
# Fake Discord transport
# --------------------------------------------------------------------------- #
class FakeDiscordMessage:
    def __init__(
        self,
        content="hello",
        author_id=99,
        channel_id=42,
        message_id=7,
        author_is_bot=False,
        attachments=None,
    ):
        self.content = content
        self.author = types.SimpleNamespace(id=author_id, bot=author_is_bot)
        self.channel = types.SimpleNamespace(id=channel_id)
        self.id = message_id
        self.attachments = attachments or []


class FakeChannel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.sent: list[str] = []

    async def send(self, text):
        self.sent.append(text)
        return types.SimpleNamespace(id=len(self.sent))

    async def typing(self):
        return None

    async def fetch_message(self, mid):
        return types.SimpleNamespace(
            id=mid, reply=lambda t: types.SimpleNamespace(id=1000 + int(mid))
        )


class FakeDiscordClient:
    def __init__(self, intents=None):
        self.intents = intents
        self.user = types.SimpleNamespace(id="SELF_BOT")
        self._channels: dict = {}
        self.closed = False
        self.started = False

    def event(self, coro):
        # discord.py registers the coroutine as an attribute named after it.
        setattr(self, coro.__name__, coro)
        return coro

    async def start(self, token):
        self.started = True
        return None

    async def close(self):
        self.closed = True

    def get_channel(self, cid):
        return self._channels.get(str(cid))

    async def fetch_channel(self, cid):
        ch = FakeChannel(cid)
        self._channels[str(cid)] = ch
        return ch


class FakeDiscord:
    class Intents:
        @classmethod
        def default(cls):
            return cls()

    Client = FakeDiscordClient


def make_discord_attachment(url, content_type):
    return types.SimpleNamespace(url=url, content_type=content_type)


# --------------------------------------------------------------------------- #
# Telegram tests
# --------------------------------------------------------------------------- #
def test_telegram_env_alias_resolution(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "preferred-token")

    assert TelegramAdapter().token == "preferred-token"

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "legacy-token")
    assert TelegramAdapter().token == "legacy-token"

    # explicit constructor arg wins over env
    assert TelegramAdapter(token="explicit").token == "explicit"


def test_telegram_connect_returns_false_without_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    assert adapter.token == ""
    assert asyncio.run(adapter.connect()) is False


def test_telegram_connect_returns_false_without_sdk(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", None, raising=False)

    adapter = TelegramAdapter()
    assert asyncio.run(adapter.connect()) is False


async def test_telegram_connect_success_registers_handler(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    assert await adapter.connect() is True
    assert isinstance(adapter.bot, FakeTeleBot)


async def test_telegram_incoming_text_message_normalized(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    await adapter.connect()

    received: list[MessageEvent] = []
    adapter.set_message_handler(lambda ev: received.append(ev))

    await adapter._handle_incoming(
        make_tele_message(text="hi there", from_user_id=11, chat_id=22, message_id=33)
    )

    assert len(received) == 1
    ev = received[0]
    assert ev.text == "hi there"
    assert ev.sender_id == "11"
    assert ev.chat_id == "22"
    assert ev.message_id == "33"
    assert ev.platform == "telegram"
    assert ev.message_type == MessageType.TEXT
    assert ev.reply_to_id is None


async def test_telegram_incoming_photo_and_voice_types(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    await adapter.connect()
    received: list[MessageEvent] = []
    adapter.set_message_handler(received.append)

    await adapter._handle_incoming(make_tele_message(content_type="photo"))
    await adapter._handle_incoming(make_tele_message(content_type="voice"))

    assert received[0].message_type == MessageType.PHOTO
    assert received[1].message_type == MessageType.VOICE


async def test_telegram_incoming_reply_to(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    await adapter.connect()
    received: list[MessageEvent] = []
    adapter.set_message_handler(received.append)

    await adapter._handle_incoming(
        make_tele_message(reply_to_message=types.SimpleNamespace(message_id=1234))
    )
    assert received[0].reply_to_id == "1234"


async def test_telegram_send_text(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    await adapter.connect()

    result = await adapter.send_text("chat-1", "hello world", reply_to="5")
    assert isinstance(result, SendResult)
    assert result.success is True
    assert result.message_id is not None

    assert len(adapter.bot.sent) == 1
    sent = adapter.bot.sent[0]
    assert sent["chat_id"] == "chat-1"
    assert sent["text"] == "hello world"
    assert sent["reply_to"] == "5"


async def test_telegram_send_text_not_connected():
    adapter = TelegramAdapter()
    adapter.bot = None
    result = await adapter.send_text("chat-1", "hi")
    assert result.success is False
    assert "not connected" in result.error.lower()


async def test_telegram_send_text_does_not_replay_non_idempotent_send(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    await adapter.connect()
    calls = {"count": 0}

    async def timed_out_send(*_args, **_kwargs):
        calls["count"] += 1
        raise TimeoutError("response status unknown")

    adapter.bot.send_message = timed_out_send
    result = await adapter.send_text("chat-1", "may already be delivered")

    assert result.success is False
    assert calls["count"] == 1


async def test_telegram_send_typing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    await adapter.connect()
    await adapter.send_typing("chat-9")

    assert ("chat-9", "typing") in adapter.bot.typing_calls


async def test_telegram_disconnect_stops_polling(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "some-token")
    monkeypatch.setattr(tg_module, "AsyncTeleBot", FakeTeleBot, raising=False)

    adapter = TelegramAdapter()
    await adapter.connect()
    await adapter.disconnect()

    assert adapter.bot.stopped is True
    assert adapter._poll_task is None


# --------------------------------------------------------------------------- #
# Discord tests
# --------------------------------------------------------------------------- #
def test_discord_env_alias_resolution(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "preferred-token")
    assert DiscordAdapter().token == "preferred-token"

    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_TOKEN", "legacy-token")
    assert DiscordAdapter().token == "legacy-token"

    assert DiscordAdapter(token="explicit").token == "explicit"


def test_discord_connect_returns_false_without_token(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    assert adapter.token == ""
    assert asyncio.run(adapter.connect()) is False


def test_discord_connect_returns_false_without_sdk(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", None, raising=False)

    adapter = DiscordAdapter()
    assert asyncio.run(adapter.connect()) is False


async def test_discord_connect_success_registers_handler(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    assert await adapter.connect() is True
    assert isinstance(adapter.client, FakeDiscordClient)
    # connect() launches client.start() as a background task; let the loop tick.
    await asyncio.sleep(0)
    assert adapter.client.started is True
    # on_message was registered as an event handler
    assert callable(getattr(adapter.client, "on_message", None))


async def test_discord_background_client_failure_updates_health(monkeypatch):
    class FailingClient(FakeDiscordClient):
        async def start(self, token):
            raise ConnectionError("discord gateway dropped")

    class FailingDiscord(FakeDiscord):
        Client = FailingClient

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FailingDiscord, raising=False)

    adapter = DiscordAdapter()
    assert await adapter.connect() is True
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert adapter.health == "unavailable"
    assert adapter.state == "recovering"
    assert "gateway dropped" in adapter.last_error


async def test_discord_incoming_text_normalized_and_skips_self(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    await adapter.connect()
    received: list[MessageEvent] = []
    adapter.set_message_handler(received.append)

    other = FakeDiscordMessage(content="ping", author_id=7, channel_id=3, message_id=5)
    await adapter.client.on_message(other)
    assert len(received) == 1
    ev = received[0]
    assert ev.text == "ping"
    assert ev.sender_id == "7"
    assert ev.chat_id == "3"
    assert ev.message_id == "5"
    assert ev.platform == "discord"
    assert ev.message_type == MessageType.TEXT
    assert ev.media_urls == []

    # Self-message must be ignored
    self_msg = FakeDiscordMessage(author_id=0, author_is_bot=True)
    self_msg.author = adapter.client.user
    received.clear()
    await adapter.client.on_message(self_msg)
    assert received == []


async def test_discord_incoming_attachments_photo_and_document(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    await adapter.connect()
    received: list[MessageEvent] = []
    adapter.set_message_handler(received.append)

    photo_msg = FakeDiscordMessage(
        attachments=[make_discord_attachment("https://x/i.png", "image/png")]
    )
    await adapter.client.on_message(photo_msg)
    assert received[-1].message_type == MessageType.PHOTO
    assert received[-1].media_urls == ["https://x/i.png"]

    doc_msg = FakeDiscordMessage(
        attachments=[make_discord_attachment("https://x/f.pdf", "application/pdf")]
    )
    await adapter.client.on_message(doc_msg)
    assert received[-1].message_type == MessageType.DOCUMENT
    assert received[-1].media_urls == ["https://x/f.pdf"]


async def test_discord_send_text(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    await adapter.connect()
    adapter.client._channels["77"] = FakeChannel(77)

    result = await adapter.send_text("77", "hello discord")
    assert result.success is True
    assert adapter.client._channels["77"].sent == ["hello discord"]


async def test_discord_send_text_with_reply(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    await adapter.connect()
    channel = FakeChannel(77)
    adapter.client._channels["77"] = channel

    result = await adapter.send_text("77", "replying", reply_to="555")
    assert result.success is True


async def test_discord_send_text_not_connected():
    adapter = DiscordAdapter()
    adapter.client = None
    result = await adapter.send_text("77", "hi")
    assert result.success is False
    assert "not connected" in result.error.lower()


async def test_discord_send_typing(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    await adapter.connect()
    channel = FakeChannel(77)
    adapter.client._channels["77"] = channel

    await adapter.send_typing("77")  # should not raise even if channel is absent
    assert adapter.client.get_channel("77") is channel


async def test_discord_disconnect_closes_client(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "some-token")
    monkeypatch.setattr(dc_module, "discord", FakeDiscord, raising=False)

    adapter = DiscordAdapter()
    await adapter.connect()
    await adapter.disconnect()

    assert adapter.client.closed is True
    assert adapter._run_task is None


# --------------------------------------------------------------------------- #
# Env-gated integration smoke (skips without real credentials)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not os.getenv("TELEGRAM_BOT_TOKEN"),
    reason="requires TELEGRAM_BOT_TOKEN for real integration",
)
async def test_telegram_real_token_resolves():
    adapter = TelegramAdapter()
    assert adapter.token == os.getenv("TELEGRAM_BOT_TOKEN")


@pytest.mark.skipif(
    not os.getenv("DISCORD_BOT_TOKEN"),
    reason="requires DISCORD_BOT_TOKEN for real integration",
)
async def test_discord_real_token_resolves():
    adapter = DiscordAdapter()
    assert adapter.token == os.getenv("DISCORD_BOT_TOKEN")
