"""Durable goal model for Nexus.

A goal is the unit of persistence: the user request, the parsed objective,
constraints, definition of done, verification criteria, the plan with step
statuses, blockers, recovery history, and completion evidence. A recovery
subtask is a child goal; the original goal is never replaced by the current
error.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from reliability.states import RunState

logger = logging.getLogger("nexus.reliability.goal")

_TERMINAL_STATES = {
    RunState.GOAL_COMPLETED,
    RunState.FAILED,
    RunState.CANCELLED_BY_USER,
    RunState.TIMED_OUT,
}


def _as_record(item: Any) -> Dict[str, Any]:
    """Normalize a history/blocker entry; tolerate non-dict values."""
    if isinstance(item, dict):
        return dict(item)
    return {"reason": str(item)}


@dataclass
class GoalStep:
    """A single plan step with durable status and evidence."""

    id: str
    description: str
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending|active|completed|failed|blocked|cancelled
    evidence: List[str] = field(default_factory=list)
    attempts: int = 0
    error: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "tool": self.tool,
            "params": self.params,
            "status": self.status,
            "evidence": list(self.evidence),
            "attempts": self.attempts,
            "error": self.error,
            "artifacts": list(self.artifacts),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoalStep":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            description=str(data.get("description") or ""),
            tool=data.get("tool"),
            params=dict(data.get("params") or {}),
            status=str(data.get("status") or "pending"),
            evidence=[str(item) for item in (data.get("evidence") or [])],
            attempts=int(data.get("attempts") or 0),
            error=data.get("error"),
            artifacts=[str(item) for item in (data.get("artifacts") or [])],
        )


@dataclass
class GoalState:
    """Complete durable state of one goal."""

    goal_id: str
    user_request: str
    parsed_objective: str = ""
    parent_goal_id: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    definition_of_done: str = ""
    verification_criteria: List[str] = field(default_factory=list)
    plan: List[GoalStep] = field(default_factory=list)
    plan_version: int = 1
    status: RunState = RunState.INITIALIZING
    completed_steps: int = 0
    active_steps: int = 0
    pending_steps: int = 0
    blocked_steps: int = 0
    failed_steps: int = 0
    artifacts: Dict[str, str] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    retry_history: List[Dict[str, Any]] = field(default_factory=list)
    recovery_history: List[Dict[str, Any]] = field(default_factory=list)
    checkpoint_history: List[str] = field(default_factory=list)
    agents: List[str] = field(default_factory=list)
    blockers: List[Dict[str, Any]] = field(default_factory=list)
    last_progress_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completion_evidence: List[str] = field(default_factory=list)
    version: int = 1

    def recount_steps(self) -> None:
        """Recompute the step counters from the plan."""
        counts = {"completed": 0, "active": 0, "pending": 0, "blocked": 0, "failed": 0}
        for step in self.plan:
            key = step.status if step.status in counts else "pending"
            counts[key] += 1
        self.completed_steps = counts["completed"]
        self.active_steps = counts["active"]
        self.pending_steps = counts["pending"]
        self.blocked_steps = counts["blocked"]
        self.failed_steps = counts["failed"]

    def touch(self, *, progress: bool = False) -> None:
        now = time.time()
        self.updated_at = now
        if progress:
            self.last_progress_at = now
        self.version += 1

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATES

    def to_dict(self) -> Dict[str, Any]:
        self.recount_steps()
        return {
            "goal_id": self.goal_id,
            "parent_goal_id": self.parent_goal_id,
            "user_request": self.user_request,
            "parsed_objective": self.parsed_objective,
            "constraints": list(self.constraints),
            "definition_of_done": self.definition_of_done,
            "verification_criteria": list(self.verification_criteria),
            "plan": [step.to_dict() for step in self.plan],
            "plan_version": self.plan_version,
            "status": self.status.value,
            "completed_steps": self.completed_steps,
            "active_steps": self.active_steps,
            "pending_steps": self.pending_steps,
            "blocked_steps": self.blocked_steps,
            "failed_steps": self.failed_steps,
            "artifacts": dict(self.artifacts),
            "evidence": list(self.evidence),
            "decisions": list(self.decisions),
            "assumptions": list(self.assumptions),
            "retry_history": list(self.retry_history),
            "recovery_history": list(self.recovery_history),
            "checkpoint_history": list(self.checkpoint_history),
            "agents": list(self.agents),
            "blockers": list(self.blockers),
            "last_progress_at": self.last_progress_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completion_evidence": list(self.completion_evidence),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoalState":
        try:
            status = RunState(str(data.get("status") or "initializing"))
        except ValueError:
            status = RunState.INITIALIZING
        goal = cls(
            goal_id=str(data.get("goal_id") or uuid.uuid4().hex[:12]),
            parent_goal_id=data.get("parent_goal_id"),
            user_request=str(data.get("user_request") or ""),
            parsed_objective=str(data.get("parsed_objective") or ""),
            constraints=[str(item) for item in (data.get("constraints") or [])],
            definition_of_done=str(data.get("definition_of_done") or ""),
            verification_criteria=[
                str(item) for item in (data.get("verification_criteria") or [])
            ],
            plan=[GoalStep.from_dict(item) for item in (data.get("plan") or [])],
            plan_version=int(data.get("plan_version") or 1),
            status=status,
            artifacts=dict(data.get("artifacts") or {}),
            evidence=[str(item) for item in (data.get("evidence") or [])],
            decisions=[str(item) for item in (data.get("decisions") or [])],
            assumptions=[str(item) for item in (data.get("assumptions") or [])],
            retry_history=[_as_record(item) for item in (data.get("retry_history") or [])],
            recovery_history=[
                _as_record(item) for item in (data.get("recovery_history") or [])
            ],
            checkpoint_history=[
                str(item) for item in (data.get("checkpoint_history") or [])
            ],
            agents=[str(item) for item in (data.get("agents") or [])],
            blockers=[_as_record(item) for item in (data.get("blockers") or [])],
            last_progress_at=float(data.get("last_progress_at") or time.time()),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            completion_evidence=[
                str(item) for item in (data.get("completion_evidence") or [])
            ],
            version=int(data.get("version") or 1),
        )
        goal.recount_steps()
        return goal

    @classmethod
    def create(
        cls,
        user_request: str,
        *,
        goal_id: Optional[str] = None,
        parent_goal_id: Optional[str] = None,
    ) -> "GoalState":
        return cls(
            goal_id=goal_id or f"goal_{uuid.uuid4().hex[:12]}",
            parent_goal_id=parent_goal_id,
            user_request=user_request,
            parsed_objective=user_request,
        )


class GoalStore:
    """Atomic JSON persistence for goals under a root directory.

    Every method is failure-tolerant: storage errors are logged and never
    raised, because losing the goal file must not crash the runtime that is
    trying to recover.
    """

    def __init__(self, root_dir: str = ".nexus/v5/goals"):
        self._root_dir = root_dir

    def _path(self, goal_id: str) -> str:
        safe = "".join(
            char for char in str(goal_id) if char.isalnum() or char in "-_"
        )
        return os.path.join(self._root_dir, f"{safe}.json")

    def save(self, goal: GoalState) -> None:
        """Atomically persist a goal (temp file + os.replace)."""
        try:
            os.makedirs(self._root_dir, exist_ok=True)
            path = self._path(goal.goal_id)
            fd, temp_path = tempfile.mkstemp(
                prefix=".goal-", suffix=".tmp", dir=self._root_dir
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(goal.to_dict(), handle, default=str, indent=1)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, path)
            except Exception:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
        except Exception:
            logger.warning("could not save goal %s", goal.goal_id, exc_info=True)

    def load(self, goal_id: str) -> Optional[GoalState]:
        try:
            path = self._path(goal_id)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as handle:
                return GoalState.from_dict(json.load(handle))
        except Exception:
            logger.warning("could not load goal %s", goal_id, exc_info=True)
            return None

    def update(
        self, goal_id: str, mutator: Callable[[GoalState], None]
    ) -> Optional[GoalState]:
        """Load, mutate, bump version, and persist atomically."""
        goal = self.load(goal_id)
        if goal is None:
            return None
        try:
            mutator(goal)
        except Exception:
            logger.warning("goal mutator failed for %s", goal_id, exc_info=True)
            return None
        goal.touch()
        self.save(goal)
        return goal

    def list_active(self) -> List[GoalState]:
        """All goals not in a terminal state (blocked goals are active:
        they are resumable)."""
        goals: List[GoalState] = []
        try:
            if not os.path.isdir(self._root_dir):
                return goals
            for filename in os.listdir(self._root_dir):
                if not filename.endswith(".json"):
                    continue
                goal = self.load(filename[:-5])
                if goal is not None and not goal.is_terminal():
                    goals.append(goal)
        except Exception:
            logger.warning("could not list goals", exc_info=True)
        return goals

    def active_goal_ids(self) -> List[str]:
        return [goal.goal_id for goal in self.list_active()]

    def delete(self, goal_id: str) -> None:
        try:
            path = self._path(goal_id)
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            logger.warning("could not delete goal %s", goal_id, exc_info=True)

    def record_recovery(
        self,
        goal_id: str,
        *,
        failure_id: str,
        strategy: str,
        verdict: str,
        detail: str,
        attempt_count: int,
    ) -> None:
        """Append a recovery operation to the goal's durable history."""
        self.update(
            goal_id,
            lambda goal: goal.recovery_history.append(
                {
                    "failure_id": failure_id,
                    "strategy": strategy,
                    "verdict": verdict,
                    "detail": detail,
                    "attempt_count": attempt_count,
                    "timestamp": time.time(),
                }
            ),
        )

    def record_blocker(
        self, goal_id: str, *, failure_id: str, reason: str, next_action: str
    ) -> None:
        self.update(
            goal_id,
            lambda goal: goal.blockers.append(
                {
                    "failure_id": failure_id,
                    "reason": reason,
                    "next_action": next_action,
                    "timestamp": time.time(),
                }
            ),
        )