"""Health aggregation for the gateway application.

Reads per-platform runtime state/health from the engine supervisor and rolls
it up into a single application health view (spec section 24 observability).
"""

from __future__ import annotations

import logging
from typing import Dict

from .lifecycle import GatewayAppState

logger = logging.getLogger("NEXUS-GATEWAY-HEALTH")


def aggregate_health(supervisor) -> Dict[str, Dict[str, str]]:
    """Return a per-platform health map plus an overall status."""
    platforms: Dict[str, Dict[str, str]] = {}
    if supervisor is None:
        return {"__overall__": {"status": "no_gateways", "state": GatewayAppState.DEGRADED.value}}
    for name, rt in getattr(supervisor, "runtimes", {}).items():
        platforms[name] = {
            "state": str(getattr(rt, "state", "unknown")),
            "health": str(getattr(rt, "health", "unknown")),
        }
    running = [n for n, m in platforms.items() if m["state"] in ("running",) and m["health"] in ("healthy",)]
    overall = "healthy" if running else ("degraded" if platforms else "no_gateways")
    return {"__overall__": {"status": overall, "state": GatewayAppState.RUNNING.value}, "platforms": platforms}
