"""Unified gateway command runner — routes all messages through the CommandBus.

This is the single authoritative gateway adapter.  Every inbound message
(API, TUI, Web, Telegram, Discord, Slack, WhatsApp) is routed through the
same CommandBus with middleware, alias resolution, timeout enforcement, and
lifecycle events.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger("NEXUS-GATEWAY-RUNNER")


class CommandBusGatewayRunner:
    """Adapter that feeds gateway messages to the unified CommandBus."""

    def __init__(self, engine_runner=None, command_name: str = "gateway.message"):
        self._engine_runner = engine_runner
        self._command_name = command_name

    @property
    def uses_command_bus(self) -> bool:
        try:
            from nexus.command_system.bridge import patched_get_bus
            bus = patched_get_bus()
            return bus.dispatcher.has(self._command_name)
        except Exception:
            return False

    async def handle_message(self, event) -> Any:
        """Route an inbound message event through the unified CommandBus.

        Falls back to the engine runner if the command is not registered.
        """
        # Only route through bus if the command is registered
        if self.uses_command_bus:
            try:
                from nexus.command_system.bridge import patched_get_bus
                from nexus.command_system.core.command import CommandRequest, CommandContext

                bus = patched_get_bus()
                request = CommandRequest(
                    command=self._command_name,
                    args=[getattr(event, "text", "")],
                    options={
                        "platform": getattr(event, "platform", None),
                        "text": getattr(event, "text", ""),
                        "chat_id": getattr(event, "chat_id", "default"),
                        "sender_id": getattr(event, "sender_id", None),
                    },
                    context=CommandContext(
                        source=getattr(event, "platform", "gateway"),
                        session_id=getattr(event, "chat_id", "default"),
                        user_id=getattr(event, "sender_id", None),
                    ),
                )
                return await bus.execute(request)
            except Exception as exc:
                logger.warning("Command-bus routing failed, using engine pipeline: %s", exc)

        if self._engine_runner is not None:
            return await self._engine_runner.handle_message(event)
        logger.warning("No engine runner available to handle gateway message")
        return None
