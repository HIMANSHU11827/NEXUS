"""Command router: maps a command to the subsystem that owns it.

The router is a read-only classifier used for observability, capability-graph
population, and routing diagnostics. Actual dispatch is done by the dispatcher;
the router answers "which subsystem does command X belong to?" via the dotted
namespace (``task.list`` -> ``tasks``, ``goal.create`` -> ``goals``).
"""

from __future__ import annotations

from typing import Dict

# namespace -> owning subsystem label
_NAMESPACE_OWNERS: Dict[str, str] = {
    "agent": "main_agent",
    "goal": "goals",
    "task": "tasks",
    "plan": "planning",
    "hive": "hive",
    "tool": "tools",
    "skill": "skills",
    "plugin": "plugins",
    "mcp": "mcp",
    "gateway": "gateways",
    "model": "models",
    "provider": "providers",
    "memory": "memory",
    "workflow": "workflows",
    "automation": "automation",
    "queue": "queues",
    "lifecycle": "lifecycle",
    "learning": "learning",
    "evaluation": "evaluation",
    "evolution": "evolution",
    "maintenance": "maintenance",
    "configure": "configure",
    "security": "security",
    "sandbox": "sandbox",
    "system": "core",
}


class CommandRouter:
    def owner_of(self, command: str) -> str:
        ns = command.split(".", 1)[0].lower()
        return _NAMESPACE_OWNERS.get(ns, "uncategorized")

    def route(self, command: str) -> str:
        return self.owner_of(command)
