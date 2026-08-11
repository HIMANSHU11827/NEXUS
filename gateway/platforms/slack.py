import asyncio
import logging
import os
from typing import List, Optional

from gateway.base import (
    HEALTH_UNAVAILABLE,
    STATE_RECOVERING,
    BasePlatformAdapter,
    MessageEvent,
    SendResult,
)

logger = logging.getLogger(__name__)

try:
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.web.async_client import AsyncWebClient

    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False
    SocketModeClient = None  # type: ignore
    AsyncWebClient = None  # type: ignore
    logger.warning("slack-sdk not installed. Install with: pip install slack-sdk")

# Env vars that, when present, mean the Slack gateway is configured.
SLACK_REQUIRED_ENV = ("SLACK_BOT_TOKEN", "SLACK_TOKEN")


class SlackAdapter(BasePlatformAdapter):
    """NEXUS Slack Adapter.

    Uses ``slack_sdk`` for chat posting and (optionally) Socket Mode for
    inbound events. The adapter is **env-gated**: it only reports as configured
    when ``slack_sdk`` is installed *and* a bot token is available, and
    ``connect`` returns ``False`` otherwise so the gateway registers it lazily.
    """

    name = "slack"
    required_env = SLACK_REQUIRED_ENV

    def __init__(self, bot_token: str = "", app_token: str = ""):
        super().__init__("slack")
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN", "") or os.getenv("SLACK_TOKEN", "")
        self.app_token = app_token or os.getenv("SLACK_APP_TOKEN", "")
        self._client: Optional["AsyncWebClient"] = None
        self._socket_client: Optional["SocketModeClient"] = None
        self._socket_task: Optional[asyncio.Task] = None
        self._disconnecting = False

    def is_configured(self) -> bool:
        """True only when slack_sdk is importable and a bot token is present."""
        return HAS_SLACK and bool(self.bot_token)

    async def connect(self) -> bool:
        if not HAS_SLACK:
            logger.error("slack-sdk not available")
            return False
        if not self.bot_token:
            logger.error("SLACK_BOT_TOKEN not set")
            return False

        try:
            self._disconnecting = False
            self._client = AsyncWebClient(token=self.bot_token)

            if self.app_token:
                self._socket_client = SocketModeClient(
                    app_token=self.app_token,
                    web_client=self._client,
                )

                @self._socket_client.on("events_api")
                async def handle_event(client: "SocketModeClient", req: "SocketModeRequest"):
                    event = self._parse_message_event(req.payload)
                    if event is not None and self._on_message:
                        await self._on_message(event)

                # Own the long-lived socket task so failures are projected to
                # supervisor-readable health state and shutdown can await it.
                self._socket_task = asyncio.create_task(self._socket_client.connect())
                self._socket_task.add_done_callback(self._on_socket_task_done)
            else:
                logger.info("Slack adapter initialized (app token missing — webhook mode only)")

            return True
        except Exception as e:
            logger.error(f"Slack connection failed: {e}")
            return False

    def _on_socket_task_done(self, task: asyncio.Task) -> None:
        """Project Socket Mode task failure/exit into adapter health."""
        if self._socket_task is task:
            self._socket_task = None
        if self._disconnecting:
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            error = exc
        if error is not None:
            self.last_error = str(error)
            logger.warning("Slack Socket Mode stopped unexpectedly: %s", error)
        else:
            self.last_error = "Slack Socket Mode stopped unexpectedly"
            logger.warning("Slack Socket Mode stopped unexpectedly")
        self.health = HEALTH_UNAVAILABLE
        self.state = STATE_RECOVERING

    async def disconnect(self):
        self._disconnecting = True
        try:
            if self._socket_client:
                await self._socket_client.close()
        finally:
            if self._socket_task is not None:
                self._socket_task.cancel()
                await asyncio.gather(self._socket_task, return_exceptions=True)
                self._socket_task = None
            self._socket_client = None
            self._client = None

    @staticmethod
    def _parse_message_event(payload: dict) -> Optional[MessageEvent]:
        """Parse a Slack ``events_api`` payload into a MessageEvent.

        Returns ``None`` for non-message events (e.g. bot messages, reactions,
        channel joins). Pure / synchronous for unit testing.
        """
        if not isinstance(payload, dict):
            return None
        event = payload.get("event", {})
        if event.get("type") != "message" or event.get("subtype") is not None:
            return None
        text = event.get("text", "")
        user = event.get("user", "")
        channel = event.get("channel", "")
        ts = event.get("ts", "")
        if not (user and channel):
            return None
        return MessageEvent(
            text=text,
            sender_id=user,
            chat_id=channel,
            platform="slack",
            message_type="text",
            message_id=ts,
        )

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
                logger.warning("gateway/platforms/slack.py async send_typing: suppressed error", exc_info=True)
                pass
