"""NEXUS Meta Adapter - WhatsApp / Facebook / Instagram via Graph API."""

import asyncio
import logging
import os
import httpx
from typing import Optional
from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

META_GRAPH_URL = "https://graph.facebook.com/v22.0"


class MetaAdapter(BasePlatformAdapter):
    """
    NEXUS Meta Adapter (Facebook / Instagram / WhatsApp via Graph API).
    Uses the Meta Graph API for sending messages and processing webhooks.
    """

    def __init__(self, platform: str, access_token: str, verify_token: str = ""):
        super().__init__(platform)
        self.access_token = access_token
        self.verify_token = verify_token
        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> bool:
        self._client = httpx.AsyncClient(timeout=30.0)
        logger.info(f"[{self.platform.upper()}]: Meta adapter ready (Graph API).")
        return True

    async def disconnect(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _phone_number_id(self, chat_id: str) -> str:
        """WhatsApp send requires phone-number-id; for FB/IG we use page-id or ig-user-id."""
        return os.getenv("META_PHONE_NUMBER_ID", "").strip()

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
                return SendResult(success=resp.is_success, message_id=mid)

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
                return SendResult(success=resp.is_success)

            else:
                logger.warning(f"[{self.platform.upper()}]: Unknown Meta platform.")
                return SendResult(success=False, error=f"Unknown Meta platform: {self.platform}")

        except Exception as e:
            logger.error(f"[{self.platform.upper()}]: send_text error: {e}")
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        """Send typing indicator via Graph API (WhatsApp only)."""
        if self.platform != "whatsapp" or not self._client:
            return
        try:
            phone_id = self._phone_number_id(chat_id)
            url = f"{META_GRAPH_URL}/{phone_id}/messages"
            await self._client.post(
                url,
                params={"access_token": self.access_token},
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": chat_id,
                    "type": "text",
                    "text": {"body": ". . ."},
                },
            )
        except Exception:
            pass

    async def handle_webhook_payload(self, payload: dict):
        """Called by an external webhook server when Meta sends an event."""
        try:
            if self.platform == "whatsapp":
                entries = payload.get("entry", [])
                for entry in entries:
                    changes = entry.get("changes", [])
                    for change in changes:
                        value = change.get("value", {})
                        messages = value.get("messages", [])
                        for msg in messages:
                            from_num = msg.get("from", "")
                            text_body = ""
                            if msg.get("type") == "text":
                                text_body = msg.get("text", {}).get("body", "")
                            elif msg.get("type") == "interactive":
                                text_body = msg.get("interactive", {}).get("button_reply", {}).get("title", "")

                            if text_body and self._on_message:
                                event = MessageEvent(
                                    text=text_body,
                                    sender_id=from_num,
                                    chat_id=from_num,
                                    platform=self.platform,
                                    message_type="text",
                                )
                                await self._on_message(event)
        except Exception as e:
            logger.error(f"[{self.platform.upper()}]: webhook parse error: {e}")
