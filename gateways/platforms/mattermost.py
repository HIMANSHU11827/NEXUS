import asyncio
import json
import logging
import os
from typing import Optional

import httpx

from gateways.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("websockets not installed. Install with: pip install websockets")


class MattermostAdapter(BasePlatformAdapter):
    """
    NEXUS Mattermost Adapter.
    Uses Mattermost REST API + WebSocket for real-time events.
    Expects MATTERMOST_URL, MATTERMOST_TOKEN, MATTERMOST_TEAM.
    """
    name = "mattermost"

    def __init__(self, url: str = "", token: str = "", team: str = ""):
        super().__init__("mattermost")
        self.url = url.rstrip("/") or os.getenv("MATTERMOST_URL", "").rstrip("/")
        self.token = token or os.getenv("MATTERMOST_TOKEN", "")
        self.team = team or os.getenv("MATTERMOST_TEAM", "")
        self._client: Optional[httpx.AsyncClient] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._user_id: Optional[str] = None

    async def connect(self) -> bool:
        if not self.url or not self.token:
            logger.error("MATTERMOST_URL and MATTERMOST_TOKEN must be set")
            return False

        try:
            self._client = httpx.AsyncClient(
                base_url=self.url + "/api/v4",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30.0,
            )

            resp = await self._client.get("/users/me")
            if resp.status_code != 200:
                logger.error(f"Mattermost auth failed: {resp.status_code}")
                return False

            self._user_id = resp.json().get("id", "")

            if HAS_WEBSOCKETS:
                self._ws_task = asyncio.create_task(self._ws_listen())

            return True
        except Exception as e:
            logger.error(f"Mattermost connection failed: {e}")
            return False

    async def disconnect(self):
        ws_task = self._ws_task
        self._ws_task = None
        await self._cancel_task(ws_task)
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ws_listen(self):
        """Listen for incoming messages via Mattermost WebSocket."""
        ws_url = self.url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url += "/api/v4/websocket"

        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    auth = json.dumps({
                        "seq": 1,
                        "action": "authentication_challenge",
                        "data": {"token": self.token},
                    })
                    await ws.send(auth)

                    async for raw in ws:
                        data = json.loads(raw)
                        event = data.get("event", "")
                        if event == "posted":
                            await self._handle_post(data.get("data", {}).get("post", "{}"))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Mattermost WS error: {e}")
                await asyncio.sleep(5)

    async def _handle_post(self, post_json: str):
        if not self._on_message:
            return
        try:
            post = json.loads(post_json) if isinstance(post_json, str) else post_json
            if post.get("user_id") == self._user_id:
                return

            text = post.get("message", "")
            channel_id = post.get("channel_id", "")
            post_id = post.get("id", "")
            user_id = post.get("user_id", "")

            if text:
                event = MessageEvent(
                    text=text,
                    sender_id=user_id,
                    chat_id=channel_id,
                    platform="mattermost",
                    message_id=post_id,
                )
                await self._on_message(event)
        except Exception as e:
            logger.debug(f"Mattermost post parse error: {e}")

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            payload = {
                "channel_id": chat_id,
                "message": text,
            }
            if reply_to:
                payload["root_id"] = reply_to

            resp = await self._client.post("/posts", json=payload)
            data = resp.json()
            return SendResult(success=resp.is_success, message_id=data.get("id"))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(self, chat_id: str, image_url: str, caption: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            async with httpx.AsyncClient() as dl:
                img_resp = await dl.get(image_url)

            files = {"files": ("image.jpg", img_resp.content, "image/jpeg")}
            upload = await self._client.post(
                "/files",
                params={"channel_id": chat_id},
                files=files,
            )
            upload_data = upload.json()
            file_ids = upload_data.get("file_infos", [])
            if not file_ids:
                return SendResult(success=False, error="Upload failed")

            payload = {
                "channel_id": chat_id,
                "message": caption or "",
                "file_ids": [f["id"] for f in file_ids],
            }
            resp = await self._client.post("/posts", json=payload)
            return SendResult(success=resp.is_success, message_id=resp.json().get("id"))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        if not self._client:
            return
        try:
            await self._client.post("/channels/" + chat_id + "/typing")
        except Exception:
            logger.warning("gateway/platforms/mattermost.py:176 async send_typing: suppressed error", exc_info=True)
            pass
