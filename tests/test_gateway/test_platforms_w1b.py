"""Tests for the Wave-1b gateway adapters (Teams, Google Chat, WeCom, Feishu).

These adapters are env-gated and degrade gracefully when credentials are
absent. We verify construction, env-var fallback, and the send path with a
monkeypatched transport (no network).
"""

import asyncio
import os

import pytest

from gateways.base import SendResult
from gateways.platforms import get_adapter


def _setenv(**kw):
    for k, v in kw.items():
        os.environ.setdefault(k, v)


def test_teams_adapter_constructs_and_gates(monkeypatch):
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TEAMS_TENANT_ID", raising=False)
    monkeypatch.delenv("TEAMS_CLIENT_ID", raising=False)
    monkeypatch.delenv("TEAMS_CLIENT_SECRET", raising=False)
    adapter = get_adapter("teams")
    assert adapter.platform == "teams"
    # Without any env, configure() is False and connect() returns False.
    assert adapter.is_configured() is False
    assert asyncio.run(adapter.connect()) is False


def test_teams_adapter_webhook_mode_from_env(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.webhook/teams")
    adapter = get_adapter("teams")
    assert adapter.is_configured() is True
    assert adapter.mode == "webhook"


def test_google_chat_adapter_constructs_and_gates(monkeypatch):
    for v in ("GOOGLE_CHAT_WEBHOOK_URL", "GOOGLE_CHAT_SPACE", "GOOGLE_CHAT_KEY"):
        monkeypatch.delenv(v, raising=False)
    adapter = get_adapter("google_chat")
    assert adapter.platform == "google_chat"
    assert adapter.is_configured() is False
    assert asyncio.run(adapter.connect()) is False


def test_google_chat_adapter_rest_mode_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CHAT_SPACE", "spaces/abc")
    monkeypatch.setenv("GOOGLE_CHAT_KEY", "my-key")
    adapter = get_adapter("google_chat")
    assert adapter.is_configured() is True
    assert adapter.mode == "rest"


def test_wecom_adapter_constructs(monkeypatch):
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_CORPSECRET", "secret")
    monkeypatch.setenv("WECOM_AGENTID", "agent")
    adapter = get_adapter("wecom")
    assert adapter.platform == "wecom"
    assert adapter.is_configured() is True


def test_feishu_adapter_constructs(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    adapter = get_adapter("feishu")
    assert adapter.platform == "feishu"
    assert adapter.is_configured() is True


async def test_teams_send_text_uses_fake_client(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.webhook/teams")
    adapter = get_adapter("teams")
    await adapter.connect()

    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "msg-1"}

    async def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    async def fake_aclose():
        return None

    adapter._client.post = fake_post
    adapter._client.aclose = fake_aclose

    result = await adapter.send_text("general", "hello")
    assert isinstance(result, SendResult)
    assert result.success is True
    assert captured["json"]["text"] == "hello"


async def test_google_chat_send_text_uses_fake_client(monkeypatch):
    monkeypatch.setenv("GOOGLE_CHAT_WEBHOOK_URL", "https://chat.googleapis.com/v1/webhook")
    adapter = get_adapter("google_chat")
    await adapter.connect()

    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"name": "spaces/x/messages/y"}

    async def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    async def fake_aclose():
        return None

    adapter._client.post = fake_post
    adapter._client.aclose = fake_aclose

    result = await adapter.send_text("general", "hi there")
    assert result.success is True
    assert result.message_id == "spaces/x/messages/y"
    assert captured["json"]["text"] == "hi there"
