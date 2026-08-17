"""
Tests for the IRC and LINE gateway adapters.

These tests are *env-gated* and *network-free*: they never require a live IRC
server or LINE endpoint, and they pass whether or not any optional IRC/LINE
libraries are installed (the adapters are self-contained). Network transports
are replaced with lightweight fakes injected in place of the real socket /
``httpx`` clients.
"""

import asyncio
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from gateways.base import SendResult
from gateways.platforms.irc import IRCAdapter
from gateways.platforms.line import LineAdapter, LINE_REQUIRED_ENV


# ---------------------------------------------------------------------------
# Lightweight fakes
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, json_data=None, is_success=True, status_code=200):
        self._json = json_data if json_data is not None else {}
        self.is_success = is_success
        self.status_code = status_code

    def json(self):
        return self._json


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient used by the LINE adapter."""

    def __init__(self, response=None):
        self.response = response or FakeResponse({"messageId": "msg1"})
        self.calls = []
        self.closed = False

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    async def aclose(self):
        self.closed = True


class FakeIRCWriter:
    """Stand-in for asyncio.StreamWriter used by the IRC adapter."""

    def __init__(self):
        self.sent = []
        self.closed = False

    def write(self, data):
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        self.sent.append(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.closed = True


def make_handler(events):
    async def _handler(event):
        events.append(event)
    return _handler


# ===========================================================================
# IRC adapter
# ===========================================================================
def test_irc_name():
    assert IRCAdapter.name == "irc"
    assert IRCAdapter().platform == "irc"


def test_irc_defaults():
    a = IRCAdapter(server="irc.example.org", port=6667, nick="nexus")
    assert a.server == "irc.example.org"
    assert a.port == 6667
    assert a.use_ssl is False
    assert a.nick == "nexus"
    assert a.is_configured() is True


def test_irc_ssl_default_on_tls_port():
    a = IRCAdapter(server="irc.example.org", port=6697, nick="nexus")
    assert a.use_ssl is True


def test_irc_env_overrides(monkeypatch):
    monkeypatch.setenv("IRC_SERVER", "irc.libera.chat")
    monkeypatch.setenv("IRC_PORT", "7000")
    monkeypatch.setenv("IRC_NICK", "mybot")
    monkeypatch.setenv("IRC_CHANNELS", "#a, #b ,#c")
    monkeypatch.setenv("IRC_USE_SSL", "false")
    a = IRCAdapter()
    assert a.server == "irc.libera.chat"
    assert a.port == 7000
    assert a.nick == "mybot"
    assert a.channels == ["#a", "#b", "#c"]
    assert a.use_ssl is False


def test_irc_env_gating_missing_nick(monkeypatch):
    monkeypatch.delenv("IRC_NICK", raising=False)
    a = IRCAdapter()
    assert a.nick == ""
    assert a.is_configured() is False
    # Without a configured nick, connect() must refuse.
    assert asyncio.run(a.connect()) is False


def test_irc_nick_from_prefix():
    assert IRCAdapter._nick_from_prefix("alice!~alice@host.example") == "alice"
    assert IRCAdapter._nick_from_prefix("bob@10.0.0.1") == "bob"
    assert IRCAdapter._nick_from_prefix("") == ""


async def test_irc_handle_privmsg_channel():
    a = IRCAdapter(nick="nexus")
    events = []
    a.set_message_handler(make_handler(events))

    await a._handle_line(":alice!~alice@host PRIVMSG #nexus :hello world")
    assert len(events) == 1
    ev = events[0]
    assert ev.text == "hello world"
    assert ev.sender_id == "alice"
    assert ev.chat_id == "#nexus"
    assert ev.platform == "irc"
    assert ev.message_id is None


async def test_irc_handle_privmsg_direct_message():
    a = IRCAdapter(nick="nexus")
    events = []
    a.set_message_handler(make_handler(events))

    # A DM arrives with the bot nick as the target -> chat id should be the
    # sender, not the bot itself.
    await a._handle_line(":bob!b@h PRIVMSG nexus :psst hi")
    assert len(events) == 1
    ev = events[0]
    assert ev.text == "psst hi"
    assert ev.sender_id == "bob"
    assert ev.chat_id == "bob"


async def test_irc_ping_pong():
    a = IRCAdapter(nick="nexus")
    writer = FakeIRCWriter()
    a._writer = writer
    await a._handle_line("PING :irc.example.org")
    assert any("PONG :irc.example.org" in line for line in writer.sent)


async def test_irc_nick_in_use_recovers():
    a = IRCAdapter(nick="nexus")
    writer = FakeIRCWriter()
    a._writer = writer
    await a._handle_line(":server 433 * nexus :Nickname is already in use.")
    assert any("NICK nexus_1" in line for line in writer.sent)


async def test_irc_send_text_not_connected():
    a = IRCAdapter(nick="nexus")
    result = await a.send_text("#chan", "hi")
    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.error == "Not connected"


async def test_irc_send_text_success_and_split():
    a = IRCAdapter(nick="nexus")
    writer = FakeIRCWriter()
    a._writer = writer

    result = await a.send_text("#chan", "ping\npong")
    assert result.success is True
    assert len(writer.sent) == 2
    assert writer.sent[0].rstrip("\r\n") == "PRIVMSG #chan :ping"
    assert writer.sent[1].rstrip("\r\n") == "PRIVMSG #chan :pong"


async def test_irc_send_text_long_line_splits():
    a = IRCAdapter(nick="nexus")
    writer = FakeIRCWriter()
    a._writer = writer

    long_text = "x" * 1000
    await a.send_text("#chan", long_text)
    # Every emitted line must stay under the IRC 512-byte command budget.
    for line in writer.sent:
        assert line.startswith("PRIVMSG #chan :")
        assert len(line.encode("utf-8")) <= 512


# ===========================================================================
# LINE adapter
# ===========================================================================
def test_line_name():
    assert LineAdapter.name == "line"
    assert LineAdapter().platform == "line"
    assert LineAdapter.required_env == LINE_REQUIRED_ENV


def test_line_env_gating_missing_token(monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_TOKEN", raising=False)
    a = LineAdapter()
    assert a.channel_access_token == ""
    assert a.is_configured() is False
    assert asyncio.run(a.connect()) is False


def test_line_instantiation_from_env(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "tok123")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "shh")
    a = LineAdapter()
    assert a.channel_access_token == "tok123"
    assert a.channel_secret == "shh"
    assert a.is_configured() is True


def test_line_parse_event_text_message():
    ev = LineAdapter._parse_event({
        "type": "message",
        "id": "evt1",
        "replyToken": "rtok",
        "source": {"type": "user", "userId": "U123"},
        "message": {"type": "text", "text": "hello line"},
    })
    assert ev is not None
    assert ev.text == "hello line"
    assert ev.sender_id == "U123"
    assert ev.chat_id == "U123"
    assert ev.platform == "line"
    assert ev.message_id == "evt1"
    assert ev.reply_to_id == "rtok"


def test_line_parse_event_group_source():
    ev = LineAdapter._parse_event({
        "type": "message",
        "id": "evt2",
        "replyToken": "rtok2",
        "source": {"type": "group", "groupId": "G1", "userId": "U99"},
        "message": {"type": "text", "text": "group hi"},
    })
    assert ev is not None
    assert ev.sender_id == "U99"
    assert ev.chat_id == "G1"
    assert ev.reply_to_id == "rtok2"


def test_line_parse_event_skips_non_message():
    # follow / postback / image events must be ignored.
    follow = LineAdapter._parse_event({
        "type": "follow", "source": {"type": "user", "userId": "U1"}
    })
    image = LineAdapter._parse_event({
        "type": "message",
        "source": {"type": "user", "userId": "U1"},
        "message": {"type": "image", "packageId": "p", "id": "i"},
    })
    assert follow is None
    assert image is None


async def test_line_handle_webhook_payload_dispatches():
    a = LineAdapter(channel_access_token="tok")
    events = []
    a.set_message_handler(make_handler(events))

    await a.handle_webhook_payload({
        "events": [
            {
                "type": "message",
                "id": "e1",
                "replyToken": "r1",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "one"},
            },
            {"type": "follow", "source": {"type": "user", "userId": "U1"}},
            {
                "type": "message",
                "id": "e2",
                "replyToken": "r2",
                "source": {"type": "user", "userId": "U2"},
                "message": {"type": "text", "text": "two"},
            },
        ]
    })
    assert len(events) == 2
    assert {e.text for e in events} == {"one", "two"}


def test_line_verify_signature():
    a = LineAdapter(channel_access_token="tok", channel_secret="shh")
    body = b'{"events":[]}'
    mac = hmac.new(b"shh", body, hashlib.sha256)
    sig = base64.b64encode(mac.digest()).decode("ascii")
    assert a.verify_signature(body, sig) is True
    assert a.verify_signature(b"tampered", sig) is False
    # Without a secret, verification cannot succeed.
    a_no_secret = LineAdapter(channel_access_token="tok")
    assert a_no_secret.verify_signature(body, sig) is False


async def test_line_send_text_not_connected():
    a = LineAdapter(channel_access_token="tok")
    result = await a.send_text("U1", "hi")
    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.error == "Not connected"


async def test_line_send_text_push():
    a = LineAdapter(channel_access_token="tok")
    fake = FakeAsyncClient(response=FakeResponse({"messageId": "msg_9"}))
    a._client = fake

    result = await a.send_text("U123", "ping")
    assert result.success is True
    assert result.message_id == "msg_9"

    assert fake.calls, "expected a POST to /message/push"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "/message/push"
    assert kwargs["json"]["to"] == "U123"
    assert kwargs["json"]["messages"][0]["text"] == "ping"


async def test_line_send_text_reply():
    a = LineAdapter(channel_access_token="tok")
    fake = FakeAsyncClient(response=FakeResponse({"messageId": "msg_reply"}))
    a._client = fake

    result = await a.send_text("U123", "pong", reply_to="reply_token_1")
    assert result.success is True
    method, url, kwargs = fake.calls[0]
    assert url == "/message/reply"
    assert kwargs["json"]["replyToken"] == "reply_token_1"
    assert kwargs["json"]["messages"][0]["text"] == "pong"


async def test_line_send_image():
    a = LineAdapter(channel_access_token="tok")
    fake = FakeAsyncClient(response=FakeResponse({"messageId": "img_1"}))
    a._client = fake

    result = await a.send_image("U123", "https://example.com/x.png", caption="see")
    assert result.success is True
    # Caption text is sent first as its own push.
    push_calls = [c for c in fake.calls if c[1] == "/message/push"]
    assert len(push_calls) == 2
    image_payload = push_calls[1][2]["json"]
    assert image_payload["messages"][0]["type"] == "image"
    assert image_payload["messages"][0]["originalContentUrl"] == "https://example.com/x.png"


# ===========================================================================
# Runner-level wiring
# ===========================================================================
def test_platform_env_map_covers_irc_and_line():
    from gateways.run import _PLATFORM_ENV_MAP

    assert _PLATFORM_ENV_MAP["irc"] == [["IRC_NICK"]]
    assert _PLATFORM_ENV_MAP["line"] == [
        ["LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_TOKEN"]
    ]


def test_registry_exposes_irc_and_line():
    from gateways.platforms import all_adapters, get_adapter

    assert "irc" in all_adapters()
    assert "line" in all_adapters()

    irc = get_adapter("irc", nick="nexus")
    assert isinstance(irc, IRCAdapter)
    assert irc.nick == "nexus"

    line = get_adapter("line", channel_access_token="tok")
    assert isinstance(line, LineAdapter)
    assert line.channel_access_token == "tok"


def test_register_all_skips_irc_and_line_without_env(monkeypatch):
    for var in (
        "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "META_ACCESS_TOKEN",
        "WHATSAPP_TOKEN", "SLACK_BOT_TOKEN", "SIGNAL_NUMBER",
        "MATRIX_HOMESERVER", "MATRIX_USER", "MATRIX_ACCESS_TOKEN",
        "MATRIX_PASSWORD", "MATTERMOST_URL", "MATTERMOST_TOKEN",
        "SMTP_HOST", "TWILIO_ACCOUNT_SID", "IRC_NICK",
        "LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)

    from gateways.run import GatewayRunner

    runner = GatewayRunner()
    runner.register_all()
    assert runner.adapters.get("irc") is None
    assert runner.adapters.get("line") is None
