"""Authoritative health reporting for core subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    detail: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)


class HealthReporter:
    """Aggregates per-component health into a system-level status."""

    def __init__(self) -> None:
        self._components: Dict[str, ComponentHealth] = {}

    def report(self, health: ComponentHealth) -> None:
        self._components[health.name] = health

    def get(self, name: str) -> Optional[ComponentHealth]:
        return self._components.get(name)

    def overall(self) -> HealthStatus:
        statuses = {h.status for h in self._components.values()}
        if not statuses:
            return HealthStatus.UNKNOWN
        if statuses <= {HealthStatus.HEALTHY}:
            return HealthStatus.HEALTHY
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.DEGRADED
