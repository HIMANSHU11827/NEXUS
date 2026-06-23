"""Tool lifecycle manager — tracks tools from discovery through deprecation.

States:
  DISCOVERED → REGISTERED → ENABLED → DISABLED → DEPRECATED
  Any state → ERROR

Versioning:
  Default: 1.0
  improve (minor): 1.0 → 1.1 → 1.2
  major_upgrade:    1.x → 2.0 → 2.1 → 3.0
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from . import LifecycleManager, LifecycleState
from .version import default_version, improve_version


class ToolState(Enum):
    DISCOVERED = "discovered"
    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    ERROR = "error"


class ToolLifecycle(LifecycleManager):
    """Lifecycle manager for NEXUS tools with versioning and call health."""

    def __init__(self):
        super().__init__()
        self._tool_states: Dict[str, str] = {}
        self._tool_info: Dict[str, Dict[str, Any]] = {}
        self._call_counts: Dict[str, int] = {}
        self._error_counts: Dict[str, int] = {}
        self._durations: Dict[str, List[float]] = {}
        self._versions: Dict[str, List[str]] = {}

    def discover_tool(self, tool_id: str, name: str, toolset: str = "core") -> str:
        self._tool_states[tool_id] = "discovered"
        self._tool_info[tool_id] = {
            "name": name, "toolset": toolset, "aliases": [],
            "version": default_version(),
        }
        self._versions[tool_id] = [default_version()]
        self._call_counts[tool_id] = 0
        self._error_counts[tool_id] = 0
        self._durations[tool_id] = []
        self.register_entity(tool_id, LifecycleState.CREATED)
        return f"Tool '{name}' v{default_version()} discovered."

    def improve_tool(self, tool_id: str, is_major: bool = False) -> str:
        """Improve tool version. Minor bump by default, major if is_major=True."""
        if tool_id not in self._tool_info:
            return f"Tool '{tool_id}' not found."
        current = self._tool_info[tool_id].get("version", "1.0")
        new_ver = improve_version(current, is_major)
        self._tool_info[tool_id]["version"] = new_ver
        self._versions.setdefault(tool_id, []).append(new_ver)
        kind = "major" if is_major else "minor"
        return f"Tool '{self._tool_info[tool_id]['name']}' {kind} improved: v{current} → v{new_ver}"

    def get_version(self, tool_id: str) -> str:
        return self._tool_info.get(tool_id, {}).get("version", "1.0")

    def get_version_history(self, tool_id: str) -> List[str]:
        return self._versions.get(tool_id, [])

    def register_tool(self, tool_id: str) -> bool:
        if self._tool_states.get(tool_id) != "discovered":
            return False
        self._tool_states[tool_id] = "registered"
        return True

    def enable_tool(self, tool_id: str) -> bool:
        if self._tool_states.get(tool_id) not in ("registered", "disabled"):
            return False
        self._tool_states[tool_id] = "enabled"
        return True

    def disable_tool(self, tool_id: str) -> bool:
        if self._tool_states.get(tool_id) != "enabled":
            return False
        self._tool_states[tool_id] = "disabled"
        return True

    def deprecate_tool(self, tool_id: str, replacement: Optional[str] = None) -> bool:
        current = self._tool_states.get(tool_id)
        if current not in ("enabled", "disabled", "registered"):
            return False
        self._tool_states[tool_id] = "deprecated"
        if replacement:
            self._tool_info[tool_id]["replacement"] = replacement
        return True

    def mark_error(self, tool_id: str) -> bool:
        self._tool_states[tool_id] = "error"
        self._error_counts[tool_id] = self._error_counts.get(tool_id, 0) + 1
        return True

    def record_call(self, tool_id: str, duration_ms: float, success: bool):
        self._call_counts[tool_id] = self._call_counts.get(tool_id, 0) + 1
        self._durations.setdefault(tool_id, []).append(duration_ms)
        if not success:
            self._error_counts[tool_id] = self._error_counts.get(tool_id, 0) + 1

    def get_tool_state(self, tool_id: str) -> Optional[str]:
        return self._tool_states.get(tool_id)

    def get_tool_info(self, tool_id: str) -> Optional[Dict[str, Any]]:
        return self._tool_info.get(tool_id)

    def get_enabled_tools(self) -> List[str]:
        return [tid for tid, s in self._tool_states.items() if s == "enabled"]

    def get_health(self, tool_id: str) -> Dict[str, Any]:
        calls = self._call_counts.get(tool_id, 0)
        errors = self._error_counts.get(tool_id, 0)
        durations = self._durations.get(tool_id, [])
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        return {
            "state": self._tool_states.get(tool_id, "unknown"),
            "version": self.get_version(tool_id),
            "version_history": self.get_version_history(tool_id),
            "call_count": calls,
            "error_count": errors,
            "error_rate": errors / calls if calls > 0 else 0.0,
            "avg_duration_ms": round(avg_duration, 2),
            "info": self._tool_info.get(tool_id),
        }

    def get_stats(self) -> Dict[str, Any]:
        states = {}
        for s in self._tool_states.values():
            states[s] = states.get(s, 0) + 1
        total_calls = sum(self._call_counts.values())
        total_errors = sum(self._error_counts.values())
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "total_tools": len(self._tool_states),
            "by_state": states,
            "total_calls": total_calls,
            "total_errors": total_errors,
            "error_rate": total_errors / total_calls if total_calls > 0 else 0.0,
            "total_version_bumps": total_versions,
        }
