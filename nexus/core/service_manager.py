"""Central service manager: registers, starts, stops, and health-checks subsystems.

A *service* is any lifecycle-aware subsystem (Core, Lifecycle, Command Bus,
ToolRegistry, etc.). The manager enforces start/stop order via a dependency
graph and isolates service failures so one broken service cannot take down the
whole runtime (degraded operation).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional, Set

from nexus.core.dependency_graph import DependencyGraph, DependencyNode
from nexus.core.errors import ServiceError
from nexus.core.health import HealthStatus


class ServiceState(str, Enum):
    REGISTERED = "registered"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class ServiceSpec:
    name: str
    start: Optional[Callable[[Any], Awaitable[None]]] = None
    stop: Optional[Callable[[Any], Awaitable[None]]] = None
    health: Optional[Callable[[], Awaitable[HealthStatus]]] = None
    dependencies: Set[str] = field(default_factory=set)
    optional: Set[str] = field(default_factory=set)
    required: bool = True  # required services failing startup cause FatalStartupError
    instance: Any = None


class ServiceManager:
    def __init__(self) -> None:
        self._specs: Dict[str, ServiceSpec] = {}
        self._state: Dict[str, ServiceState] = {}
        self._graph = DependencyGraph()

    def register(self, spec: ServiceSpec) -> None:
        if spec.name in self._specs and self._specs[spec.name] is not spec:
            raise ServiceError(f"Service already registered: {spec.name!r}")
        self._specs[spec.name] = spec
        self._state[spec.name] = ServiceState.REGISTERED
        self._graph.add(
            DependencyNode(
                name=spec.name,
                dependencies=set(spec.dependencies),
                optional=set(spec.optional),
            )
        )

    def get(self, name: str) -> Optional[ServiceSpec]:
        return self._specs.get(name)

    @property
    def state(self) -> Dict[str, ServiceState]:
        return dict(self._state)

    def start_order(self) -> List[str]:
        return self._graph.resolve_order()

    async def start_all(self) -> Dict[str, ServiceState]:
        order = self.start_order()
        # Start in dependency order; reverse that for stop.
        for name in order:
            spec = self._specs[name]
            self._state[name] = ServiceState.STARTING
            try:
                if spec.start is not None:
                    await spec.start(spec.instance)
                self._state[name] = ServiceState.RUNNING
            except Exception as exc:  # noqa: BLE001 - isolate failures
                self._state[name] = ServiceState.FAILED
                if spec.required:
                    raise ServiceError(
                        f"Required service {name!r} failed to start: {exc}"
                    ) from exc
        return self.state

    async def stop_all(self) -> Dict[str, ServiceState]:
        order = list(reversed(self.start_order()))
        for name in order:
            spec = self._specs[name]
            if self._state.get(name) not in (ServiceState.RUNNING, ServiceState.DEGRADED):
                continue
            self._state[name] = ServiceState.STOPPING
            try:
                if spec.stop is not None:
                    await spec.stop(spec.instance)
            except Exception:  # noqa: BLE001 - best-effort on shutdown
                pass
            self._state[name] = ServiceState.STOPPED
        return self.state

    async def health(self, name: str) -> HealthStatus:
        spec = self._specs.get(name)
        if spec is None or spec.health is None:
            return HealthStatus.UNKNOWN
        return await spec.health()
