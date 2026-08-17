"""Self-improvement lifecycle manager — tracks improvement cycles from analysis through integration.

States:
  IDLE → ANALYZING → LEARNING → APPLYING → EVALUATING → INTEGRATED
  Any state → ERROR / ROLLED_BACK / CANCELLED

Versioning:
  Default: 1.0
  improve (minor): 1.0 → 1.1 → 1.2
  major_upgrade:    1.x → 2.0 → 2.1 → 3.0
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from . import LifecycleManager, LifecycleState
from .version import default_version, improve_version


class SelfImprovementState(Enum):
    IDLE = "idle"
    ANALYZING = "analyzing"
    LEARNING = "learning"
    APPLYING = "applying"
    EVALUATING = "evaluating"
    INTEGRATED = "integrated"
    ERROR = "error"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class SelfImprovementLifecycle(LifecycleManager):
    """Lifecycle manager for NEXUS self-improvement cycles with versioning."""

    def __init__(self):
        super().__init__()
        self._valid_transitions = {
            LifecycleState.CREATED: {self._to_ls("analyzing"), LifecycleState.ERROR},
        }
        self._improvement_transitions = {
            "idle": {"analyzing", "cancelled"},
            "analyzing": {"learning", "idle", "cancelled", "error"},
            "learning": {"applying", "idle", "cancelled", "error"},
            "applying": {"evaluating", "rolled_back", "error"},
            "evaluating": {"integrated", "analyzing", "idle", "rolled_back", "error"},
            "integrated": {"idle", "analyzing"},
            "error": {"idle", "applying", "cancelled"},
            "rolled_back": {"idle", "analyzing"},
            "cancelled": set(),
        }
        self._cycle_states: Dict[str, str] = {}
        self._cycle_info: Dict[str, Dict[str, Any]] = {}
        self._versions: Dict[str, List[str]] = {}
        self._cycle_counter = 0
        self._persist_key = "self_improvement"
        self._restore_persisted()

    def _to_ls(self, state_str: str) -> LifecycleState:
        mapping = {
            "idle": LifecycleState.CREATED,
            "analyzing": LifecycleState.ACTIVE,
            "learning": LifecycleState.ACTIVE,
            "applying": LifecycleState.ACTIVE,
            "evaluating": LifecycleState.ACTIVE,
            "integrated": LifecycleState.ACTIVE,
            "error": LifecycleState.ERROR,
            "rolled_back": LifecycleState.ARCHIVED,
            "cancelled": LifecycleState.DELETED,
        }
        return mapping.get(state_str, LifecycleState.CREATED)

    def start_cycle(self, description: str) -> str:
        self._cycle_counter += 1
        cycle_id = f"cycle_{self._cycle_counter}"
        self._cycle_states[cycle_id] = "idle"
        self._cycle_info[cycle_id] = {
            "description": description,
            "started": datetime.now().isoformat(),
            "module": None, "changes": [], "score": None,
            "version": default_version(),
        }
        self._versions[cycle_id] = [default_version()]
        self.register_entity(cycle_id, LifecycleState.CREATED)
        self._persist()
        return cycle_id

    def improve_cycle(self, cycle_id: str, is_major: bool = False) -> str:
        """Improve cycle version. Minor bump by default, major if is_major=True."""
        if cycle_id not in self._cycle_info:
            return f"Cycle '{cycle_id}' not found."
        current = self._cycle_info[cycle_id].get("version", "1.0")
        new_ver = improve_version(current, is_major)
        self._cycle_info[cycle_id]["version"] = new_ver
        self._versions.setdefault(cycle_id, []).append(new_ver)
        kind = "major" if is_major else "minor"
        self._persist()
        return f"Cycle '{cycle_id}' {kind} improved: v{current} → v{new_ver}"

    def get_version(self, cycle_id: str) -> str:
        return self._cycle_info.get(cycle_id, {}).get("version", "1.0")

    def get_version_history(self, cycle_id: str) -> List[str]:
        return self._versions.get(cycle_id, [])

    def analyze(self, cycle_id: str) -> bool:
        if self._cycle_states.get(cycle_id) not in ("idle",):
            return False
        self._cycle_states[cycle_id] = "analyzing"
        self._cycle_info[cycle_id]["stage"] = "analyzing"
        self._persist()
        return True

    def learn(self, cycle_id: str) -> bool:
        if self._cycle_states.get(cycle_id) != "analyzing":
            return False
        self._cycle_states[cycle_id] = "learning"
        self._cycle_info[cycle_id]["stage"] = "learning"
        self._persist()
        return True

    def apply(self, cycle_id: str, changes: List[str]) -> bool:
        if self._cycle_states.get(cycle_id) != "learning":
            return False
        self._cycle_states[cycle_id] = "applying"
        self._cycle_info[cycle_id]["stage"] = "applying"
        self._cycle_info[cycle_id]["changes"] = changes
        self._persist()
        return True

    def evaluate(self, cycle_id: str, score: float) -> bool:
        if self._cycle_states.get(cycle_id) != "applying":
            return False
        self._cycle_states[cycle_id] = "evaluating"
        self._cycle_info[cycle_id]["stage"] = "evaluating"
        self._cycle_info[cycle_id]["score"] = score
        self._persist()
        return True

    def integrate(self, cycle_id: str) -> bool:
        if self._cycle_states.get(cycle_id) != "evaluating":
            return False
        self._cycle_states[cycle_id] = "integrated"
        self._cycle_info[cycle_id]["stage"] = "integrated"
        self._cycle_info[cycle_id]["integrated"] = datetime.now().isoformat()
        self._persist()
        return True

    def rollback(self, cycle_id: str) -> bool:
        if self._cycle_states.get(cycle_id) not in ("applying", "evaluating"):
            return False
        self._cycle_states[cycle_id] = "rolled_back"
        self._cycle_info[cycle_id]["stage"] = "rolled_back"
        self._persist()
        return True

    def cancel(self, cycle_id: str) -> bool:
        if self._cycle_states.get(cycle_id) in ("integrated", "cancelled", "rolled_back"):
            return False
        self._cycle_states[cycle_id] = "cancelled"
        self._cycle_info[cycle_id]["stage"] = "cancelled"
        self._persist()
        return True

    def mark_error(self, cycle_id: str) -> bool:
        self._cycle_states[cycle_id] = "error"
        self._cycle_info[cycle_id]["stage"] = "error"
        self._persist()
        return True

    def get_cycle_state(self, cycle_id: str) -> Optional[str]:
        return self._cycle_states.get(cycle_id)

    def get_cycle_info(self, cycle_id: str) -> Optional[Dict[str, Any]]:
        return self._cycle_info.get(cycle_id)

    def get_active_cycles(self) -> List[str]:
        active_states = {"analyzing", "learning", "applying", "evaluating"}
        return [cid for cid, s in self._cycle_states.items() if s in active_states]

    def _override_payload(self) -> Dict[str, Any]:
        return {
            "cycle_states": self._cycle_states,
            "cycle_info": self._cycle_info,
            "versions": self._versions,
            "cycle_counter": self._cycle_counter,
        }

    def _apply_override_payload(self, payload: Dict[str, Any]) -> None:
        self._cycle_states = payload.get("cycle_states", {}) or {}
        self._cycle_info = payload.get("cycle_info", {}) or {}
        self._versions = payload.get("versions", {}) or {}
        counter = payload.get("cycle_counter")
        if counter is not None:
            self._cycle_counter = int(counter)

    def get_stats(self) -> Dict[str, Any]:
        states = {}
        for s in self._cycle_states.values():
            states[s] = states.get(s, 0) + 1
        integrated = sum(1 for info in self._cycle_info.values() if info.get("stage") == "integrated")
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "total_cycles": len(self._cycle_states),
            "by_state": states,
            "integrated_count": integrated,
            "total_version_bumps": total_versions,
        }
