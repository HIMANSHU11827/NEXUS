"""Feishu (飞书 / Lark) gateway adapter for NEXUS.

Sends messages through the Feishu OpenAPI using a cached
``tenant_access_token`` (self-built app, ``/auth/v3/tenant_access_token/internal``)
and the ``im/v1/messages`` endpoint. Inbound events arrive via the event
subscription webhook; helpers are provided to verify the request signature and
to normalise a received event payload into a :class:`MessageEvent`.

The adapter is **env-gated**: ``connect()`` returns ``False`` unless both
``FEISHU_APP_ID`` (alias ``LARK_APP_ID``) and ``FEISHU_APP_SECRET`` (alias
``LARK_APP_SECRET``) are present, and all parsing / signature logic is pure so
it can be unit tested without network access or live credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional, Tuple

import httpx

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

FEISHU_APP_ID_ENV = ("FEISHU_APP_ID", "LARK_APP_ID")
FEISHU_APP_SECRET_ENV = ("FEISHU_APP_SECRET", "LARK_APP_SECRET")


class FeishuAdapter(BasePlatformAdapter):
    """NEXUS Feishu (Lark) Adapter."""

    name = "feishu"
    required_env = FEISHU_APP_ID_ENV + FEISHU_APP_SECRET_ENV

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        verification_token: str = "",
        timeout: float = 30.0,
    ):
        super().__init__("feishu")
        self.app_id = app_id or self._first_env(FEISHU_APP_ID_ENV)
        self.app_secret = app_secret or self._first_env(FEISHU_APP_SECRET_ENV)
        self.verification_token = verification_token or os.getenv(
            "FEISHU_VERIFICATION_TOKEN", os.getenv("LARK_VERIFICATION_TOKEN", "")
        )
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._tenant_access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @staticmethod
    def _first_env(names):
        for name in names:
            val = os.getenv(name, "")
            if val:
                return val
        return ""

    # ------------------------------------------------------------------ #
    # Configuration / gating
    # ------------------------------------------------------------------ #
    def is_configured(self) -> bool:
        """True only when both app id and secret are present."""
        return bool(self.app_id and self.app_secret)

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "Feishu adapter unavailable: set FEISHU_APP_ID and FEISHU_APP_SECRET"
            )
            return False

        try:
            self._client = httpx.AsyncClient(base_url=FEISHU_API_BASE, timeout=self.timeout)
            if not await self._fetch_tenant_access_token():
                return False
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"Feishu connection failed: {e}")
            return False

    async def disconnect(self):
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover - network dependent
                pass
            self._client = None
        self._tenant_access_token = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ #
    # Token management
    # ------------------------------------------------------------------ #
    async def _fetch_tenant_access_token(self) -> bool:
        if self._client is None:
            return False
        try:
            resp = await self._client.post(
                "/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            data = resp.json()
            if data.get("code", 0) != 0:
                logger.error(f"Feishu token fetch failed: {data.get('msg')}")
                return False
            self._tenant_access_token = data.get("tenant_access_token")
            self._token_expires_at = time.time() + int(data.get("expire", 7200)) - 60
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"Feishu token fetch failed: {e}")
            return False

    async def _ensure_token(self) -> bool:
        if self._tenant_access_token and self._token_expires_at > time.time():
            return True
        return await self._fetch_tenant_access_token()

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        if not await self._ensure_token():
            return SendResult(success=False, error="Token unavailable")

        headers = {"Authorization": f"Bearer {self._tenant_access_token}"}
        content = json.dumps({"text": text})

        try:
            if reply_to:
                url = f"/im/v1/messages/{reply_to}/reply"
                payload = {"msg_type": "text", "content": content}
                resp = await self._client.post(url, headers=headers, json=payload)
            else:
                url = "/im/v1/messages"
                params = {"receive_id_type": "chat_id"}
                payload = {
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": content,
                }
                resp = await self._client.post(
                    url, headers=headers, params=params, json=payload
                )

            data = resp.json()
            if data.get("code", 0) != 0:
                return SendResult(
                    success=False, error=data.get("msg", "feishu send failed")
                )
            return SendResult(
                success=True,
                message_id=str(data.get("data", {}).get("message_id", "")),
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Inbound: signature verification + parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def compute_signature(token: str, timestamp: str, nonce: str) -> str:
        """Compute the Feishu event request signature (HMAC-SHA256, base64)."""
        bytes_to_sign = f"{timestamp}{nonce}{token}".encode("utf-8")
        digest = hmac.new(token.encode("utf-8"), bytes_to_sign, hashlib.sha256).digest()
        import base64

        return base64.b64encode(digest).decode("ascii")

    @classmethod
    def verify_callback(
        cls, token: str, timestamp: str, nonce: str, signature: str
    ) -> bool:
        """Validate a Feishu webhook request signature."""
        expected = cls.compute_signature(token, timestamp, nonce)
        return hmac.compare_digest(expected, signature)

    @classmethod
    def parse_event(cls, payload: dict) -> Tuple[Optional[str], Optional[MessageEvent]]:
        """Normalise a Feishu event payload.

        Returns a ``(challenge, event)`` tuple. For a ``url_verification``
        request ``challenge`` is the string to echo and ``event`` is ``None``.
        For a message receive event ``event`` is the :class:`MessageEvent` and
        ``challenge`` is ``None``. Pure / synchronous for unit testing.
        """
        if not isinstance(payload, dict):
            return None, None

        event_type = payload.get("type")
        if event_type == "url_verification":
            return payload.get("challenge"), None

        event = payload.get("event")
        if not isinstance(event, dict):
            return None, None
        message = event.get("message")
        if not isinstance(message, dict):
            return None, None

        try:
            content = json.loads(message.get("content", "{}"))
        except (json.JSONDecodeError, TypeError):
            content = {}
        text = content.get("text", "")

        sender = message.get("sender", {})
        sender_id_map = sender.get("sender_id", {}) if isinstance(sender, dict) else {}
        sender_id = (
            sender_id_map.get("open_id")
            or sender_id_map.get("user_id")
            or sender_id_map.get("union_id")
            or ""
        )
        chat_id = message.get("chat_id") or message.get("conversation_id") or ""

        if not text:
            return None, None

        return None, MessageEvent(
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            platform="feishu",
            message_type="text",
            message_id=message.get("message_id"),
        )

    async def handle_webhook_payload(self, payload: dict) -> Optional[MessageEvent]:
        """Convenience hook used by a webhook receiver.

        Verifies the payload (best-effort) and dispatches a parsed event to the
        registered message handler, returning the emitted :class:`MessageEvent`.
        """
        challenge, event = self.parse_event(payload)
        if challenge is not None:
            return None
        if event is not None and self._on_message:
            result = self._on_message(event)
            if hasattr(result, "__await__"):
                await result
        return event
