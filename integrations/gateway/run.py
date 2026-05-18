import asyncio
import os
import logging
from typing import Dict, List, Optional
from integrations.gateway.base import BasePlatformAdapter, MessageEvent
from orchestrators.architect import NexusArchitect

logger = logging.getLogger(__name__)

class GatewayRunner:
    """
    NEXUS UNIFIED GATEWAY COMMANDER
    Orchestrates multiple platform adapters and routes them to the Architect.
    """
    
    def __init__(self):
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self.architect = NexusArchitect()
        self.allowed_users: Dict[str, List[str]] = self._load_permissions()
        self._running = False

    def _load_permissions(self) -> Dict[str, List[str]]:
        """Load allowed user IDs from environment."""
        perms = {}
        # Telegram
        tg_ids = os.getenv("ALLOWED_TELEGRAM_IDS", "").split(",")
        perms["telegram"] = [i.strip() for i in tg_ids if i.strip()]
        # Discord
        ds_ids = os.getenv("ALLOWED_DISCORD_IDS", "").split(",")
        perms["discord"] = [i.strip() for i in ds_ids if i.strip()]
        # WhatsApp
        wa_ids = os.getenv("ALLOWED_WHATSAPP_IDS", "").split(",")
        perms["whatsapp"] = [i.strip() for i in wa_ids if i.strip()]
        # Meta (FB/IG)
        fb_ids = os.getenv("ALLOWED_FACEBOOK_IDS", "").split(",")
        perms["facebook"] = [i.strip() for i in fb_ids if i.strip()]
        ig_ids = os.getenv("ALLOWED_INSTAGRAM_IDS", "").split(",")
        perms["instagram"] = [i.strip() for i in ig_ids if i.strip()]
        return perms

    def add_adapter(self, adapter: BasePlatformAdapter):
        self.adapters[adapter.platform] = adapter
        adapter.set_message_handler(self.handle_message)

    def is_authorized(self, event: MessageEvent) -> bool:
        """Check if the user is allowed to issue commands."""
        allowed = self.allowed_users.get(event.platform, [])
        return "*" in allowed or event.sender_id in allowed

    async def handle_message(self, event: MessageEvent):
        """Route incoming message to the Architect and send response back."""
        if not self.is_authorized(event):
            logger.warning(f"Unauthorized access attempt from {event.platform}:{event.sender_id}")
            return

        adapter = self.adapters.get(event.platform)
        if not adapter:
            return

        logger.info(f"Processing message from {event.platform}:{event.sender_id}")
        
        # Send typing/action indicator
        await adapter.send_typing(event.chat_id)
        
        try:
            # For long tasks, NEXUS streams response
            full_response = ""
            # Optionally, we could implement chunked delivery to the user here
            # For now, we collect the full response (or send in blocks)
            
            # Simple wrapper to send chunks if needed
            response_buffer = ""
            for chunk in self.architect.stream_coordinate(event.text):
                response_buffer += chunk
                # If buffer gets too big, send a part
                if len(response_buffer) > 2000:
                    await adapter.send_text(event.chat_id, response_buffer)
                    response_buffer = ""
            
            if response_buffer:
                await adapter.send_text(event.chat_id, response_buffer)
                
        except Exception as e:
            logger.error(f"Error in architect reasoning: {e}")
            await adapter.send_text(event.chat_id, f"❌ [GATEWAY_ERROR]: {str(e)}")

    async def run(self):
        """Start all added adapters."""
        self._running = True
        tasks = []
        for adapter in self.adapters.values():
            success = await adapter.connect()
            if success:
                logger.info(f"Successfully connected {adapter.platform} adapter.")
            else:
                logger.error(f"Failed to connect {adapter.platform} adapter.")
        
        # Keep the loop alive
        while self._running:
            await asyncio.sleep(1)

    async def stop(self):
        self._running = False
        for adapter in self.adapters.values():
            await adapter.disconnect()
