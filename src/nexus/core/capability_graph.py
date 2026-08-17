"""Capability graph: which component provides or depends on each capability.

The capability graph is the authoritative source for:

* which component provides each capability
* which component depends on another
* which tools a skill recommends
* which commands call which subsystem
* which agents can use which tools
* which teams contain which agents
* which gateways support files / streaming / audio / buttons / rich output
* which models support reasoning / vision / tools / audio / structured output
* which provider can replace a failed provider
* which permission is required for each capability
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from nexus.core.errors import GraphError


@dataclass
class CapabilityNode:
    name: str
    provider_component: Optional[str] = None
    permissions: Set[str] = field(default_factory=set)
    features: Set[str] = field(default_factory=set)
    metadata: Dict[str, object] = field(default_factory=dict)


class CapabilityGraph:
    """Directed graph of capabilities and their providing/depending components."""

    def __init__(self) -> None:
        self._nodes: Dict[str, CapabilityNode] = {}
        self._provides: Dict[str, Set[str]] = {}      # component -> capabilities
        self._depends: Dict[str, Set[str]] = {}       # component -> capabilities
        self._requires: Dict[str, Set[str]] = {}      # component -> components

    def register_capability(self, node: CapabilityNode) -> None:
        self._nodes[node.name] = node

    def get_capability(self, name: str) -> CapabilityNode:
        if name not in self._nodes:
            raise GraphError(f"Unknown capability {name!r}")
        return self._nodes[name]

    def add_provider(self, component: str, capability: str) -> None:
        if capability not in self._nodes:
            self._nodes[capability] = CapabilityNode(name=capability)
        self._nodes[capability].provider_component = component
        self._provides.setdefault(component, set()).add(capability)

    def add_dependency(self, component: str, capability: str) -> None:
        if capability not in self._nodes:
            self._nodes[capability] = CapabilityNode(name=capability)
        self._depends.setdefault(component, set()).add(capability)

    def add_component_dependency(self, component: str, depends_on: str) -> None:
        self._requires.setdefault(component, set()).add(depends_on)

    @property
    def capabilities(self) -> List[str]:
        return sorted(self._nodes)

    def providers_of(self, capability: str) -> str | None:
        node = self._nodes.get(capability)
        return node.provider_component if node else None

    def replacement_for(self, capability: str, exclude: str | None = None) -> str | None:
        """Return an alternate provider component for a capability (fallback)."""
        for comp, caps in self._provides.items():
            if capability in caps and comp != exclude:
                return comp
        return None

    def components_for(self, capability: str) -> List[str]:
        return [c for c, caps in self._provides.items() if capability in caps]

    def topological_order(self, components: Iterable[str]) -> List[str]:
        """Order components by their component-dependency edges (Kahn)."""
        comps = list(components)
        indeg = {c: 0 for c in comps}
        adj: Dict[str, List[str]] = {c: [] for c in comps}
        for comp, deps in self._requires.items():
            if comp not in indeg:
                continue
            for d in deps:
                if d in indeg:
                    adj[d].append(comp)
                    indeg[comp] += 1
        queue = [c for c, d in indeg.items() if d == 0]
        order: List[str] = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
        if len(order) != len(comps):
            raise GraphError("Dependency cycle detected among components")
        return order
