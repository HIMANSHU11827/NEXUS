"""Tests for webhook signature verification and env-gating fixes.

Exercises the security hardening applied to:
- Meta webhook X-Hub-Signature-256 HMAC in ``gateway/webhook_server.py``
- Twilio X-Twilio-Signature validation in ``gateway/platforms/sms.py``
- Env-gating completeness in ``gateway/run.py`` (whatsapp, email)
- Telegram bot lazy loading in ``gateway/telegram_bot.py``

All tests are network-free and env-var-isolated.
"""

import asyncio
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

from gateways.webhook_server import compute_meta_signature, verify_meta_signature
from gateways.platforms.sms import valid_twilio_signature
from gateways.run import _PLATFORM_ENV_MAP, _has_required_env


# =============================================================================
# Meta webhook X-Hub-Signature-256
# =============================================================================

class TestMetaWebhookSignature:
    """Verify HMAC-SHA256 signature logic for Meta webhook POST."""

    _SECRET = "my_app_secret_123"
    _PAYLOAD = b'{"entry":[]}'

    def test_compute_signature_returns_sha256_prefixed(self):
        sig = compute_meta_signature(self._SECRET, self._PAYLOAD)
        assert sig.startswith("sha256=")
        _, hex_part = sig.split("=", 1)
        # validate hex length: SHA256 = 64 hex chars
        assert len(hex_part) == 64
        int(hex_part, 16)  # raises on invalid hex

    def test_compute_signature_deterministic(self):
        assert compute_meta_signature(self._SECRET, self._PAYLOAD) == \
               compute_meta_signature(self._SECRET, self._PAYLOAD)

    def test_compute_signature_differs_per_secret(self):
        assert compute_meta_signature(self._SECRET, self._PAYLOAD) != \
               compute_meta_signature("other_secret", self._PAYLOAD)

    def test_compute_signature_differs_per_body(self):
        assert compute_meta_signature(self._SECRET, self._PAYLOAD) != \
               compute_meta_signature(self._SECRET, b'{"entry":[],"evil":true}')

    def test_verify_valid_signature(self):
        sig = compute_meta_signature(self._SECRET, self._PAYLOAD)
        assert verify_meta_signature(self._SECRET, self._PAYLOAD, sig) is True

    def test_verify_rejects_tampered_body(self):
        sig = compute_meta_signature(self._SECRET, self._PAYLOAD)
        tampered = b'{"entry":[],"evil":true}'
        assert verify_meta_signature(self._SECRET, tampered, sig) is False

    def test_verify_rejects_wrong_secret(self):
        sig = compute_meta_signature("wrong_secret", self._PAYLOAD)
        assert verify_meta_signature(self._SECRET, self._PAYLOAD, sig) is False

    def test_verify_rejects_empty_secret(self):
        sig = compute_meta_signature(self._SECRET, self._PAYLOAD)
        assert verify_meta_signature("", self._PAYLOAD, sig) is False

    def test_verify_rejects_empty_signature(self):
        assert verify_meta_signature(self._SECRET, self._PAYLOAD, "") is False

    def test_verify_rejects_missing_signature(self):
        assert verify_meta_signature(self._SECRET, self._PAYLOAD, "sha256=") is False

    def test_verify_case_insensitive(self):
        sig = compute_meta_signature(self._SECRET, self._PAYLOAD)
        upper = sig.upper()
        assert verify_meta_signature(self._SECRET, self._PAYLOAD, upper) is True

    def test_verify_constant_time_with_garbage(self):
        """Should not crash on garbage inputs."""
        assert verify_meta_signature("", b"", "sha256=0000") is False
        assert verify_meta_signature("s", b"", "") is False


# ---------------------------------------------------------------------------
# Integration: POST /webhook/meta enforces X-Hub-Signature-256
# ---------------------------------------------------------------------------
class TestMetaWebhookRoute:
    """End-to-end checks against the aiohttp webhook route (no network)."""

    _SECRET = "route_app_secret"
    _TOKEN = "route_verify_token"

    @pytest.fixture
    async def client(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        import gateways.webhook_server as ws

        ws._adapters = {}
        ws._app_secret = self._SECRET
        ws._verify_token = self._TOKEN

        app = web.Application()
        app.add_routes(ws.routes)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            yield client
        finally:
            await client.close()

    async def test_post_missing_signature_rejected_401(self, client):
        resp = await client.post("/webhook/meta", data=b'{"entry":[]}')
        assert resp.status == 401

    async def test_post_invalid_signature_rejected_401(self, client):
        resp = await client.post(
            "/webhook/meta",
            data=b'{"entry":[]}',
            headers={"X-Hub-Signature-256": "sha256=deadbeef"},
        )
        assert resp.status == 401

    async def test_post_valid_signature_accepted_200(self, client):
        body = b'{"entry":[]}'
        sig = compute_meta_signature(self._SECRET, body)
        resp = await client.post(
            "/webhook/meta",
            data=body,
            headers={"X-Hub-Signature-256": sig},
        )
        assert resp.status == 200
        assert await resp.read() == b"EVENT_RECEIVED"

    async def test_get_verify_handshake_still_works(self, client):
        resp = await client.get(
            "/webhook/meta",
            params={"hub.mode": "subscribe", "hub.verify_token": self._TOKEN, "hub.challenge": "ch_123"},
        )
        assert resp.status == 200
        assert await resp.read() == b"ch_123"


# =============================================================================
# Twilio X-Twilio-Signature (HMAC-SHA1, base64)
# =============================================================================

class TestTwilioWebhookSignature:
    """Verify HMAC-SHA1 signature logic for Twilio SMS webhook."""

    _AUTH_TOKEN = "my_auth_token_456"
    _URL = "https://myhost.example/sms"

    def _valid_signature(self, params, auth_token=None) -> str:
        """Helper: compute the expected X-Twilio-Signature."""
        token = auth_token or self._AUTH_TOKEN
        items = sorted(params.items())
        signed = self._URL + "".join(k + str(v) for k, v in items)
        import base64
        return base64.b64encode(
            hmac.new(token.encode(), signed.encode(), hashlib.sha1).digest()
        ).decode("ascii")

    def test_valid_signature_accepts(self):
        params = {"From": "+15551112222", "Body": "hello", "MessageSid": "SM123"}
        sig = self._valid_signature(params)
        assert valid_twilio_signature(self._URL, params, sig, self._AUTH_TOKEN) is True

    def test_rejects_tampered_body(self):
        params = {"From": "+15551112222", "Body": "hello", "MessageSid": "SM123"}
        sig = self._valid_signature(params)
        tampered = dict(params, Body="evil")
        assert valid_twilio_signature(self._URL, tampered, sig, self._AUTH_TOKEN) is False

    def test_rejects_empty_params(self):
        assert valid_twilio_signature(self._URL, {}, "sig", self._AUTH_TOKEN) is False

    def test_rejects_missing_auth_token(self):
        assert valid_twilio_signature(self._URL, {}, "sig", "") is False

    def test_rejects_missing_signature_header(self):
        assert valid_twilio_signature(self._URL, {}, "", self._AUTH_TOKEN) is False

    def test_rejects_wrong_auth_token(self):
        params = {"From": "+15551112222", "Body": "hello", "MessageSid": "SM123"}
        sig = self._valid_signature(params, auth_token="correct_token")
        # validate with wrong token
        assert valid_twilio_signature(self._URL, params, sig, "wrong_token") is False

    def test_sort_order_matters(self):
        """Different key order yields the same signature because sorted()."""
        params_a = {"b": "1", "a": "2"}
        params_b = {"a": "2", "b": "1"}
        sig = self._valid_signature(params_a)
        assert valid_twilio_signature(self._URL, params_b, sig, self._AUTH_TOKEN) is True


# =============================================================================
# Env-gating: WhatsApp and Email now require full credential sets
# =============================================================================

class TestWhatsappEnvGate:
    """WhatsApp requires both a token AND a phone-number-id to register."""

    def test_env_map_requires_phone_id(self):
        groups = _PLATFORM_ENV_MAP["whatsapp"]
        # Expect: token group + phone-number-id group
        group_names = set()
        for group in groups:
            for name in group:
                group_names.add(name)
        assert "META_PHONE_NUMBER_ID" in group_names or "WHATSAPP_PHONE_ID" in group_names
        assert "META_ACCESS_TOKEN" in group_names or "WHATSAPP_TOKEN" in group_names

    def test_has_required_env_only_token_missing_phone(self, monkeypatch):
        monkeypatch.setenv("META_ACCESS_TOKEN", "tok123")
        monkeypatch.delenv("META_PHONE_NUMBER_ID", raising=False)
        monkeypatch.delenv("WHATSAPP_PHONE_ID", raising=False)
        assert _has_required_env(_PLATFORM_ENV_MAP["whatsapp"]) is False

    def test_has_required_env_token_and_phone(self, monkeypatch):
        monkeypatch.setenv("META_ACCESS_TOKEN", "tok123")
        monkeypatch.setenv("META_PHONE_NUMBER_ID", "phone123")
        assert _has_required_env(_PLATFORM_ENV_MAP["whatsapp"]) is True

    def test_has_required_env_token_and_whatsapp_phone(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_TOKEN", "tok123")
        monkeypatch.setenv("WHATSAPP_PHONE_ID", "phone123")
        assert _has_required_env(_PLATFORM_ENV_MAP["whatsapp"]) is True


class TestEmailEnvGate:
    """Email now requires SMTP_PASS in addition to SMTP_HOST + SMTP_USER."""

    def test_env_map_requires_smtp_pass(self):
        groups = _PLATFORM_ENV_MAP["email"]
        group_names = set()
        for group in groups:
            for name in group:
                group_names.add(name)
        assert "SMTP_PASS" in group_names

    def test_has_required_env_host_user_pass(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_USER", "user")
        monkeypatch.setenv("SMTP_PASS", "pass")
        assert _has_required_env(_PLATFORM_ENV_MAP["email"]) is True

    def test_has_required_env_missing_pass(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_USER", "user")
        monkeypatch.delenv("SMTP_PASS", raising=False)
        assert _has_required_env(_PLATFORM_ENV_MAP["email"]) is False


# =============================================================================
# Telegram bot lazy-load (orphan file no longer crashes on import)
# =============================================================================

class TestTelegramBotLazyLoad:
    """Gateway telegram_bot module must import without crash and create
    NexusLoop lazily on first access."""

    def test_module_imports_without_crashing(self):
        import importlib
        import gateways.telegram_bot as tb
        importlib.reload(tb)
        # The module-level ``get_loop`` function exists; no loop was created.
        assert hasattr(tb, "get_loop")

    def test_get_loop_creates_on_first_call(self):
        import gateways.telegram_bot as tb
        # iterate over lazy - won't block because no token
        loop1 = tb.get_loop()
        assert loop1 is not None
        assert hasattr(loop1, "root_dir")
        # cached
        loop2 = tb.get_loop()
        assert loop2 is loop1
