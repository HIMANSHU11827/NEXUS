"""NEXUS YuanBao (元宝) gateway adapter.

YuanBao (Tencent's AI assistant) organises conversation into **groups** that the
app calls "派 (Pai)". Each group is addressed by a numeric ``group_code``. A
group message carries a sender (with a ``user_id`` / ``nickname`` and a
``role`` of ``user``, ``yuanbao_ai`` or ``bot``), free text, and an optional
list of ``@mentions``.

This adapter implements the YuanBao group messaging surface over HTTP (via
``httpx``) and parses inbound webhook callbacks into normalised
:class:`MessageEvent` objects. No third-party SDK is required, so the module
is always importable; the ``httpx.AsyncClient`` transport is fully injectable
for tests, and every parsing / signature routine is a pure function.

``@mention`` handling
---------------------
The YuanBao gateway matches the project-wide convention that a reply containing
``@nickname`` notifies that member. ``send_text`` therefore scans the outgoing
text for ``@name`` tokens and emits a structured ``mentions`` list alongside
the raw text, so the gateway (and the YuanBao backend) can render a real
mention. Use :meth:`YuanbaoAdapter.format_mention` to build such tokens and
:meth:`YuanbaoAdapter.extract_mentions` to pull them back out.

Environment variables
----------------------
``YUANBAO_ACCESS_TOKEN``     Long-lived access token (**required** to enable)
``YUANBAO_TOKEN``            Alias for the access token
``YUANBAO_GROUP_CODE``       Default group code when none is in the chat id
``YUANBAO_API_BASE``         API base URL override (default below)
``YUANBAO_WEBHOOK_SECRET``   Shared secret for webhook signature verification
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
from typing import List, Optional, Tuple

import httpx

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

YUANBAO_API_BASE = "https://yuanbao.tencent.com/api/v1"

YUANBAO_TOKEN_ENV = ("YUANBAO_ACCESS_TOKEN", "YUANBAO_TOKEN")

# A chat id for a YuanBao group is ``group:<group_code>``.
_GROUP_PREFIX = "group:"

# Matches ``@nickname`` tokens (the nickname is everything up to the next
# whitespace or end of string). A leading space before the ``@`` is allowed.
_MENTION_RE = re.compile(r"(?:^|\s)@(?P<name>[^\s@]+)")

# Member roles understood by YuanBao.
ROLE_USER = "user"
ROLE_YUANBAO_AI = "yuanbao_ai"
ROLE_BOT = "bot"


class YuanbaoAdapter(BasePlatformAdapter):
    """NEXUS YuanBao (元宝) group-messaging gateway adapter."""

    name = "yuanbao"
    required_env = YUANBAO_TOKEN_ENV

    def __init__(
        self,
        access_token: str = "",
        group_code: str = "",
        api_base: str = "",
        webhook_secret: str = "",
        timeout: float = 30.0,
    ):
        super().__init__("yuanbao")
        self.access_token = (
            access_token
            or os.getenv("YUANBAO_ACCESS_TOKEN", "")
            or os.getenv("YUANBAO_TOKEN", "")
        )
        self.default_group_code = group_code or os.getenv("YUANBAO_GROUP_CODE", "")
        self.api_base = api_base or os.getenv("YUANBAO_API_BASE", YUANBAO_API_BASE)
        self.webhook_secret = webhook_secret or os.getenv("YUANBAO_WEBHOOK_SECRET", "")
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------ #
    # Configuration / gating
    # ------------------------------------------------------------------ #
    def is_configured(self) -> bool:
        """True only when an access token is available."""
        return bool(self.access_token)

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    async def connect(self) -> bool:
        if not self.access_token:
            logger.error(
                "YUANBAO_ACCESS_TOKEN not set — YuanBao adapter disabled"
            )
            return False
        try:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=self.timeout,
            )
            logger.info("NEXUS YuanBao Adapter online (base=%s)", self.api_base)
            return True
        except Exception as e:  # pragma: no cover - network dependent
            logger.error(f"YuanBao connection failed: {e}")
            return False

    async def disconnect(self):
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover - network dependent
                pass
            self._client = None

    # ------------------------------------------------------------------ #
    # Chat id helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def chat_id_for_group(group_code: str) -> str:
        """Build the canonical ``group:<code>`` chat id for a group."""
        return f"{_GROUP_PREFIX}{group_code}"

    def _group_code_from_chat(self, chat_id: str) -> Optional[str]:
        if chat_id.startswith(_GROUP_PREFIX):
            code = chat_id[len(_GROUP_PREFIX):]
            return code or None
        # A bare numeric code is also accepted.
        if chat_id.isdigit():
            return chat_id
        return self.default_group_code or None

    # ------------------------------------------------------------------ #
    # @mention helpers (pure)
    # ------------------------------------------------------------------ #
    @staticmethod
    def format_mention(nickname: str) -> str:
        """Return an ``@nickname`` token renderable by the gateway."""
        return f"@{nickname}"

    @classmethod
    def extract_mentions(cls, text: str) -> List[str]:
        """Return the list of ``@nickname`` tokens found in ``text``."""
        if not text:
            return []
        return [m.group("name") for m in _MENTION_RE.finditer(text)]

    # ------------------------------------------------------------------ #
    # Inbound: webhook parsing
    # ------------------------------------------------------------------ #
    @classmethod
    def parse_event(cls, payload: dict) -> Optional[MessageEvent]:
        """Normalise a YuanBao group message payload into a ``MessageEvent``.

        Returns ``None`` for non-message payloads (e.g. ``follow`` /
        ``postback``) or malformed input. Pure / synchronous for unit testing.
        """
        if not isinstance(payload, dict):
            return None
        # A webhook envelope may wrap one or more events.
        if "events" in payload and isinstance(payload["events"], list):
            # The first message event wins; callers should use
            # ``handle_webhook_payload`` to dispatch the whole list.
            for event in payload["events"]:
                parsed = cls.parse_event(event)
                if parsed is not None:
                    return parsed
            return None

        if payload.get("type") != "message":
            return None

        message_id = payload.get("message_id") or payload.get("id")
        group_code = str(payload.get("group_code", "") or "")
        sender = payload.get("sender", {}) or {}
        sender_id = sender.get("user_id", "") or sender.get("id", "") or ""
        sender_name = sender.get("nickname", "") or sender.get("name", "") or ""
        text = payload.get("content") or payload.get("text") or ""

        if not text or not sender_id:
            return None

        chat_id = (
            cls.chat_id_for_group(group_code) if group_code else ""
        )

        return MessageEvent(
            text=text,
            sender_id=sender_id,
            chat_id=chat_id,
            platform="yuanbao",
            message_type="text",
            message_id=str(message_id) if message_id is not None else None,
            reply_to_id=payload.get("reply_to_message_id"),
            raw_data=payload,
        )

    async def handle_webhook_payload(self, payload: dict):
        """Dispatch a raw YuanBao webhook ``payload`` to the message handler.

        Accepts either a single event dict or an ``{"events": [...]}`` envelope.
        Returns the list of :class:`MessageEvent` objects dispatched.
        """
        if not isinstance(payload, dict) or not self._on_message:
            return []
        events: List[dict] = payload.get("events", []) \
            if isinstance(payload.get("events"), list) else [payload]
        dispatched: List[MessageEvent] = []
        for event in events:
            parsed = self.parse_event(event)
            if parsed is not None:
                await self._on_message(parsed)
                dispatched.append(parsed)
        return dispatched

    # ------------------------------------------------------------------ #
    # Webhook signature verification
    # ------------------------------------------------------------------ #
    def verify_callback(self, timestamp: str, nonce: str, signature: str) -> bool:
        """Validate a YuanBao webhook ``X-YuanBao-Signature`` (HMAC-SHA256).

        Without a configured ``YUANBAO_WEBHOOK_SECRET`` verification cannot
        succeed, mirroring the LINE / Feishu adapters.
        """
        if not self.webhook_secret:
            return False
        expected = self.compute_signature(timestamp, nonce)
        return hmac.compare_digest(expected, signature)

    def compute_signature(self, timestamp: str, nonce: str) -> str:
        """Compute the YuanBao webhook signature (HMAC-SHA256, base64)."""
        bytes_to_sign = f"{timestamp}{nonce}{self.webhook_secret}".encode("utf-8")
        digest = hmac.new(
            self.webhook_secret.encode("utf-8"), bytes_to_sign, hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode("ascii")

    # ------------------------------------------------------------------ #
    # Outbound
    # ------------------------------------------------------------------ #
    def _build_group_message_payload(
        self, text: str, reply_to: Optional[str]
    ) -> dict:
        payload: dict = {
            "content": text,
            "mentions": [{"nickname": n} for n in self.extract_mentions(text)],
        }
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        return payload

    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        group_code = self._group_code_from_chat(chat_id)
        if not group_code:
            return SendResult(
                success=False, error="No group_code in chat_id and no default"
            )
        try:
            payload = self._build_group_message_payload(text or "", reply_to)
            resp = await self._client.post(
                f"/groups/{group_code}/messages", json=payload
            )
            data = resp.json()
            return SendResult(
                success=resp.is_success,
                message_id=str(data.get("message_id")) if resp.is_success else None,
                error=None if resp.is_success else str(data),
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_dm(
        self,
        group_code: str,
        user_id: str,
        message: str,
        media_files: Optional[List[dict]] = None,
    ) -> SendResult:
        """Send a private / direct message to a user inside a group (私信).

        Mirrors the ``yb_send_dm`` tool described in the YuanBao skill.
        """
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        try:
            payload: dict = {"user_id": user_id, "content": message}
            if media_files:
                payload["media_files"] = media_files
            resp = await self._client.post(
                f"/groups/{group_code}/dm", json=payload
            )
            data = resp.json()
            return SendResult(
                success=resp.is_success,
                message_id=str(data.get("message_id")) if resp.is_success else None,
                error=None if resp.is_success else str(data),
            )
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        """YuanBao has no typing indicator; no-op to satisfy the interface."""
        return None
