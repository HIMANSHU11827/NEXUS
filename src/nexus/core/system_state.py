"""System-level state, health, and context definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class SystemState(str, Enum):
    """Coarse lifecycle states of the whole Nexus system."""

    CREATED = "created"
    BOOTSTRAPPING = "bootstrapping"
    INITIALIZING = "initializing"
    VALIDATING = "validating"
    STARTING = "starting"
    RUNNING = "running"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    STOPPING = "stopping"
    STOPPED = "stopped"
    DIAGNOSING = "diagnosing"
    REPAIRING = "repairing"
    RECOVERING = "recovering"
    RECOVERY_EXHAUSTED = "recovery_exhausted"
    ESCALATED = "escalated"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class SystemContext:
    """Immutable-ish snapshot of the running system's context.

    Carries the resolved root paths and runtime flags used by every subsystem
    so that components do not each re-derive environment state.
    """

    root_path: str = "."
    config_path: str = "configure"
    data_path: str = "data"
    storage_path: str = "storage"
    runtime_state_path: str = ".nexus"
    env: str = "development"
    version: str = "2.1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def child(self, **overrides: Any) -> "SystemContext":
        merged = dict(self.metadata)
        merged.update(overrides.pop("metadata", {}))
        base = dict(
            root_path=self.root_path,
            config_path=self.config_path,
            data_path=self.data_path,
            storage_path=self.storage_path,
            runtime_state_path=self.runtime_state_path,
            env=self.env,
            version=self.version,
        )
        base.update(overrides)
        base["metadata"] = merged
        return SystemContext(**base)
