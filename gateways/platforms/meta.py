"""NEXUS Meta Adapter - WhatsApp / Facebook / Instagram via Graph API."""

import logging
import os
from typing import List, Optional

import httpx

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

META_GRAPH_URL = "https://graph.facebook.com/v22.0"

# Env vars that, when present, mean the Meta/WhatsApp gateway is configured.
META_REQUIRED_ENV = ("META_ACCESS_TOKEN", "META_PAGE_TOKEN", "WHATSAPP_TOKEN")


class MetaAdapter(BasePlatformAdapter):
    """
    NEXUS Meta Adapter (Facebook / Instagram / WhatsApp via Graph API).
    Uses the Meta Graph API for sending messages and processing webhooks.

    The adapter is **env-gated**: it only reports itself as configured when a
    credential is available, and ``connect`` returns ``False`` when none is set,
    so the gateway can register it lazily without crashing at import time.
    """

    #: Env var names this adapter can source credentials from.
    required_env: tuple = META_REQUIRED_ENV

    def __init__(self, platform: str = "facebook", access_token: str = "", verify_token: str = ""):
        super().__init__(platform)
        self.access_token = (
            access_token
            or os.getenv("META_ACCESS_TOKEN", "")
            or os.getenv("META_PAGE_TOKEN", "")
            or (os.getenv("WHATSAPP_TOKEN", "") if platform == "whatsapp" else "")
        )
        self.verify_token = (
            verify_token
            or os.getenv("META_VERIFY_TOKEN", "")
            or (os.getenv("WHATSAPP_VERIFY_TOKEN", "") if platform == "whatsapp" else "")
        )
        self._client: Optional[httpx.AsyncClient] = None

    def is_configured(self) -> bool:
        """True when a usable credential is present in env or constructor."""
        return bool(self.access_token)

    def _phone_number_id(self, chat_id: str) -> str:
        """WhatsApp send requires phone-number-id; for FB/IG we use page-id or ig-user-id."""
        return (os.getenv("META_PHONE_NUMBER_ID", "") or os.getenv("WHATSAPP_PHONE_ID", "")).strip()

    async def connect(self) -> bool:
        if not self.access_token:
            logger.error("Meta credentials not set (need META_ACCESS_TOKEN / META_PAGE_TOKEN / WHATSAPP_TOKEN)")
            return False
        self._client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"[{self.platform.upper()}]: Meta adapter ready (Graph API).")
        return True

    async def disconnect(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            if self.platform == "whatsapp":
                phone_id = self._phone_number_id(chat_id)
                if phone_id:
                    url = f"{META_GRAPH_URL}/{phone_id}/messages"
                    payload = {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": chat_id,
                        "type": "text",
                        "text": {"preview_url": False, "body": text},
                    }
                else:
                    url = f"{META_GRAPH_URL}/me/messages"
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": chat_id,
                        "type": "text",
                        "text": {"body": text},
                    }
                resp = await self._client.post(
                    url,
                    params={"access_token": self.access_token},
                    json=payload,
                )
                data = resp.json()
                mid = data.get("messages", [{}])[0].get("id", "")
                return SendResult(success=resp.is_success, message_id=mid, error=None if resp.is_success else str(data))

            elif self.platform in ("facebook", "instagram"):
                url = f"{META_GRAPH_URL}/me/messages"
                payload = {
                    "recipient": {"id": chat_id},
                    "message": {"text": text},
                }
                if reply_to:
                    payload["message"]["text"] = f"@{reply_to}: {text}"
                resp = await self._client.post(
                    url,
                    params={"access_token": self.access_token},
                    json=payload,
                )
                data = resp.json()
                return SendResult(success=resp.is_success, error=None if resp.is_success else str(data))

            else:
                logger.warning(f"[{self.platform.upper()}]: Unknown Meta platform.")
                return SendResult(success=False, error=f"Unknown Meta platform: {self.platform}")

        except Exception as e:
            logger.error(f"[{self.platform.upper()}]: send_text error: {e}")
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        """Typing indicator via Graph API (WhatsApp only).

        The WhatsApp Cloud API exposes no typing action, so a text send was
        previously used to fake one — delivering a real ". . ." message to the
        user on every reply. Keep the hook as a no-op so callers keep working.
        """
        if self.platform != "whatsapp" or not self._client:
            return

    @staticmethod
    def parse_whatsapp_webhook(payload: dict) -> List[MessageEvent]:
        """Parse a Meta WhatsApp webhook payload into normalized MessageEvents.

        Returns an empty list when the payload is not a WhatsApp message event.
        Pure / synchronous so it can be unit-tested without network or credentials.
        """
        events: List[MessageEvent] = []
        if not isinstance(payload, dict):
            return events
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    from_num = msg.get("from", "")
                    text_body = ""
                    message_type = "text"
                    if msg.get("type") == "text":
                        text_body = msg.get("text", {}).get("body", "")
                    elif msg.get("type") == "interactive":
                        text_body = msg.get("interactive", {}).get("button_reply", {}).get("title", "")
                    elif msg.get("type") in ("image", "audio", "video", "document"):
                        message_type = msg.get("type")

                    if text_body and from_num:
                        events.append(
                            MessageEvent(
                                text=text_body,
                                sender_id=from_num,
                                chat_id=from_num,
                                platform="whatsapp",
                                message_type=message_type,
                                message_id=msg.get("id"),
                            )
                        )
        return events

    async def handle_webhook_payload(self, payload: dict):
        """Called by an external webhook server when Meta sends an event."""
        try:
            if self.platform == "whatsapp":
                for event in self.parse_whatsapp_webhook(payload):
                    if self._on_message:
                        await self._on_message(event)
        except Exception as e:
            logger.error(f"[{self.platform.upper()}]: webhook parse error: {e}")
