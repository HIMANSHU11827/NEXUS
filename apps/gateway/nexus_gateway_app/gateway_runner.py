"""Gateway command adapter.

Wraps the engine's ``GatewayRunner`` and, when the central command bus is
initialised AND a matching command is registered, routes inbound gateway
messages through it (``nexus.commands``), preserving the mandate's "one
central command system" rule (spec section 12 / 33).

If the bus is unavailable or no gateway command is registered, the engine's
existing Nexus-loop pipeline is used unchanged — behaviour is never regressed
and no non-existent command is invented.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("NEXUS-GATEWAY-RUNNER")


def _command_registry():
    """Return the central command registry if Nexus has initialised one."""
    try:
        from nexus.commands import get_registry

        return get_registry()
    except Exception:
        return None


class CommandBusGatewayRunner:
    """Adapter that feeds gateway messages to the central command bus."""

    def __init__(self, engine_runner=None, command_name: str = "gateway.message"):
        self._engine_runner = engine_runner
        self._command_name = command_name
        self._registry = _command_registry()

    @property
    def uses_command_bus(self) -> bool:
        return self._registry is not None and self._registry.get(self._command_name) is not None

    async def handle_message(self, event) -> Any:
        """Route an inbound message event to the command bus or the engine."""
        if self.uses_command_bus:
            try:
                from nexus.commands import CommandContext

                ctx = CommandContext(
                    session_id=getattr(event, "chat_id", "default"),
                    extra={
                        "platform": getattr(event, "platform", None),
                        "text": getattr(event, "text", ""),
                    },
                )
                return await self._registry.execute(self._command_name, ctx)
            except Exception as exc:  # fall back rather than drop the message
                logger.warning("Command-bus routing failed, using engine pipeline: %s", exc)

        if self._engine_runner is not None:
            return await self._engine_runner.handle_message(event)
        logger.warning("No engine runner available to handle gateway message")
        return None
