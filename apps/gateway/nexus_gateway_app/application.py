"""Gateway application orchestrator.

Ties together bootstrap (discovery), the engine supervisor, the command-bus
runner adapter, connection/session management, health, and graceful shutdown.
The application owns process lifecycle; the engine owns gateway behaviour.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from .lifecycle import GatewayAppState

logger = logging.getLogger("NEXUS-GATEWAY-APP")


class GatewayApplication:
    """Dedicated Gateway application (spec section 2.10 / 5 / 20)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, config_path: Optional[str] = None):
        self._config = config or {}
        self._config_path = config_path
        self.state = GatewayAppState.CREATED
        self.supervisor = None
        self.connection_manager = None
        self._webhook_task: Optional[asyncio.Task] = None
        self._gateway_task: Optional[asyncio.Task] = None

    # ---- lifecycle --------------------------------------------------- #
    async def start(self) -> None:
        self.state = GatewayAppState.BOOTSTRAPPING
        self.supervisor = await asyncio.to_thread(
            self._bootstrap, self._config, self._config_path
        )
        self.connection_manager = _ConnectionManagerProxy(self.supervisor)
        self.state = GatewayAppState.INITIALIZING

        if self.supervisor is None or not self.supervisor.adapters:
            self.state = GatewayAppState.DEGRADED
            logger.warning("Gateway app degraded: no enabled gateways discovered.")
            return

        self.state = GatewayAppState.STARTING
        self._gateway_task = asyncio.create_task(self.supervisor.run())
        self._webhook_task = self._maybe_start_webhook()
        self.state = GatewayAppState.RUNNING
        logger.info("Gateway application running.")

    def _bootstrap(self, config, config_path):
        from .bootstrap import bootstrap_gateways

        return bootstrap_gateways(config=config, config_path=config_path)

    def _maybe_start_webhook(self):
        if not getattr(self.supervisor, "adapters", {}):
            return None
        try:
            from gateways.webhook_server import start_webhook_server

            verify_token = os.getenv("META_VERIFY_TOKEN", "")
            return asyncio.create_task(
                start_webhook_server(self.supervisor.adapters, verify_token)
            )
        except Exception as exc:
            logger.warning("Webhook server unavailable: %s", exc)
            return None

    async def stop(self) -> None:
        self.state = GatewayAppState.STOPPING
        from .shutdown import graceful_shutdown

        await graceful_shutdown(self.supervisor, self._webhook_task)
        self.state = GatewayAppState.STOPPED

    # ---- introspection ----------------------------------------------- #
    def health(self) -> Dict[str, Any]:
        from .health import aggregate_health

        return aggregate_health(self.supervisor)

    @property
    def enabled_platforms(self) -> list:
        if self.supervisor is None:
            return []
        return list(getattr(self.supervisor, "adapters", {}).keys())


class _ConnectionManagerProxy:
    """Expose connection/session helpers without re-implementing the engine."""

    def __init__(self, supervisor):
        from .connection_manager import ConnectionManager

        self._cm = ConnectionManager(supervisor)

    def connected_platforms(self):
        return self._cm.connected_platforms()

    def register_session(self, chat_id, session_id):
        return self._cm.register_session(chat_id, session_id)

    def resolve_session(self, chat_id):
        return self._cm.resolve_session(chat_id)
