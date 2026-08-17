"""Entry point for the dedicated Gateway application.

Usage:
    python -m apps.gateway.nexus_gateway_app
    nexus-gateway-app   (after installing the console script)

This is the application layer only; all gateway behaviour is delegated to the
``gateways`` engine package.
"""

from __future__ import annotations

import asyncio
import logging

from .lifecycle import GatewayAppState

logger = logging.getLogger("NEXUS-GATEWAY")


def main() -> None:
    """Synchronous console-script entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Gateway application interrupted.")


async def _run() -> None:
    from .application import GatewayApplication

    app = GatewayApplication()
    try:
        await app.start()
        if app.state == GatewayAppState.DEGRADED:
            logger.warning("Started in degraded mode (no enabled gateways).")
        # Keep the process alive while running.
        while app.state == GatewayAppState.RUNNING:
            await asyncio.sleep(1.0)
    finally:
        await app.stop()
