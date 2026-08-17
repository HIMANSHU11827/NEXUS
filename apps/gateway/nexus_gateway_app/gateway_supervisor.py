"""Thin wrapper over the engine's ``GatewaySupervisor`` / ``PlatformRuntime``.

Kept so the application has a stable, documented import surface
(``from apps.gateway.nexus_gateway_app.gateway_supervisor import ...``) that
does not depend on the engine's internal module layout.
"""

from __future__ import annotations

from gateways.supervisor import GatewaySupervisor, PlatformRuntime  # noqa: F401

__all__ = ["GatewaySupervisor", "PlatformRuntime"]


def new_supervisor(config=None):
    """Construct a supervisor with optional config (delegates to the engine)."""
    return GatewaySupervisor(config=config)
