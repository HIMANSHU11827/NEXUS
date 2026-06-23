"""Memory lifecycle manager — tracks memory records from storage through eviction.

States:
  STORED → ACCESSED → CONSOLIDATED → ARCHIVED → EVICTED
  Any state → ERROR

Versioning:
  Default: 1.0
  improve (minor): 1.0 → 1.1 → 1.2
  major_upgrade:    1.x → 2.0 → 2.1 → 3.0
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime

from . import LifecycleManager, LifecycleState
from .version import default_version, improve_version


class MemoryState(Enum):
    STORED = "stored"
    ACCESSED = "accessed"
    CONSOLIDATED = "consolidated"
    ARCHIVED = "archived"
    EVICTED = "evicted"
    ERROR = "error"


class MemoryLifecycle(LifecycleManager):
    """Lifecycle manager for NEXUS memory records with versioning."""

    def __init__(self):
        super().__init__()
        self._valid_transitions = {
            LifecycleState.CREATED: {self._to_ls("stored"), LifecycleState.ERROR},
        }
        self._memory_transitions = {
            "stored": {"accessed", "consolidated", "archived", "evicted", "error"},
            "accessed": {"stored", "consolidated", "archived", "evicted", "error"},
            "consolidated": {"accessed", "archived", "evicted", "error"},
            "archived": {"evicted", "consolidated", "accessed", "error"},
            "evicted": set(),
            "error": {"stored", "archived"},
        }
        self._memory_states: Dict[str, str] = {}
        self._memory_info: Dict[str, Dict[str, Any]] = {}
        self._access_logs: Dict[str, List[str]] = {}
        self._versions: Dict[str, List[str]] = {}

    def _to_ls(self, state_str: str) -> LifecycleState:
        mapping = {
            "stored": LifecycleState.CREATED,
            "accessed": LifecycleState.ACTIVE,
            "consolidated": LifecycleState.ACTIVE,
            "archived": LifecycleState.ARCHIVED,
            "evicted": LifecycleState.DELETED,
            "error": LifecycleState.ERROR,
        }
        return mapping.get(state_str, LifecycleState.CREATED)

    def store_memory(self, memory_id: str, content: str, memory_type: str = "episodic") -> str:
        self._memory_states[memory_id] = "stored"
        self._memory_info[memory_id] = {
            "content": content,
            "type": memory_type,
            "created": datetime.now().isoformat(),
            "access_count": 0,
            "importance": 0.5,
            "version": default_version(),
        }
        self._versions[memory_id] = [default_version()]
        self._access_logs[memory_id] = []
        self.register_entity(memory_id, LifecycleState.CREATED)
        return f"Memory '{memory_id}' v{default_version()} stored (type={memory_type})."

    def improve_memory(self, memory_id: str, is_major: bool = False) -> str:
        """Improve memory version. Minor bump by default, major if is_major=True."""
        if memory_id not in self._memory_info:
            return f"Memory '{memory_id}' not found."
        current = self._memory_info[memory_id].get("version", "1.0")
        new_ver = improve_version(current, is_major)
        self._memory_info[memory_id]["version"] = new_ver
        self._versions.setdefault(memory_id, []).append(new_ver)
        kind = "major" if is_major else "minor"
        return f"Memory '{memory_id}' {kind} improved: v{current} → v{new_ver}"

    def get_version(self, memory_id: str) -> str:
        return self._memory_info.get(memory_id, {}).get("version", "1.0")

    def get_version_history(self, memory_id: str) -> List[str]:
        return self._versions.get(memory_id, [])

    def access_memory(self, memory_id: str) -> bool:
        if self._memory_states.get(memory_id) not in ("stored", "accessed", "consolidated", "archived"):
            return False
        self._memory_states[memory_id] = "accessed"
        self._memory_info[memory_id]["access_count"] += 1
        self._access_logs[memory_id].append(datetime.now().isoformat())
        return True

    def consolidate_memory(self, memory_id: str) -> bool:
        if self._memory_states.get(memory_id) not in ("stored", "accessed"):
            return False
        self._memory_states[memory_id] = "consolidated"
        self._memory_info[memory_id]["consolidated"] = datetime.now().isoformat()
        return True

    def archive_memory(self, memory_id: str) -> bool:
        if self._memory_states.get(memory_id) not in ("stored", "accessed", "consolidated"):
            return False
        self._memory_states[memory_id] = "archived"
        self._memory_info[memory_id]["archived"] = datetime.now().isoformat()
        return True

    def evict_memory(self, memory_id: str) -> bool:
        if self._memory_states.get(memory_id) not in ("stored", "accessed", "consolidated", "archived"):
            return False
        self._memory_states[memory_id] = "evicted"
        self._memory_info[memory_id]["evicted"] = datetime.now().isoformat()
        return True

    def mark_error(self, memory_id: str) -> bool:
        self._memory_states[memory_id] = "error"
        return True

    def set_importance(self, memory_id: str, importance: float):
        if memory_id in self._memory_info:
            self._memory_info[memory_id]["importance"] = max(0.0, min(1.0, importance))

    def get_memory_state(self, memory_id: str) -> Optional[str]:
        return self._memory_states.get(memory_id)

    def get_memory_info(self, memory_id: str) -> Optional[Dict[str, Any]]:
        return self._memory_info.get(memory_id)

    def get_evictable_memories(self, threshold_days: int = 90) -> List[str]:
        return [mid for mid, state in self._memory_states.items()
                if state in ("archived", "consolidated", "stored")]

    def search_by_type(self, memory_type: str) -> List[str]:
        return [mid for mid, info in self._memory_info.items() if info.get("type") == memory_type]

    def get_stats(self) -> Dict[str, Any]:
        states = {}
        for s in self._memory_states.values():
            states[s] = states.get(s, 0) + 1
        total_accesses = sum(info.get("access_count", 0) for info in self._memory_info.values())
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "total_memories": len(self._memory_states),
            "by_state": states,
            "total_accesses": total_accesses,
            "total_version_bumps": total_versions,
        }
