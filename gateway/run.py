import asyncio
import os
import re
import logging
from typing import Dict, List, Optional
from gateway.base import BasePlatformAdapter, MessageEvent
from orchestrators.loop import NexusLoop

logger = logging.getLogger(__name__)

class GatewayRunner:
    """
    NEXUS UNIFIED GATEWAY COMMANDER
    Orchestrates platform adapters and routes them to the shared NexusLoop runtime.
    Each chat maps to a stable session id visible on terminal, CLI, and GUI.
    """
    
    def __init__(self):
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self._loops: Dict[str, NexusLoop] = {}
        self._running = False

    @staticmethod
    def session_id_for(event: MessageEvent) -> str:
        raw = f"gateway_{event.platform}_{event.chat_id}"
        return re.sub(r"[^A-Za-z0-9_.-]", "_", raw)[:120]

    def _get_loop(self, event: MessageEvent) -> NexusLoop:
        session_id = self.session_id_for(event)
        if session_id not in self._loops:
            loop = NexusLoop()
            loop.load_memory(session_id)
            self._loops[session_id] = loop
        return self._loops[session_id]

    def add_adapter(self, adapter: BasePlatformAdapter):
        self.adapters[adapter.platform] = adapter
        adapter.set_message_handler(self.handle_message)

    def is_authorized(self, event: MessageEvent) -> bool:
        """Check if the user is allowed to issue commands."""
        from authentication import is_gateway_authorized
        return is_gateway_authorized(event.platform, event.sender_id)

    async def handle_message(self, event: MessageEvent):
        """Route incoming message to NexusLoop and send response back."""
        if not self.is_authorized(event):
            logger.warning(f"Unauthorized access attempt from {event.platform}:{event.sender_id}")
            return

        adapter = self.adapters.get(event.platform)
        if not adapter:
            return

        from session_bus import set_active_session_id, sync_loop_from_disk

        session_id = self.session_id_for(event)
        logger.info(
            "Processing message from %s:%s (session=%s)",
            event.platform, event.sender_id, session_id,
        )
        
        # Send typing/action indicator
        await adapter.send_typing(event.chat_id)
        
        try:
            loop = self._get_loop(event)
            set_active_session_id(loop.root, session_id, source=f"gateway:{event.platform}")
            sync_loop_from_disk(loop)
            response_buffer = ""
            for chunk in loop.stream_run(event.text):
                if not chunk or chunk.startswith("[TOOL_") or chunk.startswith("[NEXUS_ACTIVITY]"):
                    continue
                response_buffer += chunk
                if len(response_buffer) > 2000:
                    await adapter.send_text(event.chat_id, response_buffer)
                    response_buffer = ""
            
            if response_buffer:
                await adapter.send_text(event.chat_id, response_buffer)
                
        except Exception as e:
            logger.error(f"Error in gateway reasoning: {e}")
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
