"""Discord platform adapter — sends/receives messages via Discord bot."""

import logging
import os
from typing import Any, Dict, List, Optional

from gateway.base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class DiscordAdapter(BasePlatformAdapter):
    name: str = "discord"
    version: str = "1.0"
    requires_env: List[str] = ["DISCORD_TOKEN"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._token = os.environ.get("DISCORD_TOKEN", "")
        self._bot = None

    def connect(self) -> bool:
        if not self._token:
            logger.error("DISCORD_TOKEN not set")
            return False
        try:
            import discord
            self._bot = discord.Client(intents=discord.Intents.default())
            self._connected = True
            logger.info("Discord adapter connected")
            return True
        except ImportError:
            logger.error("discord.py not installed")
            return False
        except Exception as e:
            logger.error(f"Discord connect failed: {e}")
            return False

    def disconnect(self) -> bool:
        self._connected = False
        self._bot = None
        return True

    def send_message(self, target: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "not connected", "platform": "discord"}
        try:
            import discord
            channel_id = int(target)
            if self._bot and self._bot.is_ready():
                async def _send():
                    channel = self._bot.get_channel(channel_id)
                    if channel:
                        await channel.send(content)
                import asyncio
                asyncio.create_task(_send())
                return {"sent": True, "channel": target, "platform": "discord"}
        except Exception as e:
            return {"error": str(e), "platform": "discord"}
        return {"error": "failed to send", "platform": "discord"}

    def listen(self, timeout: float = 1.0) -> List[Dict[str, Any]]:
        return []
