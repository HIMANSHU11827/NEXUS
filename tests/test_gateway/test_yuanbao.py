"""
Tests for the NEXUS YuanBao (元宝) gateway adapter.

These tests are *env-gated* and *network-free*: they never require a live
YuanBao endpoint or real credentials, and they pass whether or not any optional
YuanBao libraries are installed (the adapter is self-contained over ``httpx``).
The ``httpx.AsyncClient`` transport is replaced with a lightweight fake, and all
parsing / signature routines are pure functions.

Async coroutines are driven with ``asyncio.run`` from plain ``def`` tests so the
suite is green in any pytest configuration (the project's existing ``async def``
tests require ``pytest-asyncio`` with ``asyncio_mode=auto``).
"""

import asyncio
import base64
import hashlib
import hmac

import pytest

from gateways.base import SendResult
from gateways.platforms import all_adapters, get_adapter
from gateways.platforms.yuanbao import YuanbaoAdapter
from gateways.run import GatewayRunner, _PLATFORM_ENV_MAP


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
    """Stand-in for httpx.AsyncClient used by the YuanBao adapter."""

    def __init__(self, response=None):
        self.response = response or FakeResponse({"message_id": "msg_1"})
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


def make_handler(events):
    async def _handler(event):
        events.append(event)
    return _handler


# ===========================================================================
# Construction / gating
# ===========================================================================
def test_yuanbao_name():
    assert YuanbaoAdapter.name == "yuanbao"
    assert YuanbaoAdapter().platform == "yuanbao"
    assert YuanbaoAdapter.required_env == ("YUANBAO_ACCESS_TOKEN", "YUANBAO_TOKEN")


def test_yuanbao_env_gating_missing_token(monkeypatch):
    monkeypatch.delenv("YUANBAO_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("YUANBAO_TOKEN", raising=False)
    a = YuanbaoAdapter()
    assert a.access_token == ""
    assert a.is_configured() is False
    # Without a token, connect() must refuse.
    assert asyncio.run(a.connect()) is False


def test_yuanbao_instantiation_from_env(monkeypatch):
    monkeypatch.setenv("YUANBAO_ACCESS_TOKEN", "tok123")
    monkeypatch.setenv("YUANBAO_GROUP_CODE", "328306697")
    a = YuanbaoAdapter()
    assert a.access_token == "tok123"
    assert a.default_group_code == "328306697"
    assert a.is_configured() is True


def test_yuanbao_token_alias(monkeypatch):
    monkeypatch.delenv("YUANBAO_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("YUANBAO_TOKEN", "alias-tok")
    a = YuanbaoAdapter()
    assert a.access_token == "alias-tok"
    assert a.is_configured() is True


# ===========================================================================
# Inbound parsing (pure)
# ===========================================================================
def _sample_group_message():
    return {
        "type": "message",
        "message_id": "m_1",
        "group_code": "328306697",
        "sender": {"user_id": "u_alice", "nickname": "Alice", "role": "user"},
        "content": "帮我艾特元宝",
        "mentions": [{"user_id": "u_yb", "nickname": "元宝"}],
        "timestamp": 1700000000,
    }


def test_yuanbao_parse_event_group_message():
    ev = YuanbaoAdapter.parse_event(_sample_group_message())
    assert ev is not None
    assert ev.text == "帮我艾特元宝"
    assert ev.sender_id == "u_alice"
    assert ev.chat_id == "group:328306697"
    assert ev.platform == "yuanbao"
    assert ev.message_id == "m_1"
    assert ev.raw_data["sender"]["nickname"] == "Alice"


def test_yuanbao_parse_event_skips_non_message():
    follow = YuanbaoAdapter.parse_event(
        {"type": "follow", "group_code": "1", "sender": {"user_id": "u"}}
    )
    malformed = YuanbaoAdapter.parse_event("not-a-dict")
    assert follow is None
    assert malformed is None


def test_yuanbao_parse_event_missing_sender_or_text():
    no_text = YuanbaoAdapter.parse_event(
        {"type": "message", "group_code": "1", "sender": {"user_id": "u"}}
    )
    no_sender = YuanbaoAdapter.parse_event(
        {"type": "message", "group_code": "1", "content": "hi"}
    )
    assert no_text is None
    assert no_sender is None


def test_yuanbao_handle_webhook_envelope_dispatches():
    a = YuanbaoAdapter(access_token="tok")
    events = []
    a.set_message_handler(make_handler(events))

    dispatched = asyncio.run(
        a.handle_webhook_payload(
            {
                "events": [
                    _sample_group_message(),
                    {"type": "follow", "group_code": "1"},
                    _sample_group_message(),
                ]
            }
        )
    )
    # Two of the three events are real messages.
    assert len(dispatched) == 2
    assert len(events) == 2
    assert {e.text for e in events} == {"帮我艾特元宝"}


# ===========================================================================
# @mention helpers (pure)
# ===========================================================================
def test_yuanbao_format_mention():
    assert YuanbaoAdapter.format_mention("元宝") == "@元宝"


def test_yuanbao_extract_mentions():
    text = "hi @元宝 和 @Bob 来一下"
    assert YuanbaoAdapter.extract_mentions(text) == ["元宝", "Bob"]
    assert YuanbaoAdapter.extract_mentions("no mentions here") == []
    assert YuanbaoAdapter.extract_mentions("") == []


def test_yuanbao_chat_id_for_group():
    assert YuanbaoAdapter.chat_id_for_group("328306697") == "group:328306697"


# ===========================================================================
# Webhook signature verification
# ===========================================================================
def test_yuanbao_verify_callback():
    a = YuanbaoAdapter(webhook_secret="shh")
    sig = a.compute_signature("1700000000", "abc")
    assert a.verify_callback("1700000000", "abc", sig) is True
    assert a.verify_callback("1700000000", "tampered", sig) is False
    # Without a secret, verification cannot succeed.
    a_no_secret = YuanbaoAdapter()
    assert a_no_secret.verify_callback("1700000000", "abc", sig) is False


# ===========================================================================
# Outbound (fake transport)
# ===========================================================================
def test_yuanbao_send_text_not_connected():
    a = YuanbaoAdapter(access_token="tok")
    result = asyncio.run(a.send_text("group:328306697", "hi"))
    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.error == "Not connected"


def test_yuanbao_send_text_push_with_mention():
    a = YuanbaoAdapter(access_token="tok")
    fake = FakeAsyncClient(response=FakeResponse({"message_id": "msg_9"}))
    a._client = fake

    result = asyncio.run(a.send_text("group:328306697", "hi @元宝"))
    assert result.success is True
    assert result.message_id == "msg_9"

    assert fake.calls, "expected a POST to /groups/.../messages"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "/groups/328306697/messages"
    payload = kwargs["json"]
    assert payload["content"] == "hi @元宝"
    # The @mention token is surfaced as a structured mention.
    assert payload["mentions"] == [{"nickname": "元宝"}]


def test_yuanbao_send_text_reply_to():
    a = YuanbaoAdapter(access_token="tok")
    fake = FakeAsyncClient(response=FakeResponse({"message_id": "msg_r"}))
    a._client = fake

    result = asyncio.run(
        a.send_text("group:328306697", "reply", reply_to="orig_1")
    )
    assert result.success is True
    payload = fake.calls[0][2]["json"]
    assert payload["reply_to_message_id"] == "orig_1"


def test_yuanbao_send_text_default_group_code():
    a = YuanbaoAdapter(access_token="tok", group_code="999")
    fake = FakeAsyncClient(response=FakeResponse({"message_id": "m"}))
    a._client = fake

    result = asyncio.run(a.send_text("group:328306697", "via explicit chat"))
    # Explicit chat id wins over the default group code.
    assert result.success is True
    assert fake.calls[0][1] == "/groups/328306697/messages"

    fake2 = FakeAsyncClient(response=FakeResponse({"message_id": "m2"}))
    a._client = fake2
    result2 = asyncio.run(a.send_text("some-other-context", "uses default"))
    # No group: prefix and no digit -> falls back to default group code.
    assert result2.success is True
    assert fake2.calls[0][1] == "/groups/999/messages"


def test_yuanbao_send_text_no_group():
    a = YuanbaoAdapter(access_token="tok")
    fake = FakeAsyncClient()
    a._client = fake
    result = asyncio.run(a.send_text("not-a-group", "orphan"))
    assert result.success is False
    assert "group_code" in (result.error or "")


def test_yuanbao_send_dm():
    a = YuanbaoAdapter(access_token="tok")
    fake = FakeAsyncClient(response=FakeResponse({"message_id": "dm_1"}))
    a._client = fake

    result = asyncio.run(
        a.send_dm("328306697", "u_bob", "private hello")
    )
    assert result.success is True
    assert result.message_id == "dm_1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "/groups/328306697/dm"
    assert kwargs["json"] == {
        "user_id": "u_bob",
        "content": "private hello",
    }


def test_yuanbao_send_dm_with_media():
    a = YuanbaoAdapter(access_token="tok")
    fake = FakeAsyncClient(response=FakeResponse({"message_id": "dm_m"}))
    a._client = fake

    result = asyncio.run(
        a.send_dm(
            "328306697",
            "u_bob",
            "here is the image",
            media_files=[{"path": "/tmp/photo.jpg"}],
        )
    )
    assert result.success is True
    assert kwargs_contains_media(fake.calls[0][2]["json"])


def kwargs_contains_media(payload: dict) -> bool:
    return payload.get("media_files") == [{"path": "/tmp/photo.jpg"}]


# ===========================================================================
# Runner-level wiring
# ===========================================================================
def test_platform_env_map_covers_yuanbao():
    assert _PLATFORM_ENV_MAP["yuanbao"] == [
        ["YUANBAO_ACCESS_TOKEN", "YUANBAO_TOKEN"]
    ]


def test_registry_exposes_yuanbao():
    assert "yuanbao" in all_adapters()

    yb = get_adapter("yuanbao", access_token="tok")
    assert isinstance(yb, YuanbaoAdapter)
    assert yb.access_token == "tok"


def test_register_all_skips_yuanbao_without_env(monkeypatch):
    # Clear every platform's env vars for a deterministic registration pass.
    for groups in _PLATFORM_ENV_MAP.values():
        for group in groups:
            for var in group:
                monkeypatch.delenv(var, raising=False)

    runner = GatewayRunner()
    runner.register_all()
    # YuanBao must be absent when its access token is not configured.
    assert runner.adapters.get("yuanbao") is None


def test_register_all_registers_yuanbao_with_env(monkeypatch):
    # Clear every platform's env vars first.
    for groups in _PLATFORM_ENV_MAP.values():
        for group in groups:
            for var in group:
                monkeypatch.delenv(var, raising=False)
    # Then enable only YuanBao.
    monkeypatch.setenv("YUANBAO_ACCESS_TOKEN", "tok")

    runner = GatewayRunner()
    runner.register_all()
    adapter = runner.adapters.get("yuanbao")
    assert isinstance(adapter, YuanbaoAdapter)
    assert adapter.is_configured() is True
