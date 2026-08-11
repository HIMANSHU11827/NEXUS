"""V5Lifecycle — lifecycle state-machine integration for the V5 loop.

Wraps the lifecycle/ framework (tool, skill, plugin, cron, memory,
self-improvement managers): register, transition, stats, events, hooks —
all duck-typed and failure-proof.
"""

from __future__ import annotations

import logging
import sys
from enum import Enum
from typing import Any, Dict, List, Tuple


logger = logging.getLogger(__name__)

# Managers whose state machines live in custom methods instead of the base
# ``LifecycleManager`` transition table. Values are ordered method chains
# (e.g. a tool must pass ``discovered -> registered -> enabled``).
_CUSTOM_PATHS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "tool": {
        "REGISTERED": ("register_tool",),
        "ACTIVE": ("register_tool", "enable_tool"),
        "DISABLED": ("disable_tool",),
        "DEPRECATED": ("deprecate_tool",),
        "ERROR": ("mark_error",),
    },
}


class V5Lifecycle:
    """Mixin giving the V5 loop access to the repo-wide lifecycle managers.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self._emit_runtime_event`` - optional async runtime event emitter
      (``event_type, title, status, *, event_id, payload``); skipped when
      absent or not callable.
    Managers are built lazily once and cached on ``self._v5_lifecycle_managers``;
    each construction is isolated so one broken subsystem never blocks the
    others. State names are resolved by name against the manager's state
    enum (base ``LifecycleState`` preferred when the name matches, since
    managers like ``SkillLifecycle`` key transition tables on base members).
    Fully guarded: never raises.
    """

    def _lifecycle_managers(self) -> Dict[str, Any]:
        """Return the lazy lifecycle manager registry, built once and cached.

        Each manager is constructed in its own try/except and skipped on
        failure. Imports are lazy (inside the method) to avoid import
        cycles with the ``orchestrators.v5`` package. Never raises.
        """
        try:
            cached = getattr(self, "_v5_lifecycle_managers", None)
            if cached is not None:
                return cached
        except Exception:
            pass
        managers: Dict[str, Any] = {}
        factories: Dict[str, Any] = {}
        try:
            from lifecycle import (
                CronLifecycle,
                MemoryLifecycle,
                PluginLifecycle,
                SelfImprovementLifecycle,
                SkillLifecycle,
                ToolLifecycle,
            )

            factories = {
                "cron": CronLifecycle,
                "tool": ToolLifecycle,
                "skill": SkillLifecycle,
                "plugin": PluginLifecycle,
                "memory": MemoryLifecycle,
                "self_improvement": SelfImprovementLifecycle,
            }
        except Exception as e:
            logger.warning(f"[V5LIFECYCLE] lifecycle framework import failed: {e}")
        for kind, factory in factories.items():
            try:
                managers[kind] = factory()
            except Exception as e:
                logger.warning(f"[V5LIFECYCLE] manager '{kind}' failed to initialize: {e}")
        try:
            self._v5_lifecycle_managers = managers
        except Exception:
            pass
        return managers

    def _lifecycle(self, kind: str):
        """Return the lifecycle manager for ``kind``, or None. Never raises."""
        try:
            return self._lifecycle_managers().get(kind)
        except Exception:
            return None

    def _lifecycle_state_enum(self, manager):
        """Resolve the state enum class a manager tracks, or None.

        Lookup order: (1) a ``STATE_ENUM`` class attribute, (2) an ``Enum``
        subclass declared on the manager class whose name contains "State",
        (3) the module-level enum named ``<Class name minus Lifecycle>State``
        (e.g. ``ToolLifecycle`` -> ``ToolState``) in the manager's module.
        Never raises.
        """
        try:
            found = getattr(manager.__class__, "STATE_ENUM", None)
            if isinstance(found, type) and issubclass(found, Enum):
                return found
            for name, value in vars(manager.__class__).items():
                if (
                    isinstance(value, type)
                    and issubclass(value, Enum)
                    and "State" in name
                ):
                    return value
            class_name = manager.__class__.__name__
            enum_name = class_name
            if enum_name.endswith("Lifecycle"):
                enum_name = enum_name[: -len("Lifecycle")] + "State"
            module = sys.modules.get(manager.__class__.__module__)
            if module is not None:
                found = getattr(module, enum_name, None)
                if isinstance(found, type) and issubclass(found, Enum):
                    return found
        except Exception:
            pass
        return None

    def _lifecycle_state_value(self, manager, state_name: str):
        """Resolve a state name string to the enum value a manager expects.

        Managers keying transition tables on the base ``LifecycleState``
        (e.g. ``SkillLifecycle``) require base members, while managers with
        custom states (e.g. ``ToolLifecycle``) use their own enum. Order:
        (1) base ``LifecycleState`` member when the name matches a base
        name, (2) the manager's own state enum member, (3) None when no
        enum resolves the name (callers then pass the raw string). Never
        raises.
        """
        try:
            from lifecycle import LifecycleState

            try:
                return LifecycleState[state_name]
            except Exception:
                pass
        except Exception:
            pass
        enum = self._lifecycle_state_enum(manager)
        if enum is None:
            return None
        try:
            return enum[state_name]
        except Exception:
            return None

    async def _lifecycle_emit(self, event_type: str, title: str, payload: Dict[str, Any]) -> None:
        """Emit a runtime event when an emitter is available; never raises."""
        emitter = getattr(self, "_emit_runtime_event", None)
        if not callable(emitter):
            return
        turn_id = getattr(self, "_current_turn_id", "") or "run"
        event_id = f"{event_type}_{turn_id}"
        try:
            await emitter(event_type, title, "done", event_id=event_id, payload=payload)
        except TypeError:
            try:
                await emitter(event_type, title, "done", payload=payload)
            except Exception:
                pass
        except Exception:
            pass

    async def _lifecycle_register(
        self, kind: str, entity_id: str, initial_state: str = "CREATED"
    ) -> bool:
        """Register an entity with a lifecycle manager; never raises.

        The initial state is resolved to the enum value the manager
        expects; when unsupported by the registration signature or not
        resolvable, the base single-argument ``register_entity`` is used
        (defaulting to ``CREATED``). Emits a ``lifecycle.registered``
        runtime event on success.
        """
        manager = self._lifecycle(kind)
        if manager is None:
            return False
        state = self._lifecycle_state_value(manager, initial_state)
        try:
            if state is None:
                manager.register_entity(entity_id)
            else:
                try:
                    manager.register_entity(entity_id, state)
                except TypeError:
                    manager.register_entity(entity_id)
        except Exception as e:
            logger.warning(
                f"[V5LIFECYCLE] register '{kind}/{entity_id}' failed: {e}"
            )
            return False
        await self._lifecycle_emit(
            "lifecycle.registered",
            f"Lifecycle {kind} registered: {entity_id}",
            {"kind": kind, "entity_id": entity_id},
        )
        return True

    async def _lifecycle_transition(
        self, kind: str, entity_id: str, to_state: str, **metadata
    ) -> bool:
        """Attempt a lifecycle transition for an entity; never raises.

        The target state is resolved to the enum value the manager expects
        (raw string passed when unresolvable). Returns False when the
        manager is absent, the entity is unregistered, the transition is
        invalid, or anything fails. Emits a ``lifecycle.transition``
        runtime event on success.
        """
        manager = self._lifecycle(kind)
        if manager is None:
            return False
        try:
            if manager.get_state(entity_id) is None:
                return False
        except Exception as e:
            logger.warning(
                f"[V5LIFECYCLE] get_state failed for '{kind}/{entity_id}': {e}"
            )
            return False
        state = self._lifecycle_state_value(manager, to_state)
        if state is None:
            state = to_state
        try:
            ok = bool(manager.transition(entity_id, state, **metadata))
        except Exception as e:
            logger.warning(
                f"[V5LIFECYCLE] transition '{kind}/{entity_id}' to "
                f"'{to_state}' failed: {e}"
            )
            return False
        if ok:
            await self._lifecycle_emit(
                "lifecycle.transition",
                f"Lifecycle {kind} {entity_id} -> {to_state}",
                {"kind": kind, "entity_id": entity_id, "to_state": to_state},
            )
        return ok

    def _lifecycle_stats(self) -> Dict[str, Any]:
        """Return per-kind ``get_stats()`` for every available manager.

        A failing manager contributes an empty dict. Never raises.
        """
        stats: Dict[str, Any] = {}
        for kind, manager in self._lifecycle_managers().items():
            try:
                stats[kind] = manager.get_stats()
            except Exception:
                stats[kind] = {}
        return stats

    def _lifecycle_events(self, kind: str, entity_id: str = "", limit: int = 50) -> List[Any]:
        """Return recent lifecycle events for a kind, optionally per entity.

        Returns [] when the manager is absent or fails. Never raises.
        """
        manager = self._lifecycle(kind)
        if manager is None:
            return []
        try:
            return manager.get_events(entity_id or None, limit)
        except Exception:
            return []

    async def _lifecycle_mark(
        self, kind: str, entity_id: str, to_state: str, **metadata
    ) -> bool:
        """Register an entity if needed, then transition it; never raises.

        Convenience for call sites that just want "ensure tracked, then move
        to a state": registers when the manager has no state for the entity,
        then delegates to ``_lifecycle_transition``. Returns False on any
        failure.

        Managers whose state machine lives in custom methods (e.g.
        ``ToolLifecycle`` — no base ``_valid_transitions``) are driven
        through ``_CUSTOM_TRANSITIONS`` instead of the base transition.
        """
        manager = self._lifecycle(kind)
        if manager is None:
            return False
        custom = _CUSTOM_PATHS.get(kind)
        if custom:
            return await self._lifecycle_custom_mark(
                manager, kind, entity_id, to_state, custom, metadata
            )
        registered = False
        try:
            registered = manager.get_state(entity_id) is not None
        except Exception:
            registered = False
        if not registered:
            if not await self._lifecycle_register(kind, entity_id):
                return False
        return await self._lifecycle_transition(kind, entity_id, to_state, **metadata)

    async def _lifecycle_custom_mark(
        self, manager, kind: str, entity_id: str, to_state: str,
        paths: Dict[str, Tuple[str, ...]], metadata: Dict[str, Any],
    ) -> bool:
        """Drive a custom-state lifecycle manager via its own methods.

        Each path is an ordered chain (precondition steps first); the last
        call decides success. Steps that return False (precondition not yet
        met by an earlier step) are tolerated, and ``discover_tool`` seeds
        the chain when the entity is untracked. Never raises.
        """
        try:
            state_getter = getattr(manager, "get_tool_state", None)
            current = None
            if callable(state_getter):
                current = state_getter(entity_id)
            if not current:
                register_method = getattr(manager, "discover_tool", None)
                if callable(register_method):
                    name = str(metadata.get("tool") or metadata.get("name") or entity_id)
                    register_method(entity_id, name)
                else:
                    manager.register_entity(entity_id)
            path = paths.get(to_state)
            if not path:
                return False
            ok = False
            for method_name in path:
                method = getattr(manager, method_name, None)
                if not callable(method):
                    continue
                ok = bool(method(entity_id))
            if ok:
                await self._lifecycle_emit(
                    "lifecycle.transition",
                    f"Lifecycle {kind} {entity_id} -> {to_state}",
                    {"kind": kind, "entity_id": entity_id, "to_state": to_state},
                )
            return ok
        except Exception as e:
            logger.warning(
                f"[V5LIFECYCLE] custom transition '{kind}/{entity_id}' to "
                f"'{to_state}' failed: {e}"
            )
            return False

    def _lifecycle_hooks(self, kind: str, transition_name: str, hook: Any, pre: bool = True) -> bool:
        """Register a pre/post transition hook on a lifecycle manager.

        Returns False when the manager is absent, the hook method is
        missing, or registration fails. Never raises.
        """
        manager = self._lifecycle(kind)
        if manager is None:
            return False
        try:
            method = manager.add_pre_hook if pre else manager.add_post_hook
            if not callable(method):
                return False
            method(transition_name, hook)
            return True
        except Exception:
            return False
