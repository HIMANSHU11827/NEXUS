"""Skill lifecycle manager — tracks skills from creation through archival/deletion.

States:
  CREATED → ACTIVE ↔ STALE → ARCHIVED → DELETED
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


class SkillState(Enum):
    CREATED = "created"
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    DELETED = "deleted"
    ERROR = "error"


class SkillLifecycle(LifecycleManager):
    """Lifecycle manager for NEXUS skills with versioning."""

    def __init__(self):
        super().__init__()
        self._valid_transitions = {
            LifecycleState.CREATED: {LifecycleState.ACTIVE, LifecycleState.ERROR},
            LifecycleState.ACTIVE: {LifecycleState.STALE, LifecycleState.DELETED, LifecycleState.ERROR},
            LifecycleState.STALE: {LifecycleState.ACTIVE, LifecycleState.ARCHIVED, LifecycleState.DELETED, LifecycleState.ERROR},
            LifecycleState.ARCHIVED: {LifecycleState.ACTIVE, LifecycleState.DELETED, LifecycleState.ERROR},
            LifecycleState.DELETED: set(),
            LifecycleState.ERROR: {LifecycleState.ACTIVE, LifecycleState.DELETED},
        }
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._versions: Dict[str, List[str]] = {}

    def create_skill(self, skill_id: str, name: str, category: Optional[str] = None) -> str:
        self.register_entity(skill_id, LifecycleState.CREATED)
        self._metadata[skill_id] = {
            "name": name, "category": category, "use_count": 0, "created_by": "agent",
            "version": default_version(),
        }
        self._versions[skill_id] = [default_version()]
        return f"Skill '{name}' v{default_version()} registered in CREATED state."

    def improve_skill(self, skill_id: str, is_major: bool = False) -> str:
        """Improve skill version. Minor bump by default, major if is_major=True."""
        if skill_id not in self._metadata:
            return f"Skill '{skill_id}' not found."
        current = self._metadata[skill_id].get("version", "1.0")
        new_ver = improve_version(current, is_major)
        self._metadata[skill_id]["version"] = new_ver
        self._versions.setdefault(skill_id, []).append(new_ver)
        self.activate(skill_id)
        kind = "major" if is_major else "minor"
        return f"Skill '{self._metadata[skill_id]['name']}' {kind} improved: v{current} → v{new_ver}"

    def get_version(self, skill_id: str) -> str:
        return self._metadata.get(skill_id, {}).get("version", "1.0")

    def get_version_history(self, skill_id: str) -> List[str]:
        return self._versions.get(skill_id, [])

    def activate(self, skill_id: str) -> bool:
        return self.transition(skill_id, LifecycleState.ACTIVE)

    def mark_stale(self, skill_id: str) -> bool:
        return self.transition(skill_id, LifecycleState.STALE)

    def archive(self, skill_id: str) -> bool:
        return self.transition(skill_id, LifecycleState.ARCHIVED)

    def mark_deleted(self, skill_id: str) -> bool:
        return self.transition(skill_id, LifecycleState.DELETED)

    def mark_error(self, skill_id: str) -> bool:
        return self.transition(skill_id, LifecycleState.ERROR)

    def record_use(self, skill_id: str):
        if skill_id in self._metadata:
            self._metadata[skill_id]["use_count"] = self._metadata[skill_id].get("use_count", 0) + 1
        self.activate(skill_id)

    def get_metadata(self, skill_id: str) -> Optional[Dict[str, Any]]:
        return self._metadata.get(skill_id)

    def get_stale_skills(self, max_days: int = 30) -> List[str]:
        return [sid for sid, state in self._states.items() if state == LifecycleState.STALE]

    def get_archived_skills(self) -> List[str]:
        return [sid for sid, state in self._states.items() if state == LifecycleState.ARCHIVED]

    def get_active_skills(self) -> List[str]:
        return [sid for sid, state in self._states.items() if state == LifecycleState.ACTIVE]

    def get_stats(self) -> Dict[str, Any]:
        states = {}
        for s in self._states.values():
            states[s.name] = states.get(s.name, 0) + 1
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "total_skills": len(self._states),
            "by_state": states,
            "total_versions": total_versions,
        }
