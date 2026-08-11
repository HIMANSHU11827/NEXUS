from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import tempfile
from typing import Optional

import httpx

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

try:
    from nio import AsyncClient, LoginResponse, MatrixRoom, RoomMessageText
    HAS_MATRIX_NIO = True
except ImportError:
    HAS_MATRIX_NIO = False
    logger.warning("matrix-nio not installed. Install with: pip install matrix-nio")

    # Fallback placeholders so the module imports cleanly (and type annotations
    # resolve) even when matrix-nio is absent. The connect() path short-circuits
    # on HAS_MATRIX_NIO before any of these are used at runtime.
    AsyncClient = MatrixRoom = LoginResponse = RoomMessageText = object


class MatrixAdapter(BasePlatformAdapter):
    """
    NEXUS Matrix Adapter.
    Uses matrix-nio to connect to any Matrix homeserver.
    Expects MATRIX_HOMESERVER, MATRIX_USER, MATRIX_PASSWORD or MATRIX_ACCESS_TOKEN.
    """
    name = "matrix"

    def __init__(self, homeserver: str = "", user: str = "", password: str = "", access_token: str = ""):
        super().__init__("matrix")
        self.homeserver = homeserver or os.getenv("MATRIX_HOMESERVER", "https://matrix.org")
        self.user = user or os.getenv("MATRIX_USER", "")
        self.password = password or os.getenv("MATRIX_PASSWORD", "")
        self.access_token = access_token or os.getenv("MATRIX_ACCESS_TOKEN", "")
        self._client: Optional[AsyncClient] = None
        self._sync_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        if not HAS_MATRIX_NIO:
            logger.error("matrix-nio not available")
            return False
        if not self.homeserver or not self.user:
            logger.error("MATRIX_HOMESERVER and MATRIX_USER must be set")
            return False

        try:
            self._client = AsyncClient(self.homeserver, self.user)

            if self.access_token:
                self._client.access_token = self.access_token
            elif self.password:
                resp = await self._client.login(password=self.password)
                if not isinstance(resp, LoginResponse):
                    logger.error(f"Matrix login failed: {resp}")
                    return False
            else:
                logger.error("Either MATRIX_PASSWORD or MATRIX_ACCESS_TOKEN required")
                return False

            self._sync_task = asyncio.create_task(self._sync_loop())
            return True
        except Exception as e:
            logger.error(f"Matrix connection failed: {e}")
            return False

    async def disconnect(self):
        sync_task = self._sync_task
        self._sync_task = None
        await self._cancel_task(sync_task)
        if self._client:
            await self._client.close()
            self._client = None

    async def _sync_loop(self):
        """Continuously sync with Matrix homeserver.

        Wrapped in the shared :meth:`BasePlatformAdapter._guard_poll` reconnect
        helper so a transient sync failure (network blip, homeserver hiccup)
        re-arms with exponential backoff instead of killling the platform. While
        failing repeatedly the adapter reports ``health=unavailable``; graceful
        shutdown cancels the loop cleanly.
        """
        await self._guard_poll(self._sync_once, backoff_base=1.0, backoff_cap=30.0)

    async def _sync_once(self):
        """A single Matrix sync round-trip and event dispatch. Raises on error."""
        resp = await self._client.sync(timeout=30000)
        for room_id in resp.rooms.join:
            room = resp.rooms.join[room_id]
            for event in room.timeline.events:
                if isinstance(event, RoomMessageText):
                    await self._on_room_message(room_id, event)

    async def _on_room_message(self, room_id: str, event: RoomMessageText):
        if not self._on_message:
            return
        if event.sender == self.user:
            return

        ev = MessageEvent(
            text=event.body,
            sender_id=event.sender,
            chat_id=room_id,
            platform="matrix",
            message_id=event.event_id,
        )
        await self._on_message(ev)

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            content = {"msgtype": "m.text", "body": text}
            if reply_to:
                content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}

            resp = await self._client.room_send(
                room_id=chat_id,
                message_type="m.room.message",
                content=content,
            )
            return SendResult(success=True, message_id=getattr(resp, "event_id", None))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(self, chat_id: str, image_url: str, caption: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            async with httpx.AsyncClient() as dl:
                img_resp = await dl.get(image_url)
                suffix = pathlib.Path(image_url).suffix or ".jpg"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(img_resp.content)
                tmp.close()

            with open(tmp.name, "rb") as f:
                resp = await self._client.upload(f, content_type="image/jpeg")
                os.unlink(tmp.name)
                if hasattr(resp, "content_uri"):
                    content = {
                        "msgtype": "m.image",
                        "body": caption or "Image",
                        "url": resp.content_uri,
                    }
                    send_resp = await self._client.room_send(chat_id, "m.room.message", content)
                    return SendResult(success=True, message_id=getattr(send_resp, "event_id", None))

            return SendResult(success=False, error="Upload failed")
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        if not self._client:
            return
        try:
            await self._client.room_typing(chat_id, True, timeout=5000)
        except Exception:
            logger.warning("gateway/platforms/matrix.py:157 async send_typing: suppressed error", exc_info=True)
            pass
