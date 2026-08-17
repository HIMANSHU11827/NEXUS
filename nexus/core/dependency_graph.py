"""Dependency graph for components and their declared dependencies.

Used to resolve start order and detect cycles before activation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from nexus.core.errors import DependencyError


@dataclass
class DependencyNode:
    name: str
    dependencies: Set[str] = field(default_factory=set)
    optional: Set[str] = field(default_factory=set)
    metadata: Dict[str, object] = field(default_factory=dict)


class DependencyGraph:
    def __init__(self) -> None:
        self._nodes: Dict[str, DependencyNode] = {}

    def add(self, node: DependencyNode) -> None:
        self._nodes[node.name] = node

    def get(self, name: str) -> DependencyNode:
        if name not in self._nodes:
            raise DependencyError(f"Unknown dependency node {name!r}")
        return self._nodes[name]

    def has(self, name: str) -> bool:
        return name in self._nodes

    def resolve_order(self) -> List[str]:
        """Return components in dependency (start) order; raises on cycles."""
        order: List[str] = []
        visited: Dict[str, int] = {}  # 0=visiting, 1=done

        def visit(name: str, stack: List[str]) -> None:
            state = visited.get(name, 0)
            if state == 1:
                return
            if state == 0:
                raise DependencyError(
                    f"Dependency cycle: {' -> '.join(stack + [name])}"
                )
            visited[name] = 0
            node = self._nodes.get(name)
            if node is not None:
                for dep in sorted(node.dependencies):
                    if dep in self._nodes:
                        visit(dep, stack + [name])
            visited[name] = 1
            order.append(name)

        for name in sorted(self._nodes):
            visit(name, [])
        return order

    def missing_required(self, available: Set[str]) -> List[str]:
        missing: List[str] = []
        for name, node in self._nodes.items():
            for dep in sorted(node.dependencies):
                if dep not in available and dep not in node.optional:
                    missing.append(f"{name} requires {dep}")
        return missing
