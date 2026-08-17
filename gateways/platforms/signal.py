import asyncio
import json
import logging
import os
import pathlib
import tempfile
from typing import Optional

import httpx

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)


class SignalAdapter(BasePlatformAdapter):
    """
    NEXUS Signal Adapter.
    Uses signal-cli's JSON-RPC or REST API via dbus or HTTP.
    Expects SIGNAL_NUMBER (registered phone number) and SIGNAL_RPC_URL.
    """
    name = "signal"

    def __init__(self, number: str = "", rpc_url: str = ""):
        super().__init__("signal")
        self.number = number or os.getenv("SIGNAL_NUMBER", "")
        self.rpc_url = rpc_url or os.getenv("SIGNAL_RPC_URL", "http://127.0.0.1:8080")
        self._client: Optional[httpx.AsyncClient] = None
        self._poll_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        if not self.number:
            logger.error("SIGNAL_NUMBER not set")
            return False

        try:
            self._client = httpx.AsyncClient(base_url=self.rpc_url, timeout=30.0)

            resp = await self._client.get("/v1/health")
            if resp.status_code != 200:
                logger.warning(f"Signal REST API not healthy (status={resp.status_code})")

            self._poll_task = asyncio.create_task(self._poll_receipts())
            return True
        except Exception as e:
            logger.error(f"Signal connection failed: {e}")
            return False

    async def disconnect(self):
        poll_task = self._poll_task
        self._poll_task = None
        await self._cancel_task(poll_task)
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _poll_receipts(self):
        """Poll for incoming messages from signal-cli REST API."""
        while True:
            try:
                resp = await self._client.get("/v1/receive/" + self.number)
                if resp.status_code == 200:
                    messages = resp.json()
                    for msg in messages:
                        await self._process_incoming(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Signal poll error: {e}")
            await asyncio.sleep(2)

    async def _process_incoming(self, raw: dict):
        envelope = raw.get("envelope", {})
        data_message = envelope.get("dataMessage", {})
        sync_message = envelope.get("syncMessage", {})

        if data_message:
            text = data_message.get("message", "")
            source = envelope.get("source", "")
            timestamp = str(data_message.get("timestamp", ""))

            if text and source and self._on_message:
                event = MessageEvent(
                    text=text,
                    sender_id=source,
                    chat_id=source,
                    platform="signal",
                    message_id=timestamp,
                )
                await self._on_message(event)
        elif sync_message:
            sent = sync_message.get("sent", {})
            text = sent.get("message", "")
            destination = sent.get("destination", "")
            timestamp = str(sent.get("timestamp", ""))

            if text and destination and self._on_message:
                event = MessageEvent(
                    text=text,
                    sender_id=destination,
                    chat_id=destination,
                    platform="signal",
                    message_id=timestamp,
                )
                await self._on_message(event)

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            payload = {
                "number": self.number,
                "recipients": [chat_id],
                "message": text,
            }
            if reply_to:
                payload["quote"] = {"timestamp": int(reply_to), "author": chat_id}

            resp = await self._client.post("/v2/send", json=payload)
            data = resp.json()
            ts = data.get("timestamp", "")
            return SendResult(success=resp.is_success, message_id=str(ts))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(self, chat_id: str, image_url: str, caption: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            payload = {
                "number": self.number,
                "recipients": [chat_id],
                "message": caption or "",
            }

            async with httpx.AsyncClient() as dl:
                img_resp = await dl.get(image_url)
                suffix = pathlib.Path(image_url).suffix or ".jpg"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(img_resp.content)
                tmp.close()
            try:
                # Keep the handle open only for the duration of the request;
                # on Windows an unlinked-but-open file makes the cleanup fail,
                # turning a successful send into a reported error + duplicate.
                with open(tmp.name, "rb") as fh:
                    files = {"file": (tmp.name, fh, "image/jpeg")}
                    resp = await self._client.post("/v2/send", data=json.dumps(payload), files=files)
                return SendResult(success=resp.is_success, message_id=str(resp.json().get("timestamp", "")))
            finally:
                os.unlink(tmp.name)
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        if not self._client:
            return
        try:
            payload = {
                "number": self.number,
                "recipient": chat_id,
            }
            await self._client.put("/v1/typing/" + chat_id, json=payload)
        except Exception:
            logger.warning("gateway/platforms/signal.py:161 async send_typing: suppressed error", exc_info=True)
            pass
