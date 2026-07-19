import asyncio
import logging
import os
from typing import Dict, List

from gateway.base import BasePlatformAdapter, MessageEvent
from gateway.platforms import all_adapters, get_adapter
from gateway.session_ids import gateway_session_id
from orchestrators.loop import NexusLoop

logger = logging.getLogger(__name__)

_PLATFORM_ENV_MAP: Dict[str, List[List[str]]] = {
    "telegram": [["TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"]],
    "discord": [["DISCORD_BOT_TOKEN", "DISCORD_TOKEN"]],
    "whatsapp": [["META_ACCESS_TOKEN", "WHATSAPP_TOKEN"]],
    "meta": [["META_ACCESS_TOKEN", "META_PAGE_TOKEN"]],
    "slack": [["SLACK_BOT_TOKEN", "SLACK_TOKEN"]],
    "signal": [["SIGNAL_NUMBER"]],
    "matrix": [["MATRIX_HOMESERVER"], ["MATRIX_USER"]],
    "mattermost": [["MATTERMOST_URL"], ["MATTERMOST_TOKEN"]],
    "email": [["SMTP_HOST"], ["SMTP_USER"]],
    "sms": [["TWILIO_ACCOUNT_SID"], ["TWILIO_AUTH_TOKEN"], ["TWILIO_FROM_NUMBER"]],
}


def _has_required_env(required_groups: List[List[str]]) -> bool:
    return all(any(os.getenv(name) for name in group) for group in required_groups)


class GatewayRunner:
    """
    NEXUS UNIFIED GATEWAY COMMANDER
    Orchestrates platform adapters and routes them to the shared NexusLoop runtime.
    Each chat maps to a stable session id visible on TUI and GUI.
    """

    def __init__(self):
        self.adapters: Dict[str, BasePlatformAdapter] = {}
        self._loops: Dict[str, NexusLoop] = {}
        self._running = False

    @staticmethod
    def session_id_for(event: MessageEvent) -> str:
        return gateway_session_id(event.platform, event.chat_id)

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

    def register_all(self):
        """Auto-discover and register every platform whose env vars are present."""
        for platform_name in all_adapters():
            required = _PLATFORM_ENV_MAP.get(platform_name, [])
            if required and not _has_required_env(required):
                logger.debug(f"Skipping {platform_name} — missing env vars {required}")
                continue

            try:
                adapter = get_adapter(platform_name)
                self.add_adapter(adapter)
                logger.info(f"Registered {platform_name} adapter")
            except Exception as e:
                logger.warning(f"Failed to register {platform_name}: {e}")

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

        from utils.session_bus import set_active_session_id, sync_loop_from_disk

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
            async for chunk in loop.stream_run(event.text):
                if isinstance(chunk, dict):
                    if chunk.get("type") != "content":
                        continue
                    content = chunk.get("data")
                    if not isinstance(content, str):
                        continue
                elif isinstance(chunk, str):
                    content = chunk
                else:
                    continue

                if not content or content.startswith("[TOOL_") or content.startswith("[NEXUS_ACTIVITY]"):
                    continue
                response_buffer += content
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
