"""NEXUS BlueBubbles (iMessage) gateway adapter.

Uses the local BlueBubbles macOS server for outbound REST sends and inbound
webhooks. This is a lean, NEXUS-style adapter (httpx transport) covering text
messaging; media/typing are supported where the server endpoint allows.

Env-gated: ``connect()`` returns ``False`` unless ``BLUEBUBBLES_SERVER_URL`` and
``BLUEBUBBLES_PASSWORD`` are set. The adapter degrades gracefully when the
server is unreachable and is fully unit-testable via a monkeypatched client.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

DEFAULT_WEBHOOK_HOST = "127.0.0.1"
DEFAULT_WEBHOOK_PORT = 8645
DEFAULT_WEBHOOK_PATH = "/bluebubbles-webhook"
MAX_TEXT_LENGTH = 4000


class BlueBubblesAdapter(BasePlatformAdapter):
    """NEXUS BlueBubbles (iMessage) Adapter."""

    name = "bluebubbles"

    def __init__(
        self,
        server_url: str = "",
        password: str = "",
        webhook_host: str = "",
        webhook_port: str = "",
        webhook_path: str = "",
    ):
        super().__init__("bluebubbles")
        self.server_url = (
            server_url or os.getenv("BLUEBUBBLES_SERVER_URL", "")
        ).rstrip("/")
        self.password = password or os.getenv("BLUEBUBBLES_PASSWORD", "")
        self.webhook_host = webhook_host or os.getenv(
            "BLUEBUBBLES_WEBHOOK_HOST", DEFAULT_WEBHOOK_HOST
        )
        self.webhook_port = webhook_port or os.getenv(
            "BLUEBUBBLES_WEBHOOK_PORT", str(DEFAULT_WEBHOOK_PORT)
        )
        self.webhook_path = webhook_path or os.getenv(
            "BLUEBUBBLES_WEBHOOK_PATH", DEFAULT_WEBHOOK_PATH
        )
        self._client: Optional[httpx.AsyncClient] = None

    # -- env-gating --------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self.server_url and self.password)

    # -- connection lifecycle --------------------------------------------
    async def connect(self) -> bool:
        if not self.is_configured():
            logger.error(
                "[bluebubbles] BLUEBUBBLES_SERVER_URL and BLUEBUBBLES_PASSWORD are required"
            )
            return False
        try:
            self._client = httpx.AsyncClient(
                base_url=self.server_url,
                params={"password": self.password},
                timeout=30.0,
            )
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"BlueBubbles connection failed: {e}")
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
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]
        try:
            resp = await self._client.post(
                "/api/v1/message",
                json={"chatGuid": chat_id, "message": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return SendResult(success=True, message_id=str(data.get("guid", "")))
        except Exception as e:  # pragma: no cover - network dependent
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):  # pragma: no cover - optional
        if self._client is None:
            return None
        try:
            await self._client.post(
                "/api/v1/typing", json={"chatGuid": chat_id, "state": True}
            )
        except Exception:
            pass
        return None

    # -- inbound normalisation (webhook receiver calls this) --------------
    async def handle_inbound(self, payload: dict) -> Optional[MessageEvent]:
        """Normalise a BlueBubbles webhook payload into MessageEvent."""
        text = payload.get("text") or ""
        if not text:
            return None
        return MessageEvent(
            text=text,
            sender_id=str(payload.get("sender", "")),
            chat_id=str(payload.get("chatGuid", "")),
            platform="bluebubbles",
            message_id=str(payload.get("guid", "")),
            reply_to_id=str(payload.get("threadOriginatorGuid", "")) or None,
            raw_data=payload,
        )
