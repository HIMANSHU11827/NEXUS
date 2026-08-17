"""Concrete authoritative registries - exactly one per component category.

Each registry is a thin specialization of :class:`BaseRegistry` that pins the
``category`` and a ``validate`` implementation appropriate to its component
type. Enable/disable state is tracked here; it is the single source of truth
for whether a component is active (there is no ``disabled/`` directory).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Type

from nexus.registries.base_registry import BaseRegistry, RegistryState, T


def _make_registry(category: str, validate_fn: Optional[Callable[[Any], None]] = None,
                   state_path: Optional[str] = None) -> Type[BaseRegistry]:
    """Build a concrete registry class for a category."""
    ns: Dict[str, Any] = {
        "category": category,
        "__doc__": f"Authoritative {category} registry.",
    }

    def validate(self, component: Any) -> None:  # noqa: ANN001 - generic
        if validate_fn is not None:
            validate_fn(component)

    ns["validate"] = validate
    return type(f"{category.title().replace('_', '')}Registry", (BaseRegistry,), ns)


# Common lightweight validators ------------------------------------------------
def _require_attr(attr: str):
    def _v(component: Any) -> None:
        if not hasattr(component, attr):
            raise ValueError(f"component missing required attribute {attr!r}")
    return _v


ToolRegistry_ = _make_registry("tools", _require_attr("name"))
SkillRegistry_ = _make_registry("skills", _require_attr("name"))
PluginRegistry_ = _make_registry("plugins", _require_attr("name"))
MCPRegistry_ = _make_registry("mcp", _require_attr("name"))
GatewayRegistry_ = _make_registry("gateways", _require_attr("name"))
ModelRegistry_ = _make_registry("models", _require_attr("name"))
ProviderRegistry_ = _make_registry("providers", _require_attr("name"))
AgentRegistry_ = _make_registry("agents", _require_attr("name"))
AgentTeamRegistry_ = _make_registry("agent_teams", _require_attr("name"))
WorkflowRegistry_ = _make_registry("workflows", _require_attr("name"))
MemoryRegistry_ = _make_registry("memory", _require_attr("name"))
QueueRegistry_ = _make_registry("queues", _require_attr("name"))
SandboxRegistry_ = _make_registry("sandboxes", _require_attr("name"))
IntegrationRegistry_ = _make_registry("integrations", _require_attr("name"))
CapabilityRegistry_ = _make_registry("capabilities", _require_attr("name"))


# Command registry wraps the central dispatcher so there is one source of truth.
class CommandRegistry(BaseRegistry):
    category = "commands"

    def __init__(self, dispatcher=None, state_path: Optional[str] = None) -> None:
        super().__init__(state_path)
        # dispatcher is the authoritative handler registry (nexus.commands).
        self.dispatcher = dispatcher

    def validate(self, component: Any) -> None:  # pragma: no cover - trivial
        if not getattr(component, "command", None):
            raise ValueError("command handler missing 'command' name")

    def register(self, id: str, component: Any, **kwargs):  # type: ignore[override]
        # delegate registration to the dispatcher when present
        if self.dispatcher is not None:
            self.dispatcher.register(component)
        return super().register(id, component, **kwargs)

    @property
    def commands(self):
        return self.dispatcher.commands if self.dispatcher else []


def build_default_registries(state_dir: str = ".nexus/registries") -> Dict[str, BaseRegistry]:
    """Return one authoritative registry instance per component category."""
    import os
    def sp(cat: str) -> str:
        return os.path.join(state_dir, f"{cat}.json")
    return {
        "tools": ToolRegistry_(state_path=sp("tools")),
        "skills": SkillRegistry_(state_path=sp("skills")),
        "plugins": PluginRegistry_(state_path=sp("plugins")),
        "mcp": MCPRegistry_(state_path=sp("mcp")),
        "gateways": GatewayRegistry_(state_path=sp("gateways")),
        "models": ModelRegistry_(state_path=sp("models")),
        "providers": ProviderRegistry_(state_path=sp("providers")),
        "agents": AgentRegistry_(state_path=sp("agents")),
        "agent_teams": AgentTeamRegistry_(state_path=sp("agent_teams")),
        "workflows": WorkflowRegistry_(state_path=sp("workflows")),
        "memory": MemoryRegistry_(state_path=sp("memory")),
        "queues": QueueRegistry_(state_path=sp("queues")),
        "sandboxes": SandboxRegistry_(state_path=sp("sandboxes")),
        "integrations": IntegrationRegistry_(state_path=sp("integrations")),
        "capabilities": CapabilityRegistry_(state_path=sp("capabilities")),
    }
