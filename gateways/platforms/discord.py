import asyncio
import logging
import os
from typing import Optional

from gateways.base import (
    HEALTH_HEALTHY,
    HEALTH_UNAVAILABLE,
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    STATE_RECOVERING,
    SendResult,
)

logger = logging.getLogger(__name__)

# Optional dependency: the adapter stays importable (and env-gated) even when
# discord.py is missing, so it cannot break test collection or the gateway graph.
try:  # pragma: no cover - exercised by import availability
    import discord
    HAS_DISCORD = True
except Exception:  # pragma: no cover - optional dependency absent
    discord = None  # type: ignore[assignment]
    HAS_DISCORD = False
    logger.warning(
        "discord.py not installed — Discord adapter disabled. "
        "Install with: pip install discord.py"
    )


class DiscordAdapter(BasePlatformAdapter):
    """NEXUS Discord Adapter (discord.py).

    Env-gated: ``connect()`` returns ``False`` unless a bot token is present in
    ``DISCORD_BOT_TOKEN`` (or the ``DISCORD_TOKEN`` alias) and the SDK is
    importable. Incoming messages are normalised into ``MessageEvent`` objects,
    which keeps the handler logic fully unit-testable without a live gateway.
    """

    HAS_DISCORD = HAS_DISCORD

    def __init__(self, token: str = ""):
        super().__init__("discord")
        self.token = (
            token
            or os.getenv("DISCORD_BOT_TOKEN", "")
            or os.getenv("DISCORD_TOKEN", "")
        )
        self.client = None
        self._run_task: Optional[asyncio.Task] = None
        self._disconnecting = False

    async def connect(self) -> bool:
        if discord is None:
            logger.error("Discord adapter unavailable: discord.py not installed")
            return False
        if not self.token:
            logger.error("Discord adapter unavailable: DISCORD_BOT_TOKEN not set")
            return False

        try:
            # The supervisor reconnects by calling connect() again. Cancel any
            # previous client task first, or the old gateway connection stays
            # alive and both sessions deliver the same events.
            old_run_task = self._run_task
            self._disconnecting = False
            if old_run_task is not None and not old_run_task.done():
                old_run_task.cancel()
                try:
                    await asyncio.wait_for(old_run_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                except Exception:
                    logger.debug("discord: stale client task exit failed", exc_info=True)
            intents = discord.Intents.default()
            intents.message_content = True
            self.client = discord.Client(intents=intents)

            @self.client.event
            async def on_message(message):
                # Ignore our own messages (and other bots if configured).
                me = getattr(self.client, "user", None)
                author = getattr(message, "author", None)
                if me is not None and author is not None and author == me:
                    return
                await self._handle_incoming(message)

            @self.client.event
            async def on_ready():
                logger.info(f"NEXUS Discord Adapter online as {self.client.user}")

            # Start the Discord client as a supervised background task so a
            # later transport failure reaches the gateway supervisor instead
            # of becoming an unobserved task exception.
            self._run_task = asyncio.create_task(self.client.start(self.token))
            self._run_task.add_done_callback(self._on_run_task_done)
            self.health = HEALTH_HEALTHY
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Discord connection failed: {e}")
            return False

    def _on_run_task_done(self, task: asyncio.Task) -> None:
        """Project Discord client task failure into adapter health state."""
        if self._run_task is task:
            self._run_task = None
        if self._disconnecting:
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # defensive: task inspection can fail
            error = exc
        if error is not None:
            self.last_error = str(error)
            logger.warning("Discord client stopped unexpectedly: %s", error)
        else:
            self.last_error = "Discord client stopped unexpectedly"
            logger.warning("Discord client stopped unexpectedly")
        self.health = HEALTH_UNAVAILABLE
        self.state = STATE_RECOVERING

    async def _handle_incoming(self, message):
        """Normalise a raw discord.py ``Message`` into a NEXUS ``MessageEvent``."""
        event = MessageEvent(
            text=getattr(message, "content", ""),
            sender_id=str(getattr(message.author, "id", "")),
            chat_id=str(getattr(message.channel, "id", "")),
            platform="discord",
            message_id=str(getattr(message, "id", "")),
            raw_data=message,
        )

        attachments = getattr(message, "attachments", None) or []
        if attachments:
            event.media_urls = [getattr(a, "url", "") for a in attachments]
            event.message_type = (
                MessageType.PHOTO
                if any(
                    (getattr(a, "content_type", "") or "").startswith("image/")
                    for a in attachments
                )
                else MessageType.DOCUMENT
            )

        if self._on_message:
            result = self._on_message(event)
            if asyncio.iscoroutine(result):
                await result

    async def disconnect(self):
        self._disconnecting = True
        if self.client is not None:
            try:
                await self.client.close()
            except Exception:  # pragma: no cover - network dependent
                pass
        if self._run_task is not None:
            self._run_task.cancel()
            await asyncio.gather(self._run_task, return_exceptions=True)
            self._run_task = None

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if self.client is None:
            return SendResult(success=False, error="Client not connected")
        try:
            channel = self.client.get_channel(int(chat_id))
            if channel is None:
                channel = await self.client.fetch_channel(int(chat_id))
            if channel is None:
                return SendResult(success=False, error=f"Channel {chat_id} not found")

            if reply_to:
                try:
                    original_msg = await channel.fetch_message(int(reply_to))
                    msg = await original_msg.reply(text)
                except Exception as reply_err:
                    logger.warning(f"Failed to reply to {reply_to}, sending normally: {reply_err}")
                    msg = await channel.send(text)
            else:
                msg = await channel.send(text)

            return SendResult(success=True, message_id=str(getattr(msg, "id", "")))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        if self.client is None:
            return
        try:
            channel = self.client.get_channel(int(chat_id))
            if channel is not None:
                await channel.typing()
        except Exception:  # pragma: no cover - network dependent
            logger.warning("gateway/platforms/discord.py:send_typing: suppressed error", exc_info=True)
            pass
