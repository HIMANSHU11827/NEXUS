"""Google Chat platform adapter (NEXUS).

Outbound messages use either an **incoming webhook URL**
(``GOOGLE_CHAT_WEBHOOK_URL``) or the Chat REST API
(``https://chat.googleapis.com/v1/spaces/{space}/messages`` keyed by
``GOOGLE_CHAT_SPACE`` + ``GOOGLE_CHAT_KEY``). The adapter is env-gated and
degrades gracefully when neither credential is present, matching the pattern
used by the other NEXUS gateway adapters.

The heavy ``google-api-python-client`` / Pub/Sub stack used by the reference
implementation is intentionally not required here — a webhook/REST adapter
covers the common self-hosted and space-webhook deployments without pulling
~33MB of SDK into every gateway invocation.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

GOOGLE_CHAT_API_BASE = "https://chat.googleapis.com/v1"


class GoogleChatAdapter(BasePlatformAdapter):
    """NEXUS Google Chat Adapter (webhook or REST)."""

    name = "google_chat"

    def __init__(
        self,
        webhook_url: str = "",
        space: str = "",
        key: str = "",
        token: str = "",
    ):
        super().__init__("google_chat")
        self.webhook_url = webhook_url or os.getenv("GOOGLE_CHAT_WEBHOOK_URL", "")
        self.space = space or os.getenv("GOOGLE_CHAT_SPACE", "")
        self.key = key or os.getenv("GOOGLE_CHAT_KEY", "")
        self.token = token or os.getenv("GOOGLE_CHAT_TOKEN", "")

        if self.webhook_url:
            self.mode = "webhook"
        elif self.space and (self.key or self.token):
            self.mode = "rest"
        else:
            self.mode = None

        self._client: Optional[httpx.AsyncClient] = None

    # -- env-gating --------------------------------------------------------
    def is_configured(self) -> bool:
        return self.mode is not None

    # -- connection lifecycle --------------------------------------------
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "Google Chat adapter unavailable: set GOOGLE_CHAT_WEBHOOK_URL or "
                "(GOOGLE_CHAT_SPACE + GOOGLE_CHAT_KEY)"
            )
            return False
        try:
            self._client = httpx.AsyncClient(timeout=30.0)
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Google Chat connection failed: {e}")
            return False

    async def disconnect(self):
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover - network dependent
                pass
            self._client = None

    # -- outbound ----------------------------------------------------------
    async def send_text(
        self, chat_id: str, text: str, reply_to: Optional[str] = None
    ) -> SendResult:
        if self._client is None:
            return SendResult(success=False, error="Not connected")
        try:
            if self.mode == "webhook":
                resp = await self._client.post(self.webhook_url, json={"text": text})
            else:
                url = f"{GOOGLE_CHAT_API_BASE}/spaces/{chat_id or self.space}/messages"
                params = {}
                if self.key:
                    params["key"] = self.key
                if self.token:
                    params["token"] = self.token
                resp = await self._client.post(url, params=params, json={"text": text})
            resp.raise_for_status()
            data = resp.json()
            return SendResult(success=True, message_id=data.get("name"))
        except Exception as e:  # pragma: no cover - network dependent
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):  # pragma: no cover - not supported
        return None

    # -- inbound normalisation (webhook receiver calls this) --------------
    async def handle_inbound(self, payload: dict) -> Optional[MessageEvent]:
        """Normalise a Google Chat inbound webhook payload into MessageEvent."""
        text = payload.get("text") or payload.get("message", {}).get("text", "")
        sender = payload.get("message", {}).get("sender", {})
        space = payload.get("space", {})
        if not text:
            return None
        return MessageEvent(
            text=text,
            sender_id=str(sender.get("name", "")),
            chat_id=space.get("name", "") or payload.get("space", {}).get("displayName", ""),
            platform="google_chat",
            message_id=str(payload.get("message", {}).get("name", "")),
            raw_data=payload,
        )
