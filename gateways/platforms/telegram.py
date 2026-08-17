import asyncio
import logging
import os
from typing import Optional

from gateways.base import (
    BasePlatformAdapter,
    HEALTH_HEALTHY,
    HEALTH_UNAVAILABLE,
    MessageEvent,
    MessageType,
    SendResult,
)
from models.providers.core.reliability import bounded_tool_retry

logger = logging.getLogger(__name__)

# Polling re-arm backoff: 1s, 2s, 4s, ... capped at 60s between reconnects.
POLL_BACKOFF_BASE = 1.0
POLL_BACKOFF_CAP = 60.0

# Optional dependency: the adapter must be importable (and env-gated) even when
# pyTelegramBotAPI is not installed, so it never breaks test collection or the
# gateway import graph. This mirrors the HAS_SLACK guard used by the Slack adapter.
try:  # pragma: no cover - exercised by import availability
    from telebot.async_telebot import AsyncTeleBot
    from telebot.types import Message
    HAS_TELEBOT = True
except Exception:  # pragma: no cover - optional dependency absent
    AsyncTeleBot = None  # type: ignore[assignment]
    Message = None  # type: ignore[assignment]
    HAS_TELEBOT = False
    logger.warning(
        "pyTelegramBotAPI not installed — Telegram adapter disabled. "
        "Install with: pip install pytelegrambotapi"
    )


class TelegramAdapter(BasePlatformAdapter):
    """NEXUS Telegram Adapter (telebot / AsyncTeleBot).

    Env-gated: ``connect()`` returns ``False`` unless a bot token is present in
    ``TELEGRAM_BOT_TOKEN`` (or the ``TELEGRAM_TOKEN`` alias) and the SDK is
    importable. Incoming messages are normalised into ``MessageEvent`` objects
    without any dependency on a live network connection, which keeps the handler
    logic fully unit-testable.
    """

    HAS_TELEBOT = HAS_TELEBOT

    def __init__(self, token: str = ""):
        super().__init__("telegram")
        self.token = (
            token
            or os.getenv("TELEGRAM_BOT_TOKEN", "")
            or os.getenv("TELEGRAM_TOKEN", "")
        )
        self.bot = None
        self._poll_task: Optional[asyncio.Task] = None
        self._disconnecting = False
        self._poll_backoff_base = POLL_BACKOFF_BASE
        self._poll_backoff_cap = POLL_BACKOFF_CAP

    async def connect(self) -> bool:
        if AsyncTeleBot is None:
            logger.error("Telegram adapter unavailable: pyTelegramBotAPI not installed")
            return False
        if not self.token:
            logger.error("Telegram adapter unavailable: TELEGRAM_BOT_TOKEN not set")
            return False

        try:
            # The supervisor reconnects by calling connect() again. Cancel the
            # previous poll task first, or two infinity_polling loops run on
            # the same token: the old task also reads self.bot, so it would
            # silently double-poll the freshly reassigned bot.
            old_poll = self._poll_task
            self._disconnecting = False
            self._poll_task = None
            if old_poll is not None and not old_poll.done():
                old_poll.cancel()
                try:
                    await asyncio.wait_for(old_poll, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                except Exception:  # stale poll exit failure is not fatal
                    logger.debug("telegram: stale poll task exit failed", exc_info=True)
            self.bot = AsyncTeleBot(self.token)
            self._register_handlers()
            # Run the long-lived poll loop as a background task so connect() can
            # return immediately. _safe_poll swallows network errors and re-arms
            # infinity_polling with exponential backoff, so a failed reconnect
            # never crashes the gateway runner.
            self._poll_task = asyncio.ensure_future(self._safe_poll())
            self.health = HEALTH_HEALTHY
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Telegram connection failed: {e}")
            return False

    def _register_handlers(self):
        @self.bot.message_handler(func=lambda message: True)
        async def _wrap_message(message):
            await self._handle_incoming(message)

    async def _safe_poll(self):
        """Run ``infinity_polling`` forever, re-arming after failures.

        The poll loop restarts with exponential backoff (1s, 2s, 4s, ...
        capped at 60s) after any exception; the backoff resets on a clean run.
        Graceful shutdown is preserved: cancellation raises cleanly and a
        ``disconnect`` in progress makes the loop exit instead of re-arming.
        """
        attempts = 0
        while not self._disconnecting:
            try:
                await self.bot.infinity_polling()
                attempts = 0
                if self._disconnecting:
                    break
                # infinity_polling normally blocks forever; a clean return
                # (e.g. an external stop_polling) is re-armed after a short
                # pause instead of hot-looping.
                await asyncio.sleep(self._poll_backoff_base)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # network blips -> exponential backoff
                if self._disconnecting:
                    break
                attempts += 1
                delay = min(
                    self._poll_backoff_base * (2 ** (attempts - 1)),
                    self._poll_backoff_cap,
                )
                self.health = HEALTH_UNAVAILABLE
                self.last_error = str(exc)
                logger.warning(
                    "Telegram polling stopped (%s); re-arming in %.1fs", exc, delay
                )
                await asyncio.sleep(delay)

    async def _handle_incoming(self, message: "Message"):
        """Normalise a raw telebot ``Message`` into a NEXUS ``MessageEvent``."""
        from_user = getattr(message, "from_user", None)
        chat = getattr(message, "chat", None)
        event = MessageEvent(
            text=getattr(message, "text", None) or "",
            sender_id=str(getattr(from_user, "id", "")) if from_user else "",
            chat_id=str(getattr(chat, "id", "")) if chat else "",
            platform="telegram",
            message_id=str(getattr(message, "message_id", "")),
            reply_to_id=(
                str(getattr(message.reply_to_message, "message_id", ""))
                if getattr(message, "reply_to_message", None) else None
            ),
            raw_data=message,
        )

        content_type = getattr(message, "content_type", "text")
        if content_type == "photo":
            event.message_type = MessageType.PHOTO
        elif content_type == "voice":
            event.message_type = MessageType.VOICE

        if self._on_message:
            result = self._on_message(event)
            if asyncio.iscoroutine(result):
                await result

    async def disconnect(self):
        self._disconnecting = True
        if self.bot is not None:
            try:
                await self.bot.stop_polling()
            except Exception:  # pragma: no cover - network dependent
                pass
        poll = self._poll_task
        if poll is not None:
            poll.cancel()
            try:
                await poll
            except (asyncio.CancelledError, Exception):  # expected on shutdown
                pass
            self._poll_task = None

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if self.bot is None:
            return SendResult(success=False, error="Bot not connected")
        try:
            # Sending a message is non-idempotent: a timeout can occur after
            # Telegram accepted the request, so replaying it may duplicate a
            # user-visible answer. Keep the operation single-attempt and let
            # the caller decide whether/how to reconcile delivery.
            msg = await bounded_tool_retry(
                self.bot.send_message, chat_id, text,
                reply_to_message_id=reply_to, retry_policy=0,
            )
            return SendResult(success=True, message_id=str(getattr(msg, "message_id", "")))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        if self.bot is None:
            return
        try:
            await self.bot.send_chat_action(chat_id, "typing")
        except Exception:  # pragma: no cover - network dependent
            pass
