import asyncio
import logging
import os
from typing import Optional

from gateway.base import BasePlatformAdapter, MessageEvent, SendResult

logger = logging.getLogger(__name__)

try:
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.web.async_client import AsyncWebClient
    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False
    logger.warning("slack-sdk not installed. Install with: pip install slack-sdk")


class SlackAdapter(BasePlatformAdapter):
    name = "slack"

    def __init__(self, bot_token: str = "", app_token: str = ""):
        super().__init__("slack")
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN", "")
        self.app_token = app_token or os.getenv("SLACK_APP_TOKEN", "")
        self._client: Optional[AsyncWebClient] = None
        self._socket_client: Optional[SocketModeClient] = None

    async def connect(self) -> bool:
        if not HAS_SLACK:
            logger.error("slack-sdk not available")
            return False
        if not self.bot_token:
            logger.error("SLACK_BOT_TOKEN not set")
            return False

        try:
            self._client = AsyncWebClient(token=self.bot_token)

            if self.app_token:
                self._socket_client = SocketModeClient(
                    app_token=self.app_token,
                    web_client=self._client,
                )

                @self._socket_client.on("events_api")
                async def handle_event(client: SocketModeClient, req: SocketModeRequest):
                    payload = req.payload
                    event = payload.get("event", {})
                    if event.get("type") == "message" and event.get("subtype") is None:
                        text = event.get("text", "")
                        user = event.get("user", "")
                        channel = event.get("channel", "")
                        ts = event.get("ts", "")

                        if user and channel and self._on_message:
                            ev = MessageEvent(
                                text=text,
                                sender_id=user,
                                chat_id=channel,
                                platform="slack",
                                message_id=ts,
                            )
                            await self._on_message(ev)

                asyncio.create_task(self._socket_client.connect())
            else:
                logger.info("Slack adapter initialized (app token missing — webhook mode only)")

            return True
        except Exception as e:
            logger.error(f"Slack connection failed: {e}")
            return False

    async def disconnect(self):
        if self._socket_client:
            await self._socket_client.close()
        self._client = None

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            kwargs = {"channel": chat_id, "text": text}
            if reply_to:
                kwargs["thread_ts"] = reply_to
            resp = await self._client.chat_postMessage(**kwargs)
            return SendResult(success=True, message_id=resp.get("ts"))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_image(self, chat_id: str, image_url: str, caption: Optional[str] = None) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")

        try:
            resp = await self._client.files_upload_v2(
                channel=chat_id,
                file=image_url,
                initial_comment=caption or "",
            )
            return SendResult(success=True, message_id=resp.get("file", {}).get("id"))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        if self._client:
            try:
                await self._client.reactions_add(channel=chat_id, name="thought_balloon", timestamp="")
            except Exception:
                logger.warning("gateway/platforms/slack.py:112 async send_typing: suppressed error", exc_info=True)
                pass
