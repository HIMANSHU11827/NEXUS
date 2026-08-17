"""Nexus Core - authoritative system coordination package.

This package owns the overall system lifecycle, connects subsystems, enforces
startup/shutdown order, tracks global state, maintains capability and dependency
graphs, and supports degraded operation when optional components fail.

It is designed to coexist with the legacy boot module ``nexus/__init__.py`` and
the existing ``nexus.events`` / ``nexus.commands`` registries; it does not shadow
them. New code should import from here for authoritative lifecycle and graph
services.
"""

from nexus.core.errors import (
    CoreError,
    LifecycleError,
    StartupError,
    ShutdownError,
    DependencyError,
    ServiceError,
)
from nexus.core.system_state import SystemState, SystemContext, HealthStatus
from nexus.core.state_machine import StateMachine
from nexus.core.capability_graph import CapabilityGraph, CapabilityNode
from nexus.core.dependency_graph import DependencyGraph
from nexus.core.service_manager import ServiceManager, ServiceSpec
from nexus.core.control_plane import ControlPlane
from nexus.core.kernel import NexusKernel
from nexus.core.nexus import Nexus
from nexus.core.startup_sequence import StartupSequence
from nexus.core.shutdown_sequence import ShutdownSequence

__all__ = [
    "CoreError", "LifecycleError", "StartupError", "ShutdownError",
    "DependencyError", "ServiceError",
    "SystemState", "SystemContext", "HealthStatus",
    "StateMachine",
    "CapabilityGraph", "CapabilityNode",
    "DependencyGraph",
    "ServiceManager", "ServiceSpec",
    "ControlPlane",
    "NexusKernel",
    "Nexus",
    "StartupSequence",
    "ShutdownSequence",
]
