"""Cron lifecycle manager — tracks cron tasks from scheduling through completion.

States:
  SCHEDULED → RUNNING → COMPLETED / FAILED / CANCELLED → RESCHEDULED
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


class CronState(Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"
    ERROR = "error"


class CronLifecycle(LifecycleManager):
    """Lifecycle manager for NEXUS cron tasks with versioning."""

    def __init__(self):
        super().__init__()
        self._valid_transitions = {
            LifecycleState.CREATED: {self._to_ls("scheduled"), LifecycleState.ERROR},
        }
        self._cron_transitions = {
            "scheduled": {"running", "cancelled", "error"},
            "running": {"completed", "failed", "cancelled", "error"},
            "completed": {"rescheduled", "scheduled", "archived"},
            "failed": {"rescheduled", "scheduled", "cancelled", "archived", "error"},
            "cancelled": set(),
            "rescheduled": {"scheduled", "error"},
            "error": {"scheduled", "cancelled"},
            "archived": set(),
        }
        self._cron_states: Dict[str, str] = {}
        self._cron_info: Dict[str, Dict[str, Any]] = {}
        self._executions: Dict[str, List[Dict]] = {}
        self._versions: Dict[str, List[str]] = {}

    def _to_ls(self, state_str: str) -> LifecycleState:
        mapping = {
            "scheduled": LifecycleState.CREATED,
            "running": LifecycleState.ACTIVE,
            "completed": LifecycleState.ACTIVE,
            "failed": LifecycleState.ERROR,
            "cancelled": LifecycleState.DELETED,
            "rescheduled": LifecycleState.ACTIVE,
            "error": LifecycleState.ERROR,
            "archived": LifecycleState.ARCHIVED,
        }
        return mapping.get(state_str, LifecycleState.CREATED)

    def schedule_task(self, task_id: str, name: str, cron_expr: str) -> str:
        self._cron_states[task_id] = "scheduled"
        self._cron_info[task_id] = {
            "name": name, "cron_expr": cron_expr, "runs": 0, "last_run": None,
            "version": default_version(),
        }
        self._versions[task_id] = [default_version()]
        self._executions[task_id] = []
        self.register_entity(task_id, LifecycleState.CREATED)
        return f"Cron task '{name}' v{default_version()} scheduled with '{cron_expr}'."

    def improve_task(self, task_id: str, is_major: bool = False) -> str:
        """Improve cron task version. Minor bump by default, major if is_major=True."""
        if task_id not in self._cron_info:
            return f"Cron task '{task_id}' not found."
        current = self._cron_info[task_id].get("version", "1.0")
        new_ver = improve_version(current, is_major)
        self._cron_info[task_id]["version"] = new_ver
        self._versions.setdefault(task_id, []).append(new_ver)
        kind = "major" if is_major else "minor"
        return f"Cron task '{self._cron_info[task_id]['name']}' {kind} improved: v{current} → v{new_ver}"

    def get_version(self, task_id: str) -> str:
        return self._cron_info.get(task_id, {}).get("version", "1.0")

    def get_version_history(self, task_id: str) -> List[str]:
        return self._versions.get(task_id, [])

    def run_task(self, task_id: str) -> bool:
        if self._cron_states.get(task_id) not in ("scheduled", "rescheduled"):
            return False
        self._cron_states[task_id] = "running"
        self._cron_info[task_id]["runs"] = self._cron_info[task_id].get("runs", 0) + 1
        self._cron_info[task_id]["last_run"] = datetime.now().isoformat()
        self._executions[task_id].append({"started": datetime.now().isoformat()})
        return True

    def complete_task(self, task_id: str) -> bool:
        if self._cron_states.get(task_id) != "running":
            return False
        self._cron_states[task_id] = "completed"
        if self._executions[task_id]:
            self._executions[task_id][-1]["completed"] = datetime.now().isoformat()
        return True

    def fail_task(self, task_id: str, error_msg: str = "") -> bool:
        if self._cron_states.get(task_id) != "running":
            return False
        self._cron_states[task_id] = "failed"
        if self._executions[task_id]:
            self._executions[task_id][-1]["failed"] = datetime.now().isoformat()
            self._executions[task_id][-1]["error"] = error_msg
        return True

    def cancel_task(self, task_id: str) -> bool:
        if self._cron_states.get(task_id) not in ("scheduled", "running", "failed"):
            return False
        self._cron_states[task_id] = "cancelled"
        return True

    def reschedule_task(self, task_id: str, new_expr: str) -> bool:
        if self._cron_states.get(task_id) not in ("completed", "failed"):
            return False
        self._cron_states[task_id] = "rescheduled"
        self._cron_info[task_id]["cron_expr"] = new_expr
        return True

    def mark_error(self, task_id: str) -> bool:
        self._cron_states[task_id] = "error"
        return True

    def archive(self, task_id: str) -> bool:
        if self._cron_states.get(task_id) not in ("completed", "failed"):
            return False
        self._cron_states[task_id] = "archived"
        return True

    def get_task_state(self, task_id: str) -> Optional[str]:
        return self._cron_states.get(task_id)

    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._cron_info.get(task_id)

    def get_scheduled_tasks(self) -> List[str]:
        return [tid for tid, s in self._cron_states.items() if s in ("scheduled", "rescheduled")]

    def get_stats(self) -> Dict[str, Any]:
        states = {}
        for s in self._cron_states.values():
            states[s] = states.get(s, 0) + 1
        total_runs = sum(info.get("runs", 0) for info in self._cron_info.values())
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "total_tasks": len(self._cron_states),
            "by_state": states,
            "total_runs": total_runs,
            "total_version_bumps": total_versions,
        }
