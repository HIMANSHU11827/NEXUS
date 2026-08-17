"""Route-level tests for the NEXUS gateway inbound webhook server.

Covers `gateway/webhook_server.build_platform_routes`: every platform that
implements an inbound parser (LINE, Teams, Google Chat, Feishu, Yuanbao, QQBot,
DingTalk, WeCom, Weixin, BlueBubbles) gets a ``POST /webhook/<platform>`` route
proving:

* a valid signature dispatches the platform handler and returns 200,
* a missing / invalid signature returns 401 (fail closed, handler never called),
* a platform without credentials is not registered (404).

All transports are replaced by aiohttp's in-memory TestServer; no live endpoints
are contacted.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gateways.webhook_server as ws
from gateways.base import MessageEvent
from gateways.platforms.line import LineAdapter
from gateways.platforms.teams import TeamsAdapter
from gateways.platforms.google_chat import GoogleChatAdapter
from gateways.platforms.feishu import FeishuAdapter
from gateways.platforms.yuanbao import YuanbaoAdapter
from gateways.platforms.qqbot import QQBotAdapter
from gateways.platforms.dingtalk import DingtalkAdapter, _compute_robot_sign
from gateways.platforms.wecom import WeComAdapter, _sha1_signature as wecom_sha1
from gateways.platforms.weixin import WeixinAdapter, _sha1_signature as weixin_sha1
from gateways.platforms.bluebubbles import BlueBubblesAdapter

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(adapters):
    """Build an aiohttp app with the Meta route-table + configured platform routes."""
    ws._adapters = dict(adapters)
    app = web.Application()
    app.add_routes(ws.routes)
    app.add_routes(ws.build_platform_routes())
    return TestClient(TestServer(app))


@pytest.fixture
async def server():
    started = []

    async def _factory(adapters):
        client = _make_client(adapters)
        await client.start_server()
        started.append(client)
        return client

    try:
        yield _factory
    finally:
        for client in started:
            try:
                await client.close()
            except Exception:
                pass
        ws._adapters = {}


def _hmac_b64(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _replace_handler(adapter, calls):
    """Monkeypatch an adapter's inbound handler to record calls."""
    async def _fake(payload=None, *args, **kwargs):
        calls.append(payload)

    adapter.handle_webhook_payload = _fake


# ===========================================================================
# LINE
# ===========================================================================
class TestLineRoute:
    async def test_valid_signature_dispatches(self, server, monkeypatch):
        adapter = LineAdapter(channel_access_token="tok", channel_secret="shh")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"line": adapter})

        body = b'{"events":[]}'
        sig = _hmac_b64("shh", body)
        resp = await client.post("/webhook/line", data=body, headers={"X-Line-Signature": sig})
        assert resp.status == 200
        assert len(calls) == 1

    async def test_missing_signature_rejected_401(self, server, monkeypatch):
        adapter = LineAdapter(channel_access_token="tok", channel_secret="shh")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"line": adapter})

        resp = await client.post("/webhook/line", data=b'{"events":[]}')
        assert resp.status == 401
        assert calls == []

    async def test_invalid_signature_rejected_401(self, server, monkeypatch):
        adapter = LineAdapter(channel_access_token="tok", channel_secret="shh")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"line": adapter})

        resp = await client.post("/webhook/line", data=b'{"events":[]}', headers={"X-Line-Signature": "deadbeef"})
        assert resp.status == 401
        assert calls == []

    async def test_no_secret_route_not_registered(self, server, monkeypatch):
        monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
        adapter = LineAdapter(channel_access_token="tok")  # no secret -> no route
        client = await server({"line": adapter})
        resp = await client.post("/webhook/line", data=b'{"events":[]}')
        assert resp.status == 404


# ===========================================================================
# Teams
# ===========================================================================
class TestTeamsRoute:
    async def test_valid_bearer_dispatches(self, server):
        adapter = TeamsAdapter(client_secret="teams-secret")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"teams": adapter})

        activity = {"type": "message", "from": {"id": "u1"}, "conversation": {"id": "c1"}, "text": "hi"}
        resp = await client.post(
            "/webhook/teams",
            data=json.dumps(activity).encode(),
            headers={"Authorization": "Bearer teams-secret"},
        )
        assert resp.status == 200
        assert len(calls) == 1
        assert calls[0]["type"] == "message"

    async def test_missing_bearer_rejected_401(self, server):
        adapter = TeamsAdapter(client_secret="teams-secret")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"teams": adapter})

        resp = await client.post("/webhook/teams", data=b'{"type":"message"}')
        assert resp.status == 401
        assert calls == []

    async def test_invalid_bearer_rejected_401(self, server):
        adapter = TeamsAdapter(client_secret="teams-secret")
        client = await server({"teams": adapter})
        resp = await client.post("/webhook/teams", data=b'{}', headers={"Authorization": "Bearer wrong"})
        assert resp.status == 401

    async def test_no_secret_route_not_registered(self, server):
        adapter = TeamsAdapter(webhook_url="https://x")  # no client_secret / bot_token
        client = await server({"teams": adapter})
        resp = await client.post("/webhook/teams", data=b'{}')
        assert resp.status == 404


# ===========================================================================
# Google Chat
# ===========================================================================
class TestGoogleChatRoute:
    async def test_valid_secret_dispatches(self, server, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_WEBHOOK_SECRET", "gc-secret")
        adapter = GoogleChatAdapter()
        received = []

        async def fake_inbound(payload):
            return MessageEvent(text="hi", sender_id="u", chat_id="c", platform="google_chat")

        adapter.handle_inbound = fake_inbound
        adapter.set_message_handler(received.append)
        client = await server({"google_chat": adapter})

        resp = await client.post(
            "/webhook/google_chat",
            data=b'{"text":"hi"}',
            headers={"Authorization": "Bearer gc-secret"},
        )
        assert resp.status == 200
        assert len(received) == 1

    async def test_missing_secret_rejected_401(self, server, monkeypatch):
        monkeypatch.setenv("GOOGLE_CHAT_WEBHOOK_SECRET", "gc-secret")
        adapter = GoogleChatAdapter()
        client = await server({"google_chat": adapter})
        resp = await client.post("/webhook/google_chat", data=b'{"text":"hi"}')
        assert resp.status == 401

    async def test_no_env_secret_route_not_registered(self, server, monkeypatch):
        monkeypatch.delenv("GOOGLE_CHAT_WEBHOOK_SECRET", raising=False)
        adapter = GoogleChatAdapter()
        client = await server({"google_chat": adapter})
        resp = await client.post("/webhook/google_chat", data=b'{"text":"hi"}')
        assert resp.status == 404


# ===========================================================================
# Feishu
# ===========================================================================
class TestFeishuRoute:
    def _adapter(self):
        return FeishuAdapter(app_id="app", app_secret="secret", verification_token="vtok")

    async def test_url_verification_echoes_challenge(self, server):
        adapter = self._adapter()
        client = await server({"feishu": adapter})
        resp = await client.post(
            "/webhook/feishu",
            data=json.dumps({"type": "url_verification", "challenge": "chal-1", "token": "vtok"}).encode(),
        )
        assert resp.status == 200
        assert (await resp.read()) == b"chal-1"

    async def test_url_verification_wrong_token_rejected_401(self, server):
        adapter = self._adapter()
        client = await server({"feishu": adapter})
        resp = await client.post(
            "/webhook/feishu",
            data=json.dumps({"type": "url_verification", "challenge": "c", "token": "bogus"}).encode(),
        )
        assert resp.status == 401

    async def test_valid_signed_event_dispatches(self, server):
        adapter = self._adapter()
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"feishu": adapter})

        body = json.dumps({"event": {"message": {"content": "{}", "message_id": "m1"}}}).encode()
        ts, nonce = "1700000000", "abc"
        sig = adapter.compute_signature("vtok", ts, nonce)
        resp = await client.post(
            "/webhook/feishu",
            data=body,
            headers={
                "X-Lark-Request-Timestamp": ts,
                "X-Lark-Request-Nonce": nonce,
                "X-Lark-Signature": sig,
            },
        )
        assert resp.status == 200
        assert len(calls) == 1

    async def test_missing_signature_rejected_401(self, server):
        adapter = self._adapter()
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"feishu": adapter})
        resp = await client.post("/webhook/feishu", data=b'{"event":{}}')
        assert resp.status == 401
        assert calls == []


# ===========================================================================
# Yuanbao
# ===========================================================================
class TestYuanbaoRoute:
    async def test_valid_signature_dispatches(self, server):
        adapter = YuanbaoAdapter(access_token="tok", webhook_secret="yb-secret")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"yuanbao": adapter})

        ts, nonce = "1700000000", "abc"
        sig = adapter.compute_signature(ts, nonce)
        resp = await client.post(
            "/webhook/yuanbao",
            data=b'{"events":[]}',
            params={"timestamp": ts, "nonce": nonce},
            headers={"X-YuanBao-Signature": sig},
        )
        assert resp.status == 200
        assert len(calls) == 1

    async def test_invalid_signature_rejected_401(self, server):
        adapter = YuanbaoAdapter(access_token="tok", webhook_secret="yb-secret")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"yuanbao": adapter})
        resp = await client.post(
            "/webhook/yuanbao",
            data=b'{"events":[]}',
            params={"timestamp": "1700000000", "nonce": "abc"},
            headers={"X-YuanBao-Signature": "bogus"},
        )
        assert resp.status == 401
        assert calls == []


# ===========================================================================
# QQBot
# ===========================================================================
class TestQQBotRoute:
    def _adapter(self):
        return QQBotAdapter(appid="app", secret="qq-secret")

    async def test_challenge_echoed(self, server):
        adapter = self._adapter()
        client = await server({"qqbot": adapter})
        body = json.dumps({"challenge": "qq-chal"}).encode()
        sig = _hmac_b64("qq-secret", body)
        resp = await client.post("/webhook/qqbot", data=body, headers={"X-Signature": sig})
        assert resp.status == 200
        assert (await resp.read()) == b"qq-chal"

    async def test_valid_signature_dispatches(self, server):
        adapter = self._adapter()
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"qqbot": adapter})

        payload = {"t": "GROUP_AT_MESSAGE_CREATE", "d": {"author": {"id": "u"}, "content": "hi", "id": "m"}}
        body = json.dumps(payload).encode()
        sig = _hmac_b64("qq-secret", body)
        resp = await client.post("/webhook/qqbot", data=body, headers={"X-Signature": sig})
        assert resp.status == 200
        assert len(calls) == 1

    async def test_missing_signature_rejected_401(self, server):
        adapter = self._adapter()
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"qqbot": adapter})
        resp = await client.post("/webhook/qqbot", data=b'{"t":"x"}')
        assert resp.status == 401
        assert calls == []


# ===========================================================================
# DingTalk
# ===========================================================================
class TestDingtalkRoute:
    async def test_check_url_challenge_echoed(self, server):
        adapter = DingtalkAdapter(webhook_secret="dt-secret")
        client = await server({"dingtalk": adapter})

        ts = "1700000000"
        sign = _compute_robot_sign("dt-secret", ts)
        resp = await client.post(
            "/webhook/dingtalk",
            data=json.dumps({"type": "check_url", "challenge": "dt-chal"}).encode(),
            params={"timestamp": ts, "sign": sign},
        )
        assert resp.status == 200
        assert (await resp.read()) == b"dt-chal"

    async def test_valid_signature_dispatches(self, server):
        adapter = DingtalkAdapter(webhook_secret="dt-secret")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"dingtalk": adapter})

        ts = "1700000000"
        sign = _compute_robot_sign("dt-secret", ts)
        payload = {"msgtype": "text", "text": {"content": "hi dingtalk"}, "senderId": "u", "conversationId": "c"}
        resp = await client.post(
            "/webhook/dingtalk",
            data=json.dumps(payload).encode(),
            params={"timestamp": ts, "sign": sign},
        )
        assert resp.status == 200
        assert len(calls) == 1

    async def test_missing_sign_rejected_401(self, server):
        adapter = DingtalkAdapter(webhook_secret="dt-secret")
        calls = []
        _replace_handler(adapter, calls)
        client = await server({"dingtalk": adapter})
        resp = await client.post("/webhook/dingtalk", data=b'{"msgtype":"text"}')
        assert resp.status == 401
        assert calls == []


# ===========================================================================
# WeCom
# ===========================================================================
class TestWeComRoute:
    WECOM_XML = (
        "<xml><ToUserName><![CDATA[corp]]></ToUserName>"
        "<FromUserName><![CDATA[user1]]></FromUserName>"
        "<CreateTime>1700000000</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[hello wecom]]></Content>"
        "<MsgId>123</MsgId></xml>"
    )

    def _adapter(self):
        return WeComAdapter(corpid="c", corpsecret="s", agentid="1", token="wtok",
                            encoding_aes_key="aes-key-1234567890abc")

    async def test_get_url_verification_echoes_echostr(self, server):
        adapter = self._adapter()
        client = await server({"wecom": adapter})

        ts, nonce, echostr = "1700000000", "abc", "echo-ok"
        msg_sig = wecom_sha1("wtok", ts, nonce, echostr)
        resp = await client.get(
            "/webhook/wecom",
            params={"timestamp": ts, "nonce": nonce, "echostr": echostr, "msg_signature": msg_sig},
        )
        assert resp.status == 200
        assert (await resp.read()) == b"echo-ok"

    async def test_get_url_verification_bad_signature_401(self, server):
        adapter = self._adapter()
        client = await server({"wecom": adapter})
        resp = await client.get(
            "/webhook/wecom",
            params={"timestamp": "1700000000", "nonce": "abc", "echostr": "e", "msg_signature": "bad"},
        )
        assert resp.status == 401

    async def test_post_encrypted_message_dispatches(self, server, monkeypatch):
        monkeypatch.setattr(
            WeComAdapter, "decrypt_message",
            staticmethod(lambda aes, enc: self.WECOM_XML),
        )
        adapter = self._adapter()
        received = []
        adapter.set_message_handler(received.append)
        client = await server({"wecom": adapter})

        ts, nonce, encrypt = "1700000000", "abc", "encrypted-blob"
        msg_sig = wecom_sha1("wtok", ts, nonce, encrypt)
        body = json.dumps({"MsgSignature": msg_sig, "TimeStamp": ts, "Nonce": nonce, "Encrypt": encrypt}).encode()
        resp = await client.post("/webhook/wecom", data=body)
        assert resp.status == 200
        assert len(received) == 1
        assert received[0].text == "hello wecom"

    async def test_post_encrypted_message_bad_signature_401(self, server, monkeypatch):
        monkeypatch.setattr(WeComAdapter, "decrypt_message", staticmethod(lambda aes, enc: self.WECOM_XML))
        adapter = self._adapter()
        client = await server({"wecom": adapter})
        body = json.dumps({
            "MsgSignature": "bad", "TimeStamp": "1700000000", "Nonce": "abc", "Encrypt": "x",
        }).encode()
        resp = await client.post("/webhook/wecom", data=body)
        assert resp.status == 401


# ===========================================================================
# Weixin
# ===========================================================================
class TestWeixinRoute:
    WX_XML = (
        "<xml><ToUserName><![CDATA[mp]]></ToUserName>"
        "<FromUserName><![CDATA[openid1]]></FromUserName>"
        "<CreateTime>1700000000</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[hello weixin]]></Content>"
        "<MsgId>999</MsgId></xml>"
    )

    def _adapter(self):
        return WeixinAdapter(token="wxtok")

    async def test_get_url_verification_echoes_echostr(self, server):
        adapter = self._adapter()
        client = await server({"weixin": adapter})

        ts, nonce, echostr = "1700000000", "abc", "wx-echo"
        sig = weixin_sha1("wxtok", ts, nonce, echostr)
        resp = await client.get(
            "/webhook/weixin",
            params={"timestamp": ts, "nonce": nonce, "echostr": echostr, "signature": sig},
        )
        assert resp.status == 200
        assert (await resp.read()) == b"wx-echo"

    async def test_post_plaintext_xml_dispatches(self, server):
        adapter = self._adapter()
        received = []
        adapter.set_message_handler(received.append)
        client = await server({"weixin": adapter})

        ts, nonce = "1700000000", "abc"
        sig = weixin_sha1("wxtok", ts, nonce)
        resp = await client.post(
            "/webhook/weixin",
            data=self.WX_XML.encode(),
            params={"timestamp": ts, "nonce": nonce, "signature": sig},
        )
        assert resp.status == 200
        assert len(received) == 1
        assert received[0].text == "hello weixin"

    async def test_post_plaintext_missing_signature_rejected_401(self, server):
        adapter = self._adapter()
        received = []
        adapter.set_message_handler(received.append)
        client = await server({"weixin": adapter})

        resp = await client.post(
            "/webhook/weixin",
            data=self.WX_XML.encode(),
            params={"timestamp": "1700000000", "nonce": "abc"},
        )
        assert resp.status == 401
        assert received == []


# ===========================================================================
# BlueBubbles
# ===========================================================================
class TestBlueBubblesRoute:
    async def test_valid_secret_dispatches(self, server, monkeypatch):
        monkeypatch.setenv("BLUEBUBBLES_WEBHOOK_SECRET", "bb-secret")
        adapter = BlueBubblesAdapter()
        received = []

        async def fake_inbound(payload):
            return MessageEvent(text="hello", sender_id="s", chat_id="c", platform="bluebubbles")

        adapter.handle_inbound = fake_inbound
        adapter.set_message_handler(received.append)
        client = await server({"bluebubbles": adapter})

        resp = await client.post(
            "/webhook/bluebubbles",
            data=b'{"text":"hello"}',
            headers={"X-Webhook-Secret": "bb-secret"},
        )
        assert resp.status == 200
        assert len(received) == 1

    async def test_missing_secret_rejected_401(self, server, monkeypatch):
        monkeypatch.setenv("BLUEBUBBLES_WEBHOOK_SECRET", "bb-secret")
        adapter = BlueBubblesAdapter()
        client = await server({"bluebubbles": adapter})
        resp = await client.post("/webhook/bluebubbles", data=b'{"text":"hello"}')
        assert resp.status == 401

    async def test_no_env_secret_route_not_registered(self, server, monkeypatch):
        monkeypatch.delenv("BLUEBUBBLES_WEBHOOK_SECRET", raising=False)
        adapter = BlueBubblesAdapter()
        client = await server({"bluebubbles": adapter})
        resp = await client.post("/webhook/bluebubbles", data=b'{"text":"hello"}')
        assert resp.status == 404


# ===========================================================================
# Cross-cutting behaviour
# ===========================================================================
class TestRouteGatingAndMetaIsolation:
    async def test_platform_not_in_registry_is_404(self, server, monkeypatch):
        """A platform with no adapter and no env creds exposes no route."""
        for var in ("YUANBAO_ACCESS_TOKEN", "YUANBAO_TOKEN", "YUANBAO_WEBHOOK_SECRET"):
            monkeypatch.delenv(var, raising=False)
        client = await server({})
        resp = await client.post("/webhook/yuanbao", data=b'{}')
        assert resp.status == 404

    async def test_meta_route_does_not_fan_out_to_other_platforms(self, server, monkeypatch):
        """/webhook/meta only dispatches to Meta-family adapters."""
        ws._app_secret = "meta-secret"
        ws._verify_token = "meta-token"

        meta_adapter = type("FakeMeta", (), {"handle_webhook_payload": None})()
        meta_calls = []
        async def meta_handler(payload):
            meta_calls.append(payload)
        meta_adapter.handle_webhook_payload = meta_handler

        line_adapter = LineAdapter(channel_access_token="tok")
        line_calls = []
        _replace_handler(line_adapter, line_calls)

        client = await server({"meta": meta_adapter, "line": line_adapter})

        body = b'{"entry":[{"changes":[{"value":{"messages":[{"from":"1","id":"m","type":"text","text":{"body":"hi"}}]}}]}]}'
        sig = ws.compute_meta_signature("meta-secret", body)
        resp = await client.post("/webhook/meta", data=body, headers={"X-Hub-Signature-256": sig})
        assert resp.status == 200
        assert len(meta_calls) == 1
        assert line_calls == []
