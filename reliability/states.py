"""Explicit, validated runtime state machine for Nexus runs and goals.

Replaces scattered booleans (``is_running``, ``failed``, ``done``) with an
explicit state machine whose transitions are validated against a table,
recorded with a reason, and optionally persisted so a restart can rebuild
the current run state.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("nexus.reliability.states")


class RunState(str, Enum):
    """Runtime states for a goal, a run, or a task.

    ``EXECUTING`` covers the model/tool loop; recovery and blocking are
    first-class states so observers can always tell *why* a run is not
    making progress.
    """

    INITIALIZING = "initializing"
    PERCEIVING = "perceiving"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    REPLANNING = "replanning"
    DEGRADED = "degraded"
    PAUSED = "paused"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    WAITING_FOR_CREDENTIALS = "waiting_for_credentials"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    BLOCKED_NON_RECOVERABLE = "blocked_non_recoverable"
    PARTIALLY_COMPLETED = "partially_completed"
    GOAL_COMPLETED = "goal_completed"
    CANCELLED_BY_USER = "cancelled_by_user"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    RETRYING = "retrying"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    OUTPUTTING = "outputting"

    # NOTE: legacy V5 value -> canonical state map lives at module level
    # (_V5_STATE_MAP). A dict declared inside an Enum class body would be
    # captured as a member by the Enum metaclass.

    @classmethod
    def from_v5(cls, v5_state: Any) -> "RunState":
        """Map a legacy V5 loop state string/enum to the canonical set."""
        if isinstance(v5_state, RunState):
            return v5_state
        value = str(getattr(v5_state, "value", v5_state)).lower()
        try:
            return cls(value)
        except ValueError:
            return _V5_STATE_MAP.get(value, cls.INITIALIZING)

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunState.GOAL_COMPLETED,
            RunState.CANCELLED_BY_USER,
            RunState.FAILED,
            RunState.TIMED_OUT,
        }

    @property
    def is_blocked(self) -> bool:
        return self in {
            RunState.BLOCKED_NON_RECOVERABLE,
            RunState.WAITING_FOR_PERMISSION,
            RunState.WAITING_FOR_CREDENTIALS,
            RunState.WAITING_FOR_DEPENDENCY,
            RunState.PAUSED,
        }


# Validated transition table. Internal observation states (OBSERVING,
# REFLECTING, OUTPUTTING) are sub-states of the surrounding phase and are
# allowed from/to the states they belong to; the table handles them as
# broadly-permitted so the loop can emit them without ceremony.
# TIMED_OUT is reachable from every active state (deadlines can fire in any
# phase); PLANNING is reachable from VERIFYING because the loop routes
# verification failures back through the planning phase.
TRANSITION_TABLE: Dict[RunState, Set[RunState]] = {
    RunState.INITIALIZING: {
        RunState.PERCEIVING, RunState.PLANNING, RunState.EXECUTING,
        RunState.OBSERVING, RunState.REFLECTING, RunState.OUTPUTTING,
        RunState.FAILED, RunState.CANCELLED_BY_USER, RunState.TIMED_OUT,
        RunState.GOAL_COMPLETED,
    },
    RunState.PERCEIVING: {
        RunState.PLANNING, RunState.EXECUTING, RunState.OBSERVING,
        RunState.REFLECTING, RunState.FAILED, RunState.TIMED_OUT,
    },
    RunState.PLANNING: {
        RunState.EXECUTING, RunState.REPLANNING, RunState.RECOVERING,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.FAILED,
        RunState.OBSERVING, RunState.REFLECTING, RunState.OUTPUTTING,
        RunState.TIMED_OUT, RunState.CANCELLED_BY_USER,
    },
    RunState.EXECUTING: {
        RunState.VERIFYING, RunState.RECOVERING, RunState.REPLANNING,
        RunState.DEGRADED, RunState.WAITING_FOR_PERMISSION,
        RunState.WAITING_FOR_CREDENTIALS, RunState.WAITING_FOR_DEPENDENCY,
        RunState.PARTIALLY_COMPLETED, RunState.BLOCKED_NON_RECOVERABLE,
        RunState.GOAL_COMPLETED, RunState.FAILED, RunState.CANCELLED_BY_USER,
        RunState.RETRYING, RunState.PAUSED, RunState.OBSERVING,
        RunState.REFLECTING, RunState.OUTPUTTING, RunState.TIMED_OUT,
    },
    RunState.VERIFYING: {
        RunState.GOAL_COMPLETED, RunState.REPLANNING, RunState.RECOVERING,
        RunState.PARTIALLY_COMPLETED, RunState.BLOCKED_NON_RECOVERABLE,
        RunState.FAILED, RunState.EXECUTING, RunState.OBSERVING,
        RunState.REFLECTING, RunState.OUTPUTTING, RunState.TIMED_OUT,
        RunState.PLANNING,
    },
    RunState.RECOVERING: {
        RunState.EXECUTING, RunState.REPLANNING, RunState.DEGRADED,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.WAITING_FOR_PERMISSION,
        RunState.WAITING_FOR_CREDENTIALS, RunState.WAITING_FOR_DEPENDENCY,
        RunState.FAILED, RunState.OBSERVING, RunState.REFLECTING,
        RunState.TIMED_OUT,
    },
    RunState.REPLANNING: {
        RunState.EXECUTING, RunState.RECOVERING,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.FAILED,
        RunState.PLANNING, RunState.OBSERVING, RunState.REFLECTING,
        RunState.TIMED_OUT, RunState.CANCELLED_BY_USER,
    },
    RunState.DEGRADED: {
        RunState.EXECUTING, RunState.RECOVERING, RunState.REPLANNING,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.FAILED,
        RunState.GOAL_COMPLETED, RunState.PARTIALLY_COMPLETED,
        RunState.PLANNING, RunState.TIMED_OUT,
    },
    RunState.RETRYING: {
        RunState.EXECUTING, RunState.RECOVERING,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.FAILED,
        RunState.REPLANNING, RunState.OBSERVING, RunState.REFLECTING,
        RunState.TIMED_OUT,
    },
    RunState.WAITING_FOR_PERMISSION: {
        RunState.EXECUTING, RunState.RECOVERING,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.CANCELLED_BY_USER,
        RunState.TIMED_OUT,
    },
    RunState.WAITING_FOR_CREDENTIALS: {
        RunState.EXECUTING, RunState.RECOVERING,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.CANCELLED_BY_USER,
        RunState.TIMED_OUT,
    },
    RunState.WAITING_FOR_DEPENDENCY: {
        RunState.EXECUTING, RunState.RECOVERING,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.CANCELLED_BY_USER,
        RunState.TIMED_OUT,
    },
    RunState.PAUSED: {
        RunState.EXECUTING, RunState.RECOVERING,
        RunState.CANCELLED_BY_USER, RunState.BLOCKED_NON_RECOVERABLE,
        RunState.TIMED_OUT,
    },
    RunState.BLOCKED_NON_RECOVERABLE: {
        RunState.EXECUTING, RunState.REPLANNING, RunState.RECOVERING,
        RunState.CANCELLED_BY_USER, RunState.TIMED_OUT,
    },
    RunState.PARTIALLY_COMPLETED: {
        RunState.EXECUTING, RunState.VERIFYING, RunState.GOAL_COMPLETED,
        RunState.BLOCKED_NON_RECOVERABLE, RunState.CANCELLED_BY_USER,
        RunState.REPLANNING, RunState.TIMED_OUT,
    },
    RunState.GOAL_COMPLETED: set(),
    RunState.CANCELLED_BY_USER: set(),
    RunState.FAILED: set(),
    RunState.TIMED_OUT: set(),
    RunState.OBSERVING: {
        RunState.EXECUTING, RunState.PLANNING, RunState.VERIFYING,
        RunState.RECOVERING, RunState.FAILED, RunState.REFLECTING,
        RunState.OUTPUTTING, RunState.REPLANNING, RunState.TIMED_OUT,
    },
    RunState.REFLECTING: {
        RunState.EXECUTING, RunState.PLANNING, RunState.VERIFYING,
        RunState.RECOVERING, RunState.FAILED, RunState.OBSERVING,
        RunState.OUTPUTTING, RunState.REPLANNING, RunState.TIMED_OUT,
    },
    RunState.OUTPUTTING: {
        RunState.GOAL_COMPLETED, RunState.PARTIALLY_COMPLETED,
        RunState.FAILED, RunState.EXECUTING, RunState.OBSERVING,
        RunState.REFLECTING, RunState.TIMED_OUT,
    },
}

RECOVERABLE_FROM = {
    RunState.RECOVERING, RunState.REPLANNING, RunState.DEGRADED,
    RunState.RETRYING, RunState.WAITING_FOR_PERMISSION,
    RunState.WAITING_FOR_CREDENTIALS, RunState.WAITING_FOR_DEPENDENCY,
    RunState.PAUSED, RunState.BLOCKED_NON_RECOVERABLE,
    RunState.PARTIALLY_COMPLETED,
}


_V5_STATE_MAP = {
    "initializing": RunState.INITIALIZING,
    "perceiving": RunState.PERCEIVING,
    "planning": RunState.PLANNING,
    "acting": RunState.EXECUTING,
    "observing": RunState.OBSERVING,
    "reflecting": RunState.REFLECTING,
    "retrying": RunState.RETRYING,
    "evolving": RunState.PLANNING,
    "conscious": RunState.PLANNING,
    "outputting": RunState.OUTPUTTING,
    "completed": RunState.GOAL_COMPLETED,
    "cancelled": RunState.CANCELLED_BY_USER,
    "timed_out": RunState.TIMED_OUT,
    "failed": RunState.FAILED,
}


@dataclass
class TransitionRecord:
    """A single validated state transition."""

    state: RunState
    previous_state: RunState
    reason: str
    timestamp: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "previous_state": self.previous_state.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "meta": self.meta,
        }


class RunStateMachine:
    """Validated, persistable state machine with recorded transitions.

    Storage failures never raise: a checkpoint-storage outage must not break
    the state machine itself (the failure is logged and the in-memory machine
    keeps running).
    """

    def __init__(
        self,
        initial: RunState = RunState.INITIALIZING,
        *,
        persist_path: Optional[str] = None,
        on_change: Optional[Callable[[RunState, RunState, str], None]] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self._state = initial
        self._history: List[TransitionRecord] = []
        self._persist_path = persist_path
        self._on_change = on_change
        self._lock = threading.Lock()
        self._clock = clock or time.time
        if persist_path:
            try:
                if os.path.exists(persist_path):
                    restored = RunStateMachine.load(persist_path)
                    self._state = restored._state
                    self._history = restored._history
            except Exception:
                logger.warning(
                    "could not resume state machine from %s; starting fresh",
                    persist_path,
                )

    @property
    def state(self) -> RunState:
        with self._lock:
            return self._state

    def can_transition(self, new: RunState) -> bool:
        with self._lock:
            allowed = TRANSITION_TABLE.get(self._state, set())
            return new in allowed or new == self._state

    def transition(
        self,
        new: RunState,
        *,
        reason: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Attempt a validated transition. Returns False (and logs) when the
        transition is invalid; no-op True when already in that state."""
        new_state = RunState.from_v5(new)
        with self._lock:
            if new_state == self._state:
                return True
            allowed = TRANSITION_TABLE.get(self._state, set())
            if new_state not in allowed:
                logger.warning(
                    "invalid state transition %s -> %s (%s); rejected",
                    self._state.value, new_state.value, reason or "no reason",
                )
                return False
            record = TransitionRecord(
                state=new_state,
                previous_state=self._state,
                reason=reason or "unspecified",
                timestamp=self._clock(),
                meta=dict(meta or {}),
            )
            self._history.append(record)
            self._state = new_state
        self._persist()
        on_change = self._on_change
        if on_change is not None:
            try:
                on_change(record.previous_state, new_state, reason)
            except Exception:
                logger.warning("state on_change callback failed", exc_info=True)
        return True

    def history(self) -> List[TransitionRecord]:
        with self._lock:
            return list(self._history)

    def _persist(self) -> None:
        path = self._persist_path
        if not path:
            return
        try:
            payload = {
                "state": self._state.value,
                "history": [record.to_dict() for record in self._history],
            }
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                prefix=".state-", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, default=str)
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
            logger.warning("could not persist state machine at %s", path, exc_info=True)

    def restore(self, state: RunState, history: List[TransitionRecord]) -> None:
        with self._lock:
            self._state = RunState.from_v5(state)
            self._history = list(history)

    @classmethod
    def load(cls, path: str, **kwargs) -> "RunStateMachine":
        """Rebuild a machine from a persisted snapshot. Tolerant of
        corruption: falls back to a fresh INITIALIZING machine."""
        machine = cls(**kwargs)
        try:
            if not os.path.exists(path):
                return machine
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            state = RunState.from_v5(payload.get("state", "initializing"))
            history = []
            for item in payload.get("history", []):
                try:
                    history.append(
                        TransitionRecord(
                            state=RunState.from_v5(item.get("state")),
                            previous_state=RunState.from_v5(item.get("previous_state")),
                            reason=str(item.get("reason") or ""),
                            timestamp=float(item.get("timestamp") or 0.0),
                            meta=dict(item.get("meta") or {}),
                        )
                    )
                except Exception:
                    continue
            machine.restore(state, history)
        except Exception:
            logger.warning("corrupt state snapshot at %s; starting fresh", path)
        return machine