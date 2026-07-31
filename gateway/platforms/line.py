"""NEXUS LINE Adapter (LINE Messaging API).

Implements the LINE Bot push/reply Messaging API over HTTP (via ``httpx``) and
parses inbound webhook callbacks. No third-party SDK is required, so the module
is always importable; the ``httpx.AsyncClient`` transport is injectable for
tests.

Webhook signature verification uses HMAC-SHA256 (stdlib ``hmac``/``hashlib``),
which LINE uses to authenticate callbacks when ``LINE_CHANNEL_SECRET`` is set.

Environment variables
----------------------
``LINE_CHANNEL_ACCESS_TOKEN``  Long-lived channel access token (**required**)
``LINE_CHANNEL_TOKEN``         Alias for the access token
``LINE_CHANNEL_SECRET``        Channel secret (enables webhook verification)
``LINE_API_BASE``              API base URL override (default: v2/bot endpoint)
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import os
from typing import List, Optional

import httpx

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_REQUIRED_ENV = ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_TOKEN")


class LineAdapter(BasePlatformAdapter):
    """LINE Messaging API gateway adapter."""

    name = "line"
    required_env = LINE_REQUIRED_ENV

    def __init__(
        self,
        channel_access_token: str = "",
        channel_secret: str = "",
        api_base: str = "",
    ):
        super().__init__("line")
        self.channel_access_token = (
            channel_access_token
            or os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
            or os.getenv("LINE_CHANNEL_TOKEN", "")
        )
        self.channel_secret = channel_secret or os.getenv("LINE_CHANNEL_SECRET", "")
        self.api_base = api_base or os.getenv("LINE_API_BASE", LINE_API_BASE)
        self._client: Optional[httpx.AsyncClient] = None

    def is_configured(self) -> bool:
        """True when a channel access token is available."""
        return bool(self.channel_access_token)

    async def connect(self) -> bool:
        if not self.channel_access_token:
            logger.error(
                "LINE_CHANNEL_ACCESS_TOKEN not set — LINE adapter disabled"
            )
            return False
        try:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                headers={"Authorization": f"Bearer {self.channel_access_token}"},
                timeout=30.0,
            )
            # Best-effort token verification (does not block connect).
            try:
                resp = await self._client.get("/info")
                if resp.status_code == 200:
                    logger.info("NEXUS LINE Adapter online (token verified)")
                else:
                    logger.warning(
                        "LINE token verification returned %s", resp.status_code
                    )
            except Exception as e:  # pragma: no cover - network dependent
                logger.debug(f"LINE token verification skipped: {e}")
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"LINE connection failed: {e}")
            return False

    async def disconnect(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ #
    # Webhook parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_event(event: dict) -> Optional[MessageEvent]:
        """Parse a single LINE webhook event into a ``MessageEvent``.

        Returns ``None`` for non-message events (e.g. ``follow``, ``postback``)
        or unsupported message types. Pure / synchronous for unit testing.
        """
        if not isinstance(event, dict):
            return None
        if event.get("type") != "message":
            return None
        message = event.get("message", {})
        if message.get("type") != "text":
            return None

        text = message.get("text", "")
        source = event.get("source", {})
        src_type = source.get("type")
        sender_id = source.get("userId", "")

        if src_type == "group":
            chat_id = source.get("groupId", "")
        elif src_type == "room":
            chat_id = source.get("roomId", "")
        else:
            # user (or unknown) -> 1:1 chat keyed by userId
            chat_id = source.get("userId", "")

        if not text or not sender_id:
            return None

        return MessageEvent(
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            platform="line",
            message_type="text",
            message_id=event.get("id"),
            reply_to_id=event.get("replyToken"),
            raw_data=event,
        )

    async def handle_webhook_payload(self, payload: dict):
        """Dispatch a raw LINE webhook ``payload`` to the message handler."""
        if not isinstance(payload, dict) or not self._on_message:
            return
        for event in payload.get("events", []):
            parsed = self._parse_event(event)
            if parsed is not None:
                await self._on_message(parsed)

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify a LINE webhook ``X-Line-Signature`` HMAC-SHA256 value."""
        if not self.channel_secret:
            return False
        mac = hmac.new(
            self.channel_secret.encode("utf-8"), body, hashlib.sha256
        )
        expected = base64.b64encode(mac.digest()).decode("ascii")
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------ #
    # Sending
    # ------------------------------------------------------------------ #
    def _build_text_payload(self, chat_id: str, text: str, reply_to: Optional[str]):
        if reply_to:
            return "/message/reply", {
                "replyToken": reply_to,
                "messages": [{"type": "text", "text": text}],
            }
        return "/message/push", {
            "to": chat_id,
            "messages": [{"type": "text", "text": text}],
        }

    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        try:
            url, payload = self._build_text_payload(chat_id, text, reply_to)
            resp = await self._client.post(url, json=payload)
            data = resp.json()
            return SendResult(
                success=resp.is_success,
                message_id=data.get("messageId"),
                error=None if resp.is_success else str(data),
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(
        self, chat_id: str, image_url: str, caption: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        try:
            if caption:
                text_res = await self.send_text(chat_id, caption)
                if not text_res.success:
                    return text_res
            payload = {
                "to": chat_id,
                "messages": [
                    {
                        "type": "image",
                        "originalContentUrl": image_url,
                        "previewImageUrl": image_url,
                    }
                ],
            }
            resp = await self._client.post("/message/push", json=payload)
            data = resp.json()
            return SendResult(
                success=resp.is_success,
                message_id=data.get("messageId"),
                error=None if resp.is_success else str(data),
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        """LINE has no typing indicator; no-op to satisfy the interface."""
        return None
