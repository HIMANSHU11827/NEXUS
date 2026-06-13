import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Awaitable, Tuple

logger = logging.getLogger(__name__)

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

    def set_message_handler(self, handler: Callable[[MessageEvent], Awaitable[None]]):
        self._on_message = handler

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
        return await self.send_text(chat_id, f"{caption + '\n' if caption else ''}{image_url}")

    async def send_typing(self, chat_id: str):
        """Optional: Send typing indicator."""
        pass
