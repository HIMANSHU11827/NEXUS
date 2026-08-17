"""Tests for DingTalk + BlueBubbles adapters (Wave 2 gap-fill).

Env-gated, graceful no-dep, with monkeypatched transport (no network).
"""

import asyncio
import os

import pytest

from gateways.base import SendResult
from gateways.platforms import get_adapter


def test_dingtalk_adapter_gates_without_env(monkeypatch):
    for v in ("DINGTALK_WEBHOOK", "DINGTALK_WEBHOOK_ACCESS_TOKEN", "DINGTALK_ROBOT_TOKEN",
              "DINGTALK_APP_KEY", "DINGTALK_APP_SECRET", "DINGTALK_WEBHOOK_SECRET"):
        monkeypatch.delenv(v, raising=False)
    adapter = get_adapter("dingtalk")
    assert adapter.platform == "dingtalk"
    assert adapter.is_configured() is False
    assert asyncio.run(adapter.connect()) is False


def test_dingtalk_adapter_webhook_mode(monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK_ACCESS_TOKEN", "tok")
    adapter = get_adapter("dingtalk")
    assert adapter.is_configured() is True


def test_bluebubbles_adapter_gates_without_env(monkeypatch):
    for v in ("BLUEBUBBLES_SERVER_URL", "BLUEBUBBLES_PASSWORD"):
        monkeypatch.delenv(v, raising=False)
    adapter = get_adapter("bluebubbles")
    # get_adapter returns the class instance; verify via is_configured
    inst = get_adapter("bluebubbles")
    assert inst.platform == "bluebubbles"
    assert inst.is_configured() is False
    assert asyncio.run(inst.connect()) is False


def test_bluebubbles_adapter_configured_with_env(monkeypatch):
    monkeypatch.setenv("BLUEBUBBLES_SERVER_URL", "http://127.0.0.1:8645")
    monkeypatch.setenv("BLUEBUBBLES_PASSWORD", "secret")
    adapter = get_adapter("bluebubbles")
    assert adapter.is_configured() is True


async def test_dingtalk_send_text_uses_fake_client(monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK_ACCESS_TOKEN", "tok")
    adapter = get_adapter("dingtalk")
    await adapter.connect()

    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"errcode": 0, "msgid": "dt-1"}

    async def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    async def fake_aclose():
        return None

    adapter._client.post = fake_post
    adapter._client.aclose = fake_aclose

    result = await adapter.send_text("chat", "hello dingtalk")
    assert isinstance(result, SendResult)
    assert result.success is True
    assert captured["json"]["msgtype"] == "text"


async def test_bluebubbles_send_text_uses_fake_client(monkeypatch):
    monkeypatch.setenv("BLUEBUBBLES_SERVER_URL", "http://127.0.0.1:8645")
    monkeypatch.setenv("BLUEBUBBLES_PASSWORD", "secret")
    adapter = get_adapter("bluebubbles")
    await adapter.connect()

    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"guid": "bb-1"}

    async def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    async def fake_aclose():
        return None

    adapter._client.post = fake_post
    adapter._client.aclose = fake_aclose

    result = await adapter.send_text("iMessage;-;abc", "hello imessage")
    assert isinstance(result, SendResult)
    assert result.success is True
    assert result.message_id == "bb-1"
    assert captured["json"]["message"] == "hello imessage"
