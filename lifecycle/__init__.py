"""NEXUS Lifecycle Framework — state machine lifecycle managers for all subsystems.

Provides unified lifecycle tracking for skills, plugins, tools, cron jobs,
self-improvement, and memory. Each lifecycle manager implements a state machine
with defined states, valid transitions, and transition hooks.

Inspired by Hermes Agent's curator and plugin lifecycle patterns.
"""

from enum import Enum, auto
from typing import Any, Dict, List, Optional


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
                pass

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
from .self_improvement_lifecycle import SelfImprovementLifecycle, SelfImprovementState as ImprovementState
from .skill_lifecycle import SkillLifecycle, SkillState
from .tool_lifecycle import ToolLifecycle, ToolState

__all__ = [
    "LifecycleState", "LifecycleEvent", "LifecycleManager",
    "SkillLifecycle", "SkillState",
    "PluginLifecycle", "PluginState",
    "ToolLifecycle", "ToolState",
    "CronLifecycle", "CronState",
    "SelfImprovementLifecycle", "ImprovementState",
    "MemoryLifecycle", "MemoryState",
]
