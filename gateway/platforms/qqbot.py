"""QQBot (QQ 机器人 / Tencent official QQ Bot) gateway adapter for NEXUS.

Outbound sends use the QQ Bot OpenAPI. An *app access token* is fetched from
``https://bots.qq.com/app/getAppAccessToken`` using ``QQBOT_APPID`` (alias
``QQ_APPID``) and ``QQBOT_SECRET`` (alias ``QQ_SECRET``); messages are then
pushed over the v2 OpenAPI (``https://api.sgroup.qq.com``):

* **C2C (private) message**: ``POST /v2/users/{openid}/messages``
* **Group message**: ``POST /v2/groups/{group_openid}/messages``
* **Guild channel message**: ``POST /v2/channels/{channel_id}/messages``

Inbound messages arrive either over the websocket gateway (handled by the
official ``qq-botpy`` SDK outside this module) or — for HTTP-only deployments —
via a signed webhook callback. This adapter exposes pure helpers to verify a
webhook signature (HMAC-SHA256 over the raw body with the client secret) and to
normalise a parsed message event payload into a :class:`MessageEvent`.

Env-gated: ``connect()`` returns ``False`` without appid + secret, and all
crypto/parse helpers are pure and unit-tested without network access.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional, Tuple

import httpx

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

QQBOT_TOKEN_API = "https://bots.qq.com/app/getAppAccessToken"
QQBOT_API_BASE = "https://api.sgroup.qq.com"

QQBOT_APPID_ENV = ("QQBOT_APPID", "QQ_APPID")
QQBOT_SECRET_ENV = ("QQBOT_SECRET", "QQ_SECRET")


class QQBotAdapter(BasePlatformAdapter):
    """NEXUS QQBot (Tencent official QQ Bot) Adapter."""

    name = "qqbot"
    required_env = QQBOT_APPID_ENV + QQBOT_SECRET_ENV

    def __init__(
        self,
        appid: str = "",
        secret: str = "",
        timeout: float = 30.0,
    ):
        super().__init__("qqbot")
        self.appid = appid or self._first_env(QQBOT_APPID_ENV)
        self.secret = secret or self._first_env(QQBOT_SECRET_ENV)
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @staticmethod
    def _first_env(names) -> str:
        for name in names:
            val = os.getenv(name, "")
            if val:
                return val
        return ""

    # ------------------------------------------------------------------ #
    # Configuration / gating
    # ------------------------------------------------------------------ #
    def is_configured(self) -> bool:
        """True only when both appid and secret are present."""
        return bool(self.appid and self.secret)

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "QQBot adapter unavailable: set QQBOT_APPID and QQBOT_SECRET "
                "(aliases QQ_APPID / QQ_SECRET)"
            )
            return False

        try:
            self._client = httpx.AsyncClient(base_url=QQBOT_API_BASE, timeout=self.timeout)
            if not await self._fetch_app_access_token():
                return False
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"QQBot connection failed: {e}")
            return False

    async def disconnect(self):
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover - network dependent
                pass
            self._client = None
        self._access_token = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ #
    # Token management
    # ------------------------------------------------------------------ #
    async def _fetch_app_access_token(self) -> bool:
        if self._client is None:
            return False
        try:
            resp = await self._client.post(
                QQBOT_TOKEN_API,
                json={"appId": self.appid, "clientSecret": self.secret},
            )
            data = resp.json()
            if "access_token" not in data:
                logger.error(f"QQBot token fetch failed: {data.get('message')}")
                return False
            self._access_token = data.get("access_token")
            self._token_expires_at = time.time() + int(data.get("expires_in", 7200)) - 60
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"QQBot token fetch failed: {e}")
            return False

    async def _ensure_token(self) -> bool:
        # A token is valid when present and unexpired. ``_token_expires_at == 0``
        # means the token was injected without expiry metadata (e.g. in tests)
        # and should be trusted as-is.
        if self._access_token and (
            self._token_expires_at == 0.0 or self._token_expires_at > time.time()
        ):
            return True
        return await self._fetch_app_access_token()

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    async def send_text(
        self,
        chat_id: str,
        text: str,
        reply_to: Optional[str] = None,
        to_type: str = "user",
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        if not await self._ensure_token():
            return SendResult(success=False, error="Token unavailable")

        if to_type == "group":
            url = f"/v2/groups/{chat_id}/messages"
        elif to_type == "channel":
            url = f"/v2/channels/{chat_id}/messages"
        else:
            url = f"/v2/users/{chat_id}/messages"

        payload: dict = {"content": text, "msg_type": 0}
        if reply_to:
            # Passive reply within the 5-minute window; ties the message to its
            # parent for the QQ platform's sequencing/threading semantics.
            payload["msg_id"] = reply_to

        headers = {
            "Authorization": f"QQBot {self._access_token}",
            "Content-Type": "application/json",
        }

        try:
            resp = await self._client.post(url, headers=headers, json=payload)
            data = resp.json()
            if data.get("code") is not None and data.get("code") != 0:
                return SendResult(
                    success=False,
                    error=data.get("message", "qqbot send failed"),
                )
            return SendResult(success=True, message_id=str(data.get("id", "")))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Inbound: webhook signature verification + event parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def verify_callback(secret: str, body: bytes, signature: str) -> bool:
        """Validate a QQBot webhook request signature.

        The platform signs the raw request body with HMAC-SHA256 using the
        client secret and base64-encodes the result.
        """
        if isinstance(body, str):
            body = body.encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        import base64

        expected = base64.b64encode(digest).decode("ascii")
        return hmac.compare_digest(expected, signature)

    @classmethod
    def parse_event(cls, payload: dict) -> Tuple[Optional[str], Optional[MessageEvent]]:
        """Normalise a QQBot event payload.

        Returns a ``(challenge, event)`` tuple. For a ``url_verification``
        request ``challenge`` is the string to echo and ``event`` is ``None``.
        For a message event ``event`` is the :class:`MessageEvent` and
        ``challenge`` is ``None``. Pure / synchronous for unit testing.
        """
        if not isinstance(payload, dict):
            return None, None

        if payload.get("challenge") is not None:
            return payload.get("challenge"), None

        event_name = payload.get("t")
        data = payload.get("d")
        if not event_name or not isinstance(data, dict):
            return None, None

        author = data.get("author") or {}
        sender_id = author.get("id", "")
        text = (data.get("content") or "").strip()
        message_id = data.get("id")

        # Route chat_id to the most specific conversation the message belongs to.
        if data.get("group_id"):
            chat_id = data["group_id"]
        elif data.get("channel_id"):
            chat_id = data["channel_id"]
        else:
            chat_id = sender_id

        if not text:
            return None, None

        return None, MessageEvent(
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            platform="qqbot",
            message_type="text",
            message_id=message_id,
        )

    async def handle_webhook_payload(
        self, payload: dict, signature: Optional[str] = None, raw_body: Optional[bytes] = None
    ) -> Optional[MessageEvent]:
        """Convenience hook used by a webhook receiver.

        Optionally verifies the callback signature, then dispatches a parsed
        event to the registered message handler and returns the emitted
        :class:`MessageEvent`.
        """
        if signature is not None and raw_body is not None and self.secret:
            if not self.verify_callback(self.secret, raw_body, signature):
                logger.warning("QQBot webhook signature verification failed")
                return None

        challenge, event = self.parse_event(payload)
        if challenge is not None:
            return None
        if event is not None and self._on_message:
            result = self._on_message(event)
            if hasattr(result, "__await__"):
                await result
        return event
