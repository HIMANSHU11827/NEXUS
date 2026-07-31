"""Tests for the Weixin (WeChat Official Account) and QQBot gateway adapters.

These adapters are env-gated and degrade gracefully when credentials are
absent. We verify construction, env-var fallback, the inbound signature /
parse helpers (pure, network-free), and the outbound send path with a
monkeypatched transport.
"""

import asyncio
import base64
import hashlib
import hmac
import os
import sys
from pathlib import Path

import pytest

# Ensure the project root is importable regardless of pytest's rootdir discovery.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gateway.base import SendResult  # noqa: E402
from gateway.platforms import all_adapters, get_adapter  # noqa: E402
from gateway.platforms.weixin import WeixinAdapter, _sha1_signature  # noqa: E402
from gateway.platforms.qqbot import QQBotAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Lightweight fakes for the network client
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code

    def json(self):
        return self._json


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient used by Weixin / QQBot."""

    def __init__(self, response=None):
        self.response = response or FakeResponse({"msgid": "wx-1"})
        self.calls = []
        self.closed = False

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response

    async def aclose(self):
        self.closed = True


def make_handler(events):
    async def _handler(event):
        events.append(event)

    return _handler


# ===========================================================================
# Weixin adapter
# ===========================================================================
def test_weixin_name():
    assert WeixinAdapter.name == "weixin"
    assert WeixinAdapter().platform == "weixin"


def test_weixin_env_gating_missing_config(monkeypatch):
    for v in ("WX_APPID", "WEIXIN_APPID", "WX_APPSECRET", "WEIXIN_APPSECRET"):
        monkeypatch.delenv(v, raising=False)
    adapter = WeixinAdapter()
    assert adapter.is_configured() is False
    assert asyncio.run(adapter.connect()) is False


def test_weixin_instantiation_from_env(monkeypatch):
    monkeypatch.setenv("WX_APPID", "wxapp")
    monkeypatch.setenv("WX_APPSECRET", "wxsecret")
    adapter = WeixinAdapter()
    assert adapter.appid == "wxapp"
    assert adapter.appsecret == "wxsecret"
    assert adapter.is_configured() is True


def test_weixin_alias_env(monkeypatch):
    monkeypatch.delenv("WX_APPID", raising=False)
    monkeypatch.delenv("WX_APPSECRET", raising=False)
    monkeypatch.setenv("WEIXIN_APPID", "alias_app")
    monkeypatch.setenv("WEIXIN_APPSECRET", "alias_secret")
    adapter = WeixinAdapter()
    assert adapter.appid == "alias_app"
    assert adapter.appsecret == "alias_secret"


def test_weixin_verify_url_and_signature():
    token, ts, nonce, echostr = "mytoken", "1700000000", "abc123", "verify-me"
    url_sig = _sha1_signature(token, ts, nonce, echostr)
    assert WeixinAdapter.verify_url(token, ts, nonce, echostr, url_sig) is True
    assert WeixinAdapter.verify_url(token, ts, nonce, echostr, "wrong") is False

    msg_sig = _sha1_signature(token, ts, nonce)
    assert WeixinAdapter.verify_signature(token, ts, nonce, msg_sig) is True
    assert WeixinAdapter.verify_signature(token, ts, nonce, "bogus") is False


WEXIN_XML = """<xml>
<ToUserName><![CDATA[nexus_mp]]></ToUserName>
<FromUserName><![CDATA[openid_user_1]]></FromUserName>
<CreateTime>1700000000</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[hello nexus]]></Content>
<MsgId>1234567890123456</MsgId>
</xml>"""


def test_weixin_parse_incoming_text():
    event = WeixinAdapter.parse_incoming(WEXIN_XML)
    assert event is not None
    assert event.text == "hello nexus"
    assert event.sender_id == "openid_user_1"
    assert event.chat_id == "openid_user_1"
    assert event.platform == "weixin"
    assert event.message_id == "1234567890123456"
    assert str(event.message_type) == "text"


def test_weixin_parse_incoming_event_returns_none():
    xml = """<xml><MsgType><![CDATA[event]]></MsgType><Event><![CDATA[subscribe]]></Event></xml>"""
    assert WeixinAdapter.parse_incoming(xml) is None


def test_weixin_parse_incoming_malformed():
    assert WeixinAdapter.parse_incoming("not xml <<<") is None


async def test_weixin_send_text_not_connected():
    adapter = WeixinAdapter(appid="a", appsecret="s")
    result = await adapter.send_text("openid_x", "hi")
    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.error == "Not connected"


async def test_weixin_send_text_success(monkeypatch):
    monkeypatch.setenv("WX_APPID", "wxapp")
    monkeypatch.setenv("WX_APPSECRET", "wxsecret")
    adapter = WeixinAdapter()
    adapter._client = FakeAsyncClient(response=FakeResponse({"msgid": "wx-msg-7"}))
    adapter._access_token = "tok-123"

    result = await adapter.send_text("openid_x", "pong")
    assert result.success is True
    assert result.message_id == "wx-msg-7"

    assert adapter._client.calls, "expected a POST to /message/custom/send"
    method, url, kwargs = adapter._client.calls[0]
    assert method == "POST"
    assert url == "/message/custom/send"
    assert kwargs["params"] == {"access_token": "tok-123"}
    assert kwargs["json"]["touser"] == "openid_x"
    assert kwargs["json"]["msgtype"] == "text"
    assert kwargs["json"]["text"]["content"] == "pong"


async def test_weixin_send_text_api_error(monkeypatch):
    monkeypatch.setenv("WX_APPID", "wxapp")
    monkeypatch.setenv("WX_APPSECRET", "wxsecret")
    adapter = WeixinAdapter()
    adapter._client = FakeAsyncClient(response=FakeResponse({"errcode": 40003, "errmsg": "invalid openid"}))
    adapter._access_token = "tok-123"

    result = await adapter.send_text("bad_id", "hi")
    assert result.success is False
    assert "invalid openid" in result.error


# ===========================================================================
# QQBot adapter
# ===========================================================================
def test_qqbot_name():
    assert QQBotAdapter.name == "qqbot"
    assert QQBotAdapter().platform == "qqbot"


def test_qqbot_env_gating_missing_config(monkeypatch):
    for v in ("QQBOT_APPID", "QQ_APPID", "QQBOT_SECRET", "QQ_SECRET"):
        monkeypatch.delenv(v, raising=False)
    adapter = QQBotAdapter()
    assert adapter.is_configured() is False
    assert asyncio.run(adapter.connect()) is False


def test_qqbot_instantiation_from_env(monkeypatch):
    monkeypatch.setenv("QQBOT_APPID", "qqapp")
    monkeypatch.setenv("QQBOT_SECRET", "qqsecret")
    adapter = QQBotAdapter()
    assert adapter.appid == "qqapp"
    assert adapter.secret == "qqsecret"
    assert adapter.is_configured() is True


def test_qqbot_alias_env(monkeypatch):
    monkeypatch.delenv("QQBOT_APPID", raising=False)
    monkeypatch.delenv("QQBOT_SECRET", raising=False)
    monkeypatch.setenv("QQ_APPID", "alias_qq_app")
    monkeypatch.setenv("QQ_SECRET", "alias_qq_secret")
    adapter = QQBotAdapter()
    assert adapter.appid == "alias_qq_app"
    assert adapter.secret == "alias_qq_secret"


def _qq_sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def test_qqbot_verify_callback():
    secret = "qq-client-secret"
    body = b'{"d":{"content":"hi"}}'
    sig = _qq_sign(secret, body)
    assert QQBotAdapter.verify_callback(secret, body, sig) is True
    # Tampered body must fail verification.
    assert QQBotAdapter.verify_callback(secret, b'{"d":{}}', sig) is False
    # Wrong secret must fail.
    assert QQBotAdapter.verify_callback("other", body, sig) is False


def test_qqbot_parse_event_challenge():
    challenge, event = QQBotAdapter.parse_event({"challenge": "abc123"})
    assert challenge == "abc123"
    assert event is None


def test_qqbot_parse_event_group_message():
    payload = {
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "author": {"id": "user_openid_9", "username": "alice"},
            "content": "group ping",
            "id": "msg_group_1",
            "group_id": "group_openid_42",
        },
    }
    challenge, event = QQBotAdapter.parse_event(payload)
    assert challenge is None
    assert event is not None
    assert event.text == "group ping"
    assert event.sender_id == "user_openid_9"
    assert event.chat_id == "group_openid_42"
    assert event.platform == "qqbot"
    assert event.message_id == "msg_group_1"


def test_qqbot_parse_event_c2c_message():
    payload = {
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "author": {"id": "user_openid_7"},
            "content": "private hi",
            "id": "msg_c2c_1",
        },
    }
    challenge, event = QQBotAdapter.parse_event(payload)
    assert event is not None
    assert event.chat_id == "user_openid_7"  # falls back to sender id
    assert event.text == "private hi"
    assert event.message_id == "msg_c2c_1"


def test_qqbot_parse_event_malformed():
    assert QQBotAdapter.parse_event({"foo": "bar"}) == (None, None)
    assert QQBotAdapter.parse_event("not-a-dict") == (None, None)


async def test_qqbot_send_text_not_connected():
    adapter = QQBotAdapter(appid="a", secret="s")
    result = await adapter.send_text("user_openid_1", "hi")
    assert isinstance(result, SendResult)
    assert result.success is False
    assert result.error == "Not connected"


async def test_qqbot_send_text_user_success(monkeypatch):
    monkeypatch.setenv("QQBOT_APPID", "qqapp")
    monkeypatch.setenv("QQBOT_SECRET", "qqsecret")
    adapter = QQBotAdapter()
    adapter._client = FakeAsyncClient(response=FakeResponse({"id": "qq-msg-1"}))
    adapter._access_token = "qq-tok"

    result = await adapter.send_text("user_openid_1", "hello qq")
    assert result.success is True
    assert result.message_id == "qq-msg-1"

    assert adapter._client.calls, "expected a POST to /v2/users/.../messages"
    method, url, kwargs = adapter._client.calls[0]
    assert method == "POST"
    assert url == "/v2/users/user_openid_1/messages"
    assert kwargs["headers"]["Authorization"] == "QQBot qq-tok"
    assert kwargs["json"] == {"content": "hello qq", "msg_type": 0}


async def test_qqbot_send_text_group_with_reply(monkeypatch):
    monkeypatch.setenv("QQBOT_APPID", "qqapp")
    monkeypatch.setenv("QQBOT_SECRET", "qqsecret")
    adapter = QQBotAdapter()
    adapter._client = FakeAsyncClient(response=FakeResponse({"id": "qq-grp-1"}))
    adapter._access_token = "qq-tok"

    result = await adapter.send_text(
        "group_openid_42", "reply!", reply_to="parent_msg", to_type="group"
    )
    assert result.success is True
    method, url, kwargs = adapter._client.calls[0]
    assert url == "/v2/groups/group_openid_42/messages"
    assert kwargs["json"]["msg_id"] == "parent_msg"
    assert kwargs["json"]["content"] == "reply!"


async def test_qqbot_send_text_api_error(monkeypatch):
    monkeypatch.setenv("QQBOT_APPID", "qqapp")
    monkeypatch.setenv("QQBOT_SECRET", "qqsecret")
    adapter = QQBotAdapter()
    adapter._client = FakeAsyncClient(
        response=FakeResponse({"code": 500000, "message": "invalid user"}, status_code=200)
    )
    adapter._access_token = "qq-tok"

    result = await adapter.send_text("user_openid_1", "hi")
    assert result.success is False
    assert "invalid user" in result.error


# ===========================================================================
# Registry / runner wiring
# ===========================================================================
def test_platforms_registry_includes_both():
    assert "weixin" in all_adapters()
    assert "qqbot" in all_adapters()
    assert get_adapter("weixin").platform == "weixin"
    assert get_adapter("qqbot").platform == "qqbot"


def test_runner_env_map_covers_both():
    from gateway.run import _PLATFORM_ENV_MAP, _has_required_env

    assert _PLATFORM_ENV_MAP["weixin"] == [["WX_APPID"], ["WX_APPSECRET"]]
    assert _PLATFORM_ENV_MAP["qqbot"] == [["QQBOT_APPID"], ["QQBOT_SECRET"]]


def test_register_all_skips_unconfigured_adapters(monkeypatch):
    for var in (
        "WX_APPID", "WEIXIN_APPID", "WX_APPSECRET", "WEIXIN_APPSECRET",
        "QQBOT_APPID", "QQ_APPID", "QQBOT_SECRET", "QQ_SECRET",
        "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "META_ACCESS_TOKEN",
        "WHATSAPP_TOKEN", "SLACK_BOT_TOKEN", "SMTP_HOST", "TWILIO_ACCOUNT_SID",
    ):
        monkeypatch.delenv(var, raising=False)

    from gateway.run import GatewayRunner

    runner = GatewayRunner()
    runner.register_all()
    assert runner.adapters.get("weixin") is None
    assert runner.adapters.get("qqbot") is None
