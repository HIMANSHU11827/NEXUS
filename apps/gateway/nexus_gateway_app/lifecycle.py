"""Lifecycle state model for the Gateway application (mirrors spec section 8)."""

from enum import Enum


class GatewayAppState(str, Enum):
    """High-level state of the gateway application process."""

    CREATED = "created"
    BOOTSTRAPPING = "bootstrapping"
    INITIALIZING = "initializing"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        return self in (self.__class__.STOPPED, self.__class__.FAILED)
