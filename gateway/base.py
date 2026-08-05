import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Platform lifecycle states + health
# --------------------------------------------------------------------------- #
# Lifecycle: created -> connecting -> running -> paused -> recovering -> stopped
STATE_CREATED = "created"
STATE_CONNECTING = "connecting"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_RECOVERING = "recovering"
STATE_STOPPED = "stopped"
STATE_DISABLED = "disabled"

# Health: healthy / degraded / unavailable / disabled
HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_UNAVAILABLE = "unavailable"
HEALTH_DISABLED = "disabled"


class MessageType(Enum):
    """Types of incoming messages."""
    TEXT = "text"
    LOCATION = "location"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    COMMAND = "command"

@dataclass
class MessageEvent:
    """Normalized representation of an incoming message from any platform."""
    text: str
    sender_id: str
    chat_id: str
    platform: str
    message_type: MessageType = MessageType.TEXT
    message_id: Optional[str] = None
    media_urls: List[str] = field(default_factory=list)
    reply_to_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    raw_data: Any = None

@dataclass
class SendResult:
    """Result of sending a message."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None

class BasePlatformAdapter(ABC):
    """
    Base class for all NEXUS platform adapters.
    Ensures a unified interface for Telegram, Discord, WhatsApp, etc.
    """
    
    def __init__(self, platform_name: str):
        self.platform = platform_name
        self._on_message: Optional[Callable[[MessageEvent], Awaitable[None]]] = None
        self._running = False
        # Supervised lifecycle state — mirrored here by the GatewaySupervisor so
        # any caller can read ``adapter.state`` / ``adapter.health`` directly.
        # ``created*`` is the resting state; the supervisor drives the rest.
        self.state = STATE_CREATED
        self.health = HEALTH_UNAVAILABLE
        self.last_error: Optional[str] = None
        self.restarts = 0
        self.paused_reason: Optional[str] = None
        self.disabled_until = 0.0

    def set_message_handler(self, handler: Callable[[MessageEvent], Awaitable[None]]):
        self._on_message = handler

    async def _guard_poll(
        self,
        poll: Callable[[], Awaitable[None]],
        backoff_base: float = 1.0,
        backoff_cap: float = 60.0,
    ) -> None:
        """Run a long-lived poll coroutine, re-arming with exponential backoff.

        Shared reconnect helper for adapters that block on a polling loop
        (``infinity_polling``, a homeserver sync, a socket listener). Any
        exception is swallowed and the loop re-armed after ``1s, 2s, 4s, ...``
        capped at ``backoff_cap`` instead of killing the platform permanently;
        a clean run resets the backoff. While failing, the adapter reports
        ``health=unavailable`` so the supervisor can schedule a reconnect. A
        ``CancelledError`` (shutdown) propagates cleanly.
        """
        attempts = 0
        while not getattr(self, "_disconnecting", False):
            try:
                await poll()
                attempts = 0
                self.health = HEALTH_HEALTHY
                if getattr(self, "_disconnecting", False):
                    break
                # A poll that returns cleanly (external stop) is re-armed after
                # a short pause instead of hot-looping.
                await asyncio.sleep(backoff_base)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # network blips -> exponential backoff
                if getattr(self, "_disconnecting", False):
                    break
                attempts += 1
                delay = min(backoff_base * (2 ** (attempts - 1)), backoff_cap)
                self.health = HEALTH_UNAVAILABLE
                self.last_error = str(exc)
                logger.warning(
                    "%s poll stopped (%s); re-arming in %.1fs", self.platform, exc, delay
                )
                await asyncio.sleep(delay)

    @abstractmethod
    async def connect(self) -> bool:
        """Initialize connection to the platform."""
        pass

    @abstractmethod
    async def disconnect(self):
        """Shutdown connection."""
        pass

    @abstractmethod
    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        """Send a text message."""
        pass

    async def send_image(self, chat_id: str, image_url: str, caption: Optional[str] = None) -> SendResult:
        """Send an image. Default implementation sends as text URL.""" 
        prefix = f"{caption}\n" if caption else ""
        return await self.send_text(chat_id, f"{prefix}{image_url}")

    async def send_typing(self, chat_id: str):
        """Optional: Send typing indicator."""
        pass
