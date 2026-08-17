"""Control plane: the authoritative cross-subsystem coordination facade.

The control plane owns the service manager, capability graph, dependency graph,
and health reporter. Subsystems register themselves here; the main Nexus object
drives startup/shutdown through it. It is deliberately thin - it does not contain
business logic for any subsystem, only coordination contracts.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from nexus.core.capability_graph import CapabilityGraph
from nexus.core.dependency_graph import DependencyGraph
from nexus.core.health import HealthReporter, HealthStatus
from nexus.core.service_manager import ServiceManager, ServiceSpec, ServiceState


class ControlPlane:
    def __init__(self) -> None:
        self.services = ServiceManager()
        self.capabilities = CapabilityGraph()
        self.dependencies = DependencyGraph()
        self.health = HealthReporter()
        self._extensions: Dict[str, Any] = {}

    def register_service(self, spec: ServiceSpec) -> None:
        self.services.register(spec)

    def attach(self, key: str, value: Any) -> None:
        self._extensions[key] = value

    def get(self, key: str) -> Optional[Any]:
        return self._extensions.get(key)

    async def start(self) -> Dict[str, ServiceState]:
        return await self.services.start_all()

    async def stop(self) -> Dict[str, ServiceState]:
        return await self.services.stop_all()

    def overall_health(self) -> HealthStatus:
        return self.health.overall()
