import discord
import asyncio
import logging
from typing import Optional, Dict, Any
from integrations.gateway.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger(__name__)

class DiscordAdapter(BasePlatformAdapter):
    """
    NEXUS Discord Adapter.
    Uses discord.py to interface with the Discord Bot API.
    """
    
    def __init__(self, token: str):
        super().__init__("discord")
        self.token = token
        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)

    async def connect(self) -> bool:
        if not self.token:
            return False
            
        @self.client.event
        async def on_message(message):
            if message.author == self.client.user:
                return
                
            event = MessageEvent(
                text=message.content,
                sender_id=str(message.author.id),
                chat_id=str(message.channel.id),
                platform="discord",
                message_id=str(message.id),
                raw_data=message
            )
            
            # Check for attachments
            if message.attachments:
                event.message_type = MessageType.PHOTO if any(a.content_type.startswith('image/') for a in message.attachments) else MessageType.DOCUMENT
                event.media_urls = [a.url for a in message.attachments]
                
            if self._on_message:
                await self._on_message(event)

        @self.client.event
        async def on_ready():
            logger.info(f"NEXUS Discord Adapter online as {self.client.user}")

        # Start Discord client in a background task
        asyncio.create_task(self.client.start(self.token))
        return True

    async def disconnect(self):
        await self.client.close()

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        try:
            channel = self.client.get_channel(int(chat_id))
            if not channel:
                channel = await self.client.fetch_channel(int(chat_id))
            
            if reply_to:
                try:
                    # Fetch the message to reply to
                    original_msg = await channel.fetch_message(int(reply_to))
                    msg = await original_msg.reply(text)
                except Exception as reply_err:
                    logger.warning(f"Failed to reply to {reply_to}, sending normally: {reply_err}")
                    msg = await channel.send(text)
            else:
                msg = await channel.send(text)

            return SendResult(success=True, message_id=str(msg.id))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        try:
            channel = self.client.get_channel(int(chat_id))
            if channel:
                await channel.typing()
        except Exception:
            pass
