"""Authoritative registries - one per component category.

Import :func:`build_default_registries` for a ready-made set, or import the
individual registry classes. There is exactly one authoritative registry per
component type; enable/disable state is tracked here, never via a ``disabled/``
directory.
"""

from nexus.registries.base_registry import (
    BaseRegistry,
    RegistryEntry,
    RegistryState,
)
from nexus.registries.registry_factories import (
    AgentRegistry_,
    AgentTeamRegistry_,
    CapabilityRegistry_,
    CommandRegistry,
    GatewayRegistry_,
    IntegrationRegistry_,
    MCPRegistry_,
    MemoryRegistry_,
    ModelRegistry_,
    PluginRegistry_,
    ProviderRegistry_,
    QueueRegistry_,
    SandboxRegistry_,
    SkillRegistry_,
    ToolRegistry_,
    WorkflowRegistry_,
    build_default_registries,
)

__all__ = [
    "BaseRegistry",
    "RegistryEntry",
    "RegistryState",
    "ToolRegistry_",
    "SkillRegistry_",
    "PluginRegistry_",
    "MCPRegistry_",
    "GatewayRegistry_",
    "ModelRegistry_",
    "ProviderRegistry_",
    "AgentRegistry_",
    "AgentTeamRegistry_",
    "WorkflowRegistry_",
    "MemoryRegistry_",
    "QueueRegistry_",
    "SandboxRegistry_",
    "IntegrationRegistry_",
    "CapabilityRegistry_",
    "CommandRegistry",
    "build_default_registries",
]
