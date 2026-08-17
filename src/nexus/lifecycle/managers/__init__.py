"""NEXUS Lifecycle Framework — state machine lifecycle managers for all subsystems.

Two layers:

1. Per-entity lifecycle managers (LifecycleState + LifecycleEvent) for skills,
   plugins, tools, cron jobs, self-improvement, and memory. Each manager
   implements a state machine with defined states, valid transitions, and
   transition hooks, and persists to ``~/.nexus/lifecycle``.

2. A component supervision layer (LifecycleStage + ComponentSupervisor) that
   tracks coarse stages (created -> initializing -> ready -> running <-> paused
   -> stopping -> stopped, plus failed/recovering/quarantined) with
   dependency-ordered startup/shutdown, timeouts, quarantine, and restart
   recovery. Use ``get_component_supervisor()`` for the shared supervisor.

Inspired by Hermes Agent's curator and plugin lifecycle patterns.
"""

import logging
from enum import Enum, auto
from typing import Any, Dict, List, Optional

from .persistence import load_state, persistence_status, save_state


class LifecycleState(Enum):
    """Base lifecycle states shared across all subsystems."""
    CREATED = auto()
    ACTIVE = auto()
    STALE = auto()
    ARCHIVED = auto()
    DELETED = auto()
    ERROR = auto()


class LifecycleEvent:
    """An event that occurred during lifecycle transitions."""

    def __init__(self, entity_type: str, entity_id: str, from_state: LifecycleState,
                 to_state: LifecycleState, metadata: Optional[Dict[str, Any]] = None):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.from_state = from_state
        self.to_state = to_state
        self.metadata = metadata or {}

    def __repr__(self) -> str:
        return (f"LifecycleEvent({self.entity_type}:{self.entity_id} "
                f"{self.from_state.name} -> {self.to_state.name})")


class LifecycleManager:
    """Base class for all lifecycle managers.

    Provides:
    - State machine with valid transitions
    - Transition hooks (pre/post callbacks)
    - Event recording and retrieval
    """

    def __init__(self):
        self._events: List[LifecycleEvent] = []
        self._states: Dict[str, LifecycleState] = {}
        self._pre_hooks: Dict[str, List] = {}
        self._post_hooks: Dict[str, List] = {}
        self._valid_transitions: Dict[LifecycleState, set] = {}
        # Subclasses opt into persistence by setting this to a stable key.
        self._persist_key: Optional[str] = None

    def register_entity(self, entity_id: str, initial_state: LifecycleState = LifecycleState.CREATED):
        """Register a new entity in the lifecycle tracker."""
        self._states[entity_id] = initial_state
        self._record_event(entity_id, None, initial_state)

    def get_state(self, entity_id: str) -> Optional[LifecycleState]:
        return self._states.get(entity_id)

    def transition(self, entity_id: str, to_state: LifecycleState, **metadata) -> bool:
        """Attempt a state transition. Returns True if successful."""
        current = self._states.get(entity_id)
        if current is None:
            return False
        if current == to_state:
            return True
        if to_state not in self._valid_transitions.get(current, set()):
            return False

        self._run_hooks("pre", entity_id, current, to_state, metadata)
        self._states[entity_id] = to_state
        self._record_event(entity_id, current, to_state, metadata)
        self._run_hooks("post", entity_id, current, to_state, metadata)
        self._persist()
        return True

    def add_pre_hook(self, transition_name: str, fn):
        self._pre_hooks.setdefault(transition_name, []).append(fn)

    def add_post_hook(self, transition_name: str, fn):
        self._post_hooks.setdefault(transition_name, []).append(fn)

    def get_events(self, entity_id: Optional[str] = None,
                   limit: int = 50) -> List[LifecycleEvent]:
        events = self._events
        if entity_id:
            events = [e for e in events if e.entity_id == entity_id]
        return events[-limit:]

    def _record_event(self, entity_id: str, from_state, to_state,
                      metadata: Optional[Dict] = None):
        event = LifecycleEvent(
            entity_type=self.__class__.__name__,
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            metadata=metadata,
        )
        self._events.append(event)

    def _run_hooks(self, hook_type: str, entity_id: str, from_state, to_state, metadata):
        key = f"{from_state.name}_to_{to_state.name}"
        hooks = (self._pre_hooks if hook_type == "pre" else self._post_hooks).get(key, [])
        for hook in hooks:
            try:
                hook(entity_id, from_state, to_state, metadata)
            except Exception:
                _logger = logging.getLogger("nexus.lifecycle")
                _logger.warning("lifecycle/__init__.py:110 _run_hooks: suppressed error", exc_info=True)

    # -- JSON persistence ---------------------------------------------------
    def _persist(self) -> None:
        """Best-effort persistence hook. Subclasses opt in via `_persist_key`."""
        if not self._persist_key:
            return
        payload = self._state_payload()
        payload.update(self._override_payload())
        save_state(self._persist_key, payload)

    def _state_payload(self) -> Dict[str, Any]:
        return {
            "states": {k: v.name for k, v in self._states.items()},
            "events": [
                {
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "from_state": e.from_state.name if e.from_state else None,
                    "to_state": e.to_state.name if e.to_state else None,
                    "metadata": e.metadata,
                }
                for e in self._events
            ],
        }

    def _override_payload(self) -> Dict[str, Any]:
        """Subclass hook: add domain dicts to the persisted payload."""
        return {}

    def _apply_override_payload(self, payload: Dict[str, Any]) -> None:
        """Subclass hook: restore domain dicts from the payload."""
        return

    def _restore_persisted(self) -> None:
        """Restore prior persisted state into this manager (best-effort)."""
        if not self._persist_key:
            return
        payload = load_state(self._persist_key)
        if not payload:
            return
        try:
            for entity_id, state_name in (payload.get("states") or {}).items():
                try:
                    self._states[entity_id] = LifecycleState[state_name]
                except (KeyError, TypeError):
                    pass
            self._events = []
            for ev in payload.get("events") or []:
                try:
                    self._events.append(
                        LifecycleEvent(
                            entity_type=ev.get("entity_type", self.__class__.__name__),
                            entity_id=ev.get("entity_id", ""),
                            from_state=LifecycleState[ev["from_state"]] if ev.get("from_state") else None,
                            to_state=LifecycleState[ev["to_state"]] if ev.get("to_state") else None,
                            metadata=ev.get("metadata") or {},
                        )
                    )
                except (KeyError, TypeError):
                    continue
            self._apply_override_payload(payload)
        except Exception:
            _logger = logging.getLogger("nexus.lifecycle")
            _logger.warning("lifecycle/__init__.py: _restore_persisted: suppressed error", exc_info=True)

    def get_stats(self) -> Dict[str, Any]:
        states = {}
        for s in self._states.values():
            states[s.name] = states.get(s.name, 0) + 1
        return {
            "total_entities": len(self._states),
            "by_state": states,
            "total_events": len(self._events),
        }


from .cron_lifecycle import CronLifecycle, CronState
from .memory_lifecycle import MemoryLifecycle, MemoryState
from .plugin_lifecycle import PluginLifecycle, PluginState
from .self_improvement_lifecycle import SelfImprovementLifecycle
from .self_improvement_lifecycle import SelfImprovementState as ImprovementState
from .skill_lifecycle import SkillLifecycle, SkillState
from .tool_lifecycle import ToolLifecycle, ToolState
from .supervisor import ComponentSupervisor, LifecycleStage, StageTransitionError, get_component_supervisor

__all__ = [
    "LifecycleState", "LifecycleEvent", "LifecycleManager",
    "SkillLifecycle", "SkillState",
    "PluginLifecycle", "PluginState",
    "ToolLifecycle", "ToolState",
    "CronLifecycle", "CronState",
    "SelfImprovementLifecycle", "ImprovementState",
    "MemoryLifecycle", "MemoryState",
    "LifecycleStage", "StageTransitionError", "ComponentSupervisor",
    "get_component_supervisor",
]
