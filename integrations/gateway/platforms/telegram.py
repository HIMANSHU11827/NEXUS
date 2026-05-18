import os
import asyncio
import logging
from typing import Optional
from telebot.async_telebot import AsyncTeleBot
from telebot.types import Message
from integrations.gateway.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger(__name__)

class TelegramAdapter(BasePlatformAdapter):
    """
    NEXUS Telegram Adapter.
    Uses telebot (AsyncTeleBot) to interface with the Telegram Bot API.
    """
    
    def __init__(self, token: str):
        super().__init__("telegram")
        self.token = token
        self.bot: Optional[AsyncTeleBot] = None

    async def connect(self) -> bool:
        if not self.token:
            return False
        
        try:
            self.bot = AsyncTeleBot(self.token)
            
            @self.bot.message_handler(func=lambda message: True)
            async def wrap_message(message: Message):
                event = MessageEvent(
                    text=message.text or "",
                    sender_id=str(message.from_user.id),
                    chat_id=str(message.chat.id),
                    platform="telegram",
                    message_id=str(message.message_id),
                    reply_to_id=str(message.reply_to_message.message_id) if message.reply_to_message else None,
                    raw_data=message
                )
                
                # Determine message type
                if message.content_type == 'photo':
                    event.message_type = MessageType.PHOTO
                elif message.content_type == 'voice':
                    event.message_type = MessageType.VOICE
                
                if self._on_message:
                    await self._on_message(event)

            # Start polling in a background task
            asyncio.create_task(self.bot.infinity_polling())
            return True
        except Exception as e:
            logger.error(f"Telegram connection failed: {e}")
            return False

    async def disconnect(self):
        if self.bot:
            await self.bot.stop_polling()

    async def send_text(self, chat_id: str, text: str, reply_to: Optional[str] = None) -> SendResult:
        if not self.bot:
            return SendResult(success=False, error="Bot not connected")
        
        try:
            msg = await self.bot.send_message(chat_id, text, reply_to_message_id=reply_to)
            return SendResult(success=True, message_id=str(msg.message_id))
        except Exception as e:
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str):
        if self.bot:
            await self.bot.send_chat_action(chat_id, "typing")
