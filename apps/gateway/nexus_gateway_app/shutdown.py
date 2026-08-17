"""Graceful shutdown for the gateway application.

Coordinates stopping the supervisor (which cancels the supervision loop,
await pending disconnects, and flushes lifecycle state) and the optional
webhook server, bounded by the engine's ``shutdown_timeout`` (spec section 30).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("NEXUS-GATEWAY-SHUTDOWN")


async def graceful_shutdown(supervisor, webhook_task: Optional[asyncio.Task] = None, timeout: float = 30.0):
    """Stop the gateway supervisor and webhook server safely."""
    logger.info("Gateway application shutting down...")
    try:
        if supervisor is not None:
            await supervisor.stop_all()
    except Exception:  # shutdown must never raise — log and continue
        logger.exception("Error during supervisor shutdown")

    if webhook_task is not None and not webhook_task.done():
        webhook_task.cancel()
        try:
            await asyncio.wait_for(webhook_task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.warning("Webhook server did not stop cleanly within %.1fs", timeout)
        except Exception:
            logger.exception("Error stopping webhook server")
    logger.info("Gateway application stopped.")
