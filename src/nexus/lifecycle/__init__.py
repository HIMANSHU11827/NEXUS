"""Authoritative component lifecycle contracts.

Defines the lifecycle states an executable component moves through and the
operations that drive transitions. Components declare their state via
``LifecycleState``; the ``LifecycleManager`` enforces legal transitions and
records failures. This is the single lifecycle model - there is no second,
competing lifecycle manager elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class LifecycleState(str, Enum):
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    COMPATIBILITY_CHECKED = "compatibility_checked"
    DEPENDENCIES_RESOLVED = "dependencies_resolved"
    INSTALLED = "installed"
    CONFIGURED = "configured"
    REGISTERED = "registered"
    ENABLED = "enabled"
    STARTING = "starting"
    RUNNING = "running"
    HEALTHY = "healthy"
    DISABLED = "disabled"
    PAUSED = "paused"
    DEGRADED = "degraded"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    UPDATING = "updating"
    MIGRATING = "migrating"
    ROLLING_BACK = "rolling_back"
    STOPPING = "stopping"
    STOPPED = "stopped"
    UNINSTALLING = "uninstalling"
    UNINSTALLED = "uninstalled"


class LifecycleOperation(str, Enum):
    DISCOVER = "discover"
    VALIDATE = "validate"
    CHECK_COMPATIBILITY = "check_compatibility"
    RESOLVE_DEPENDENCIES = "resolve_dependencies"
    INSTALL = "install"
    CONFIGURE = "configure"
    REGISTER = "register"
    ENABLE = "enable"
    START = "start"
    HEALTH_CHECK = "health_check"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    RESTART = "restart"
    DISABLE = "disable"
    UPDATE = "update"
    MIGRATE = "migrate"
    REPAIR = "repair"
    ROLLBACK = "rollback"
    QUARANTINE = "quarantine"
    UNINSTALL = "uninstall"


# Happy-path ordering. Higher ordinal = further along. Forward (>=) moves along
# the path are legal, which lets non-executable components (skills, etc.) skip
# install/configure/start stages while still enforcing monotonic progress.
_HAPPY_PATH: List[LifecycleState] = [
    LifecycleState.DISCOVERED,
    LifecycleState.VALIDATED,
    LifecycleState.COMPATIBILITY_CHECKED,
    LifecycleState.DEPENDENCIES_RESOLVED,
    LifecycleState.INSTALLED,
    LifecycleState.CONFIGURED,
    LifecycleState.REGISTERED,
    LifecycleState.ENABLED,
    LifecycleState.STARTING,
    LifecycleState.RUNNING,
    LifecycleState.HEALTHY,
]
_ORDINAL = {s: i for i, s in enumerate(_HAPPY_PATH)}

# Explicit deviation edges that are NOT simple forward happy-path moves.
_DEVIATION_EDGES: Set[tuple] = {
    # runtime deviations
    ("running", "degraded"), ("healthy", "degraded"), ("degraded", "healthy"),
    ("healthy", "paused"), ("running", "paused"), ("paused", "running"),
    ("enabled", "disabled"), ("disabled", "enabled"),
    ("running", "stopping"), ("degraded", "stopping"), ("paused", "stopping"),
    ("stopping", "stopped"), ("stopped", "registered"), ("stopped", "uninstalling"),
    # failure & recovery
    ("running", "failed"), ("starting", "failed"), ("healthy", "failed"),
    ("failed", "running"), ("failed", "stopped"), ("failed", "quarantined"),
    # maintenance
    ("running", "updating"), ("updating", "running"),
    ("running", "migrating"), ("migrating", "running"),
    ("running", "rolling_back"), ("rolling_back", "running"),
    ("uninstalling", "uninstalled"),
}


@dataclass
class LifecycleRecord:
    id: str
    state: LifecycleState = LifecycleState.DISCOVERED
    history: List[str] = field(default_factory=list)
    error: Optional[str] = None
    retries: int = 0


class LifecycleStateMachine:
    def can_transition(self, source: LifecycleState, target: LifecycleState) -> bool:
        if source == target:
            return True
        # Explicit deviation edges always allowed.
        if (source.value, target.value) in _DEVIATION_EDGES:
            return True
        # Forward (or same-stage) moves along the happy path are allowed so that
        # components may skip optional executable stages (e.g. skills go
        # validated -> registered). Backward happy-path moves are rejected.
        so, to = _ORDINAL.get(source), _ORDINAL.get(target)
        if so is not None and to is not None:
            return to >= so
        return False

    def transition(self, source: LifecycleState, target: LifecycleState) -> None:
        if not self.can_transition(source, target):
            raise ValueError(
                f"Illegal lifecycle transition {source.value} -> {target.value}"
            )


class LifecycleManager:
    """Authoritative lifecycle coordinator for all executable components."""

    def __init__(self) -> None:
        self._fsm = LifecycleStateMachine()
        self._records: Dict[str, LifecycleRecord] = {}

    def track(self, component_id: str,
              initial: LifecycleState = LifecycleState.DISCOVERED) -> LifecycleRecord:
        rec = self._records.get(component_id)
        if rec is None:
            rec = LifecycleRecord(id=component_id, state=initial)
            self._records[component_id] = rec
        return rec

    def get(self, component_id: str) -> Optional[LifecycleRecord]:
        return self._records.get(component_id)

    def transition(self, component_id: str, target: LifecycleState,
                   error: Optional[str] = None, max_retries: int = 3) -> LifecycleRecord:
        rec = self.track(component_id)
        if not self._fsm.can_transition(rec.state, target):
            # allow bounded retries on failure recovery
            if target == LifecycleState.RUNNING and rec.retries < max_retries:
                rec.retries += 1
                rec.history.append(f"retry->{target.value}({rec.retries})")
                rec.state = target
                return rec
            raise ValueError(
                f"Illegal lifecycle transition for {component_id!r}: "
                f"{rec.state.value} -> {target.value}"
            )
        rec.state = target
        rec.history.append(target.value)
        rec.error = error
        if target in (LifecycleState.FAILED,):
            rec.error = error or rec.error
        else:
            rec.error = None
        return rec

    def mark_failed(self, component_id: str, error: str) -> LifecycleRecord:
        return self.transition(component_id, LifecycleState.FAILED, error=error)

    def is_healthy(self, component_id: str) -> bool:
        rec = self._records.get(component_id)
        return rec is not None and rec.state in (
            LifecycleState.RUNNING, LifecycleState.HEALTHY
        )

    @property
    def states(self) -> Dict[str, str]:
        return {i: r.state.value for i, r in self._records.items()}
