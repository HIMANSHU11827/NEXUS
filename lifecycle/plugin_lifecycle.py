"""Plugin lifecycle manager — tracks plugins from discovery through unloading.

States:
  DISCOVERED → LOADED → REGISTERED → RUNNING → STOPPED → UNLOADED
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


class PluginState(Enum):
    DISCOVERED = "discovered"
    LOADED = "loaded"
    REGISTERED = "registered"
    RUNNING = "running"
    STOPPED = "stopped"
    UNLOADED = "unloaded"
    ERROR = "error"


class PluginLifecycle(LifecycleManager):
    """Lifecycle manager for NEXUS plugins with versioning."""

    def __init__(self):
        super().__init__()
        self._valid_transitions = {
            LifecycleState.CREATED: {self._to_ls("discovered"), LifecycleState.ERROR},
        }
        self._plugin_transitions = {
            "discovered": {"loaded", "error"},
            "loaded": {"registered", "error"},
            "registered": {"running", "stopped", "error"},
            "running": {"stopped", "error"},
            "stopped": {"running", "unloaded", "error"},
            "unloaded": set(),
            "error": {"loaded", "unloaded"},
        }
        self._plugin_states: Dict[str, str] = {}
        self._plugin_info: Dict[str, Dict[str, Any]] = {}
        self._versions: Dict[str, List[str]] = {}
        self._hooks: Dict[str, List] = {
            "on_load": [], "on_register": [], "on_start": [],
            "on_stop": [], "on_unload": [],
        }

    def _to_ls(self, state_str: str) -> LifecycleState:
        mapping = {
            "discovered": LifecycleState.CREATED,
            "loaded": LifecycleState.ACTIVE,
            "registered": LifecycleState.ACTIVE,
            "running": LifecycleState.ACTIVE,
            "stopped": LifecycleState.STALE,
            "unloaded": LifecycleState.DELETED,
            "error": LifecycleState.ERROR,
        }
        return mapping.get(state_str, LifecycleState.CREATED)

    def discover_plugin(self, plugin_id: str, name: str, version: str = "") -> str:
        ver = version if version else default_version()
        self._plugin_states[plugin_id] = "discovered"
        self._plugin_info[plugin_id] = {"name": name, "version": ver}
        self._versions[plugin_id] = [ver]
        self.register_entity(plugin_id, LifecycleState.CREATED)
        return f"Plugin '{name}' v{ver} discovered."

    def improve_plugin(self, plugin_id: str, is_major: bool = False) -> str:
        """Improve plugin version. Minor bump by default, major if is_major=True."""
        if plugin_id not in self._plugin_info:
            return f"Plugin '{plugin_id}' not found."
        current = self._plugin_info[plugin_id].get("version", "1.0")
        new_ver = improve_version(current, is_major)
        self._plugin_info[plugin_id]["version"] = new_ver
        self._versions.setdefault(plugin_id, []).append(new_ver)
        kind = "major" if is_major else "minor"
        return f"Plugin '{self._plugin_info[plugin_id]['name']}' {kind} improved: v{current} → v{new_ver}"

    def get_version(self, plugin_id: str) -> str:
        return self._plugin_info.get(plugin_id, {}).get("version", "1.0")

    def get_version_history(self, plugin_id: str) -> List[str]:
        return self._versions.get(plugin_id, [])

    def load_plugin(self, plugin_id: str) -> bool:
        if self._plugin_states.get(plugin_id) != "discovered":
            return False
        self._plugin_states[plugin_id] = "loaded"
        self._run_plugin_hooks("on_load", plugin_id)
        return True

    def register_plugin(self, plugin_id: str) -> bool:
        if self._plugin_states.get(plugin_id) != "loaded":
            return False
        self._plugin_states[plugin_id] = "registered"
        self._run_plugin_hooks("on_register", plugin_id)
        return True

    def start_plugin(self, plugin_id: str) -> bool:
        if self._plugin_states.get(plugin_id) not in ("registered", "stopped"):
            return False
        self._plugin_states[plugin_id] = "running"
        self._run_plugin_hooks("on_start", plugin_id)
        return True

    def stop_plugin(self, plugin_id: str) -> bool:
        if self._plugin_states.get(plugin_id) != "running":
            return False
        self._plugin_states[plugin_id] = "stopped"
        self._run_plugin_hooks("on_stop", plugin_id)
        return True

    def unload_plugin(self, plugin_id: str) -> bool:
        current = self._plugin_states.get(plugin_id)
        if current not in ("stopped", "error"):
            return False
        self._plugin_states[plugin_id] = "unloaded"
        self._run_plugin_hooks("on_unload", plugin_id)
        return True

    def mark_error(self, plugin_id: str) -> bool:
        self._plugin_states[plugin_id] = "error"
        return True

    def add_hook(self, hook_name: str, fn):
        if hook_name in self._hooks:
            self._hooks[hook_name].append(fn)

    def _run_plugin_hooks(self, hook_name: str, plugin_id: str):
        for hook in self._hooks.get(hook_name, []):
            try:
                hook(plugin_id)
            except Exception:
                pass

    def get_plugin_state(self, plugin_id: str) -> Optional[str]:
        return self._plugin_states.get(plugin_id)

    def get_plugin_info(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        return self._plugin_info.get(plugin_id)

    def list_plugins_by_state(self, state: str) -> List[str]:
        return [pid for pid, s in self._plugin_states.items() if s == state]

    def get_stats(self) -> Dict[str, Any]:
        states = {}
        for s in self._plugin_states.values():
            states[s] = states.get(s, 0) + 1
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "total_plugins": len(self._plugin_states),
            "by_state": states,
            "total_version_bumps": total_versions,
        }
