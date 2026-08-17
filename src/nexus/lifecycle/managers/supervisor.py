"""Component supervisor — an explicit stage machine on top of the per-entity
lifecycle managers, with dependency-ordered startup/shutdown, per-component
timeouts, failure quarantine, restart recovery, and JSON persistence.

The per-entity LifecycleManagers in this package track *entities* (skills,
tools, plugins, cron jobs, self-improvement cycles, memories) through their own
domain state machines. The ComponentSupervisor tracks *components* (database,
cache, workers, agents, ...) through one coarse lifecycle:

    created -> initializing -> ready -> running <-> paused
    ready/running/paused -> stopping -> stopped
    failed/quarantined -> recovering -> ready      (restart recovery)
    start failure x MAX_START_FAILURES -> quarantined

Stage transitions are validated against STAGE_TRANSITIONS: an illegal
transition is rejected with a reason, so no ghost states are possible.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import deque
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional

from .persistence import load_state, persistence_status, save_state

logger = logging.getLogger("nexus.lifecycle.supervisor")

# Stop trusting a component after this many consecutive start failures.
MAX_START_FAILURES = 3
# Default per-component recovery cooldown (seconds) used by restart() with checks.
DEFAULT_COOLDOWN = 5.0
# Default timeout (seconds) applied to async startup/shutdown calls.
DEFAULT_TIMEOUT = 10.0
# Keep only the newest history entries per component (memory + persisted file).
MAX_HISTORY = 100


class LifecycleStage(Enum):
    """Coarse supervision stages shared by all NEXUS components."""
    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    QUARANTINED = "quarantined"


# Legal stage transitions. Keys are the ``from`` stage; values are the set of
# legal ``to`` stages. Any other pair is rejected by mark_stage().
STAGE_TRANSITIONS: Dict[LifecycleStage, set] = {
    LifecycleStage.CREATED: {LifecycleStage.INITIALIZING, LifecycleStage.FAILED},
    LifecycleStage.INITIALIZING: {LifecycleStage.READY, LifecycleStage.STOPPING, LifecycleStage.FAILED},
    LifecycleStage.READY: {LifecycleStage.RUNNING, LifecycleStage.PAUSED, LifecycleStage.STOPPING, LifecycleStage.FAILED},
    LifecycleStage.RUNNING: {LifecycleStage.READY, LifecycleStage.PAUSED, LifecycleStage.STOPPING, LifecycleStage.RECOVERING, LifecycleStage.FAILED},
    LifecycleStage.PAUSED: {LifecycleStage.READY, LifecycleStage.RUNNING, LifecycleStage.STOPPING, LifecycleStage.FAILED},
    LifecycleStage.RECOVERING: {LifecycleStage.READY, LifecycleStage.RUNNING, LifecycleStage.STOPPING, LifecycleStage.FAILED},
    LifecycleStage.STOPPING: {LifecycleStage.STOPPED, LifecycleStage.FAILED},
    LifecycleStage.STOPPED: {LifecycleStage.INITIALIZING, LifecycleStage.FAILED},
    LifecycleStage.FAILED: {LifecycleStage.RECOVERING, LifecycleStage.QUARANTINED, LifecycleStage.INITIALIZING, LifecycleStage.STOPPING},
    LifecycleStage.QUARANTINED: {LifecycleStage.RECOVERING, LifecycleStage.STOPPING},
}


class StageTransitionError(Exception):
    """Raised when a stage transition is illegal or the component is unknown."""

    def __init__(self, component_id: Optional[str], from_stage, to_stage, reason: str):
        super().__init__(reason)
        self.component_id = component_id
        self.from_stage = from_stage
        self.to_stage = to_stage


def _now_iso() -> str:
    return datetime.now().isoformat()


class ComponentSupervisor:
    """Tracks the coarse lifecycle of many components at once.

    Register components up-front (or let startup() auto-register from the
    supplied specs), then move them through LifecycleStage transitions. Every
    transition is validated; illegal ones raise StageTransitionError with a
    reason (see try_mark_stage() for a non-raising form).

    ``startup``/``shutdown`` respect declared ``after=`` dependencies, time
    each step, and continue past a failing component so one bad actor never
    blocks the rest. A component that fails to start ``MAX_START_FAILURES``
    times is quarantined until an explicit ``restart`` recovers it.

    Persistence is on by default under ``~/.nexus/lifecycle/supervisor.json``
    so a process restart restores the last-known stages. Pass ``persist=False``
    (or a custom ``persist_key``) for isolated/embedded use.
    """

    def __init__(self, persist_key: Optional[str] = "supervisor", persist: bool = True):
        self._persist_key = persist_key if persist else None
        self._components: Dict[str, Dict[str, Any]] = {}
        self._restore_persisted()

    # -- registry ----------------------------------------------------------
    def register(self, component_id: str, name: Optional[str] = None,
                 after: Optional[list] = None, cooldown: float = DEFAULT_COOLDOWN):
        """Register (or refresh) a supervised component.

        Re-registering an existing component preserves its current stage and
        its fail/restart counters; only the descriptive fields are updated.
        Returns self for chaining.
        """
        after = list(after or [])
        existing = self._components.get(component_id)
        if existing is not None:
            existing["name"] = name or existing.get("name") or component_id
            existing["after"] = after
            existing["cooldown"] = cooldown
            self._persist()
            return self
        self._components[component_id] = {
            "name": name or component_id,
            "stage": LifecycleStage.CREATED,
            "after": after,
            "cooldown": cooldown,
            "fail_count": 0,
            "restart_count": 0,
            "last_error": None,
            "updated_at": _now_iso(),
            "history": [],
        }
        self._persist()
        return self

    # -- stage machine -----------------------------------------------------
    def _as_stage(self, stage):
        if isinstance(stage, LifecycleStage):
            return stage
        if isinstance(stage, str):
            return LifecycleStage[stage.upper()]
        raise StageTransitionError(None, None, stage, f"invalid stage value: {stage!r}")

    def may_transition(self, from_stage, to_stage) -> bool:
        """True if ``from_stage -> to_stage`` is a legal transition."""
        from_stage = self._as_stage(from_stage)
        to_stage = self._as_stage(to_stage)
        if from_stage == to_stage:
            return True
        return to_stage in STAGE_TRANSITIONS.get(from_stage, set())

    def transition_reason(self, from_stage, to_stage) -> Optional[str]:
        """None if the transition is legal, otherwise a human-readable reason."""
        from_stage = self._as_stage(from_stage)
        to_stage = self._as_stage(to_stage)
        if from_stage == to_stage:
            return None
        legal = STAGE_TRANSITIONS.get(from_stage, set())
        if to_stage in legal:
            return None
        targets = ", ".join(sorted(s.name for s in legal)) or "none"
        return (f"illegal transition {from_stage.name} -> {to_stage.name} "
                f"(from {from_stage.name} the legal targets are: {targets})")

    def mark_stage(self, component_id: str, stage, reason: str = "") -> bool:
        """Move a component to ``stage``, validating the transition.

        Raises StageTransitionError for unknown components or illegal
        transitions — no ghost states. Same-stage re-marks are a no-op.
        """
        comp = self._components.get(component_id)
        if comp is None:
            raise StageTransitionError(
                component_id, None, stage,
                f"component '{component_id}' is not registered")
        to_stage = self._as_stage(stage)
        current = comp["stage"]
        if current == to_stage:
            comp["updated_at"] = _now_iso()
            self._persist()
            return True
        problem = self.transition_reason(current, to_stage)
        if problem:
            raise StageTransitionError(component_id, current, to_stage, problem)
        self._record_transition(comp, current, to_stage, reason)
        return True

    def try_mark_stage(self, component_id: str, stage, reason: str = ""):
        """Like mark_stage, but returns ``(ok, reason)`` instead of raising."""
        try:
            self.mark_stage(component_id, stage, reason)
            return True, None
        except StageTransitionError as exc:
            return False, str(exc)

    def _record_transition(self, comp: Dict[str, Any], from_stage, to_stage,
                           reason: str = ""):
        comp["stage"] = to_stage
        comp["updated_at"] = _now_iso()
        comp.setdefault("history", []).append({
            "from": from_stage.name,
            "to": to_stage.name,
            "at": _now_iso(),
            "reason": reason or "",
        })
        if len(comp["history"]) > MAX_HISTORY:
            comp["history"] = comp["history"][-MAX_HISTORY:]
        self._persist()

    def get_stage(self, component_id: str) -> Optional[LifecycleStage]:
        comp = self._components.get(component_id)
        return comp["stage"] if comp else None

    def get_component(self, component_id: str) -> Optional[Dict[str, Any]]:
        comp = self._components.get(component_id)
        return dict(comp) if comp else None

    def components(self) -> Dict[str, Dict[str, Any]]:
        return {cid: dict(c) for cid, c in self._components.items()}

    def status(self) -> Dict[str, str]:
        """Snapshot of every component id mapped to its current stage name."""
        return {cid: comp["stage"].name for cid, comp in sorted(self._components.items())}

    # -- startup / shutdown / restart --------------------------------------
    def _spec(self, item) -> Dict[str, Any]:
        """Normalize a dict / attribute-carrying object / registered id into a spec."""
        if isinstance(item, str):
            comp = self._components.get(item)
            if comp is None:
                raise StageTransitionError(item, None, None, f"unknown component '{item}'")
            return {
                "id": item,
                "name": comp["name"],
                "after": list(comp["after"]),
                "startup": None,
                "shutdown": None,
                "timeout": None,
                "cooldown": comp["cooldown"],
            }
        if isinstance(item, dict):
            spec = dict(item)
            spec.setdefault("id", None)
            spec.setdefault("name", spec["id"])
            spec.setdefault("after", [])
            spec.setdefault("startup", None)
            spec.setdefault("shutdown", None)
            spec.setdefault("timeout", None)
            spec.setdefault("cooldown", DEFAULT_COOLDOWN)
            return spec
        # Plain object with attributes (e.g. a component class instance).
        return {
            "id": getattr(item, "id", None),
            "name": getattr(item, "name", None) or getattr(item, "id", ""),
            "after": list(getattr(item, "after", None) or []),
            "startup": getattr(item, "startup", None),
            "shutdown": getattr(item, "shutdown", None),
            "timeout": getattr(item, "timeout", None),
            "cooldown": getattr(item, "cooldown", DEFAULT_COOLDOWN),
        }

    @staticmethod
    def _order_components(specs: List[Dict[str, Any]]):
        """Topologically order specs so each starts after its ``after=`` deps.

        Returns ``(ordered_ids, cyclic_ids)``; cyclic_ids participate in a
        dependency cycle and cannot be started.
        """
        present = {s["id"] for s in specs}
        deps = {s["id"]: [d for d in (s.get("after") or []) if d in present] for s in specs}
        indegree = {cid: len(ds) for cid, ds in deps.items()}
        dependents: Dict[str, List[str]] = {cid: [] for cid in deps}
        for cid, dss in deps.items():
            for d in dss:
                dependents[d].append(cid)
        ready = deque(cid for cid, deg in indegree.items() if deg == 0)
        ordered: List[str] = []
        while ready:
            cid = ready.popleft()
            ordered.append(cid)
            for m in dependents.get(cid, []):
                indegree[m] -= 1
                if indegree[m] == 0:
                    ready.append(m)
        cyclic = [cid for cid, deg in indegree.items() if deg > 0]
        return ordered, cyclic

    @staticmethod
    async def _invoke(fn: Callable, timeout: float):
        """Run a component callable, bounding async calls with ``timeout``.

        Sync callables are called directly (they cannot be safely interrupted);
        async callables run under asyncio.wait_for.
        """
        if inspect.iscoroutinefunction(fn):
            return await asyncio.wait_for(fn(), timeout=timeout)
        result = fn()
        if inspect.isawaitable(result):
            return await asyncio.wait_for(result, timeout=timeout)
        return result

    async def startup(self, components: Iterable,
                      timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Dict[str, Any]]:
        """Start components in ``after=`` dependency order.

        Each component moves through ``initializing`` and, on success, to
        ``ready``. A failure marks it ``failed`` and startup continues with the
        remaining components; ``MAX_START_FAILURES`` consecutive failures move
        it to ``quarantined``. Returns a dict of per-component results with
        ``status``, ``detail`` and ``duration_ms``.
        """
        specs = [self._spec(c) for c in components]
        for s in specs:
            if s["id"] is None:
                raise StageTransitionError(None, None, None, "component spec is missing 'id'")
            if s["id"] not in self._components:
                self.register(s["id"], s["name"], after=s["after"], cooldown=s["cooldown"])
        ordered, cyclic = self._order_components(specs)
        by_id = {s["id"]: s for s in specs}
        results: Dict[str, Dict[str, Any]] = {}
        for cid in cyclic:
            ok, err = self.try_mark_stage(cid, LifecycleStage.FAILED, "dependency cycle")
            results[cid] = {"status": "cyclic", "detail": err or "dependency cycle", "duration_ms": 0.0}
        for cid in ordered:
            spec = by_id[cid]
            comp = self._components[cid]
            stage = comp["stage"]
            if stage in (LifecycleStage.READY, LifecycleStage.RUNNING,
                         LifecycleStage.PAUSED, LifecycleStage.QUARANTINED):
                results[cid] = {"status": "skipped",
                                "detail": f"already {stage.name.lower()}", "duration_ms": 0.0}
                continue
            ok, err = self.try_mark_stage(cid, LifecycleStage.INITIALIZING, "startup")
            if not ok:
                results[cid] = {"status": "skipped", "detail": err, "duration_ms": 0.0}
                continue
            started = time.perf_counter()
            error = None
            fn = spec.get("startup")
            if fn is not None:
                try:
                    await self._invoke(fn, spec.get("timeout") or timeout)
                except asyncio.TimeoutError:
                    error = f"startup timed out after {(spec.get('timeout') or timeout)}s"
                except Exception as exc:  # noqa: BLE001 - a failing component must not block others
                    error = f"startup failed: {exc}"
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if error is not None:
                results[cid] = self._fail_start(cid, error, duration_ms)
            else:
                comp["last_error"] = None
                self.mark_stage(cid, LifecycleStage.READY, "startup complete")
                results[cid] = {"status": "started", "detail": None, "duration_ms": duration_ms}
        return results

    def _fail_start(self, component_id: str, error: str, duration_ms: float) -> Dict[str, Any]:
        """Record a failed start; quarantine once the threshold is reached."""
        comp = self._components[component_id]
        comp["fail_count"] = comp.get("fail_count", 0) + 1
        comp["last_error"] = error
        # Always land on FAILED first (initializing -> failed is legal), then
        # escalate to QUARANTINED once the threshold is met.
        self.mark_stage(component_id, LifecycleStage.FAILED, error)
        if comp["fail_count"] >= MAX_START_FAILURES:
            ok, err = self.try_mark_stage(component_id, LifecycleStage.QUARANTINED, error)
            if ok:
                status = "quarantined"
                detail = f"quarantined after {comp['fail_count']} consecutive start failures"
            else:
                status = "failed"
                detail = err
        else:
            status = "failed"
            detail = error
        return {"status": status, "detail": detail, "duration_ms": duration_ms}

    async def shutdown(self, components: Iterable,
                       timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Dict[str, Any]]:
        """Stop components in reverse of their startup dependency order.

        Components move through ``stopping`` to ``stopped``. A failing shutdown
        marks the component ``failed`` and teardown continues with the rest.
        """
        specs = [self._spec(c) for c in components]
        for s in specs:
            if s["id"] is None:
                raise StageTransitionError(None, None, None, "component spec is missing 'id'")
            if s["id"] not in self._components:
                self.register(s["id"], s["name"], after=s["after"], cooldown=s["cooldown"])
        ordered, cyclic = self._order_components(specs)
        by_id = {s["id"]: s for s in specs}
        # Reverse of the startup order, with any cyclic components torn down last.
        order = list(reversed(ordered)) + cyclic
        results: Dict[str, Dict[str, Any]] = {}
        for cid in order:
            spec = by_id[cid]
            comp = self._components.get(cid)
            if comp is None:
                results[cid] = {"status": "skipped", "detail": "not registered", "duration_ms": 0.0}
                continue
            stage = comp["stage"]
            if stage in (LifecycleStage.STOPPED, LifecycleStage.CREATED,
                         LifecycleStage.QUARANTINED):
                results[cid] = {"status": "skipped",
                                "detail": f"already {stage.name.lower()}", "duration_ms": 0.0}
                continue
            ok, err = self.try_mark_stage(cid, LifecycleStage.STOPPING, "shutdown")
            if not ok:
                results[cid] = {"status": "skipped", "detail": err, "duration_ms": 0.0}
                continue
            started = time.perf_counter()
            error = None
            fn = spec.get("shutdown")
            if fn is not None:
                try:
                    await self._invoke(fn, spec.get("timeout") or timeout)
                except asyncio.TimeoutError:
                    error = f"shutdown timed out after {(spec.get('timeout') or timeout)}s"
                except Exception as exc:  # noqa: BLE001 - keep tearing down the rest
                    error = f"shutdown failed: {exc}"
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if error is not None:
                comp["last_error"] = error
                self.mark_stage(cid, LifecycleStage.FAILED, error)
                results[cid] = {"status": "failed", "detail": error, "duration_ms": duration_ms}
            else:
                comp["last_error"] = None
                self.mark_stage(cid, LifecycleStage.STOPPED, "shutdown complete")
                results[cid] = {"status": "stopped", "detail": None, "duration_ms": duration_ms}
        return results

    async def restart(self, component_id: str, check=None):
        """Recover a failed/quarantined component back to ``ready``.

        The component moves to ``recovering``. If a ``check`` callable is
        given, it is evaluated after the component's cooldown; recovery only
        completes when it returns truthy, otherwise the component returns to
        ``failed``. Without a check, recovery is immediate.

        Returns ``(ok, detail)``.
        """
        comp = self._components.get(component_id)
        if comp is None:
            return False, f"component '{component_id}' is not registered"
        current = comp["stage"]
        if current not in (LifecycleStage.FAILED, LifecycleStage.QUARANTINED):
            return False, f"cannot restart a component in stage {current.name}"
        try:
            self.mark_stage(component_id, LifecycleStage.RECOVERING, "restart")
        except StageTransitionError as exc:
            return False, str(exc)
        if check is not None:
            await asyncio.sleep(comp.get("cooldown") or DEFAULT_COOLDOWN)
            result = check()
            if inspect.isawaitable(result):
                result = await result
            if not result:
                self.mark_stage(component_id, LifecycleStage.FAILED, "readiness check failed")
                return False, "readiness check failed"
        self.mark_stage(component_id, LifecycleStage.READY, "restart recovered")
        comp["fail_count"] = 0
        comp["restart_count"] = comp.get("restart_count", 0) + 1
        comp["last_error"] = None
        self._persist()
        return True, "restart recovered"

    # -- JSON persistence ---------------------------------------------------
    def _persist(self) -> None:
        """Best-effort persistence hook. No-op when persistence is disabled."""
        if not self._persist_key:
            return
        save_state(self._persist_key, self._state_payload())

    def _state_payload(self) -> Dict[str, Any]:
        components = {}
        for cid, comp in self._components.items():
            components[cid] = {
                "name": comp["name"],
                "stage": comp["stage"].name,
                "after": list(comp["after"]),
                "cooldown": comp["cooldown"],
                "fail_count": comp["fail_count"],
                "restart_count": comp["restart_count"],
                "last_error": comp.get("last_error"),
                "updated_at": comp["updated_at"],
                "history": comp["history"][-MAX_HISTORY:],
            }
        return {"components": components}

    def _restore_persisted(self) -> None:
        """Best-effort restore of previously persisted stages.

        A fresh supervisor picks up the last-known stage of every known
        component, so a process restart resumes where the last one left off.
        """
        if not self._persist_key:
            return
        payload = load_state(self._persist_key)
        if not payload:
            return
        try:
            for cid, data in (payload.get("components") or {}).items():
                stage = LifecycleStage.CREATED
                if data.get("stage") in LifecycleStage.__members__:
                    stage = LifecycleStage[data["stage"]]
                self._components[cid] = {
                    "name": data.get("name") or cid,
                    "stage": stage,
                    "after": list(data.get("after") or []),
                    "cooldown": float(data.get("cooldown") or DEFAULT_COOLDOWN),
                    "fail_count": int(data.get("fail_count") or 0),
                    "restart_count": int(data.get("restart_count") or 0),
                    "last_error": data.get("last_error"),
                    "updated_at": data.get("updated_at") or _now_iso(),
                    "history": list(data.get("history") or [])[-MAX_HISTORY:],
                }
        except Exception:
            logger.warning(
                "lifecycle/supervisor.py _restore_persisted: suppressed error",
                exc_info=True,
            )

    def get_stats(self) -> Dict[str, Any]:
        counts = {}
        for comp in self._components.values():
            counts[comp["stage"].name] = counts.get(comp["stage"].name, 0) + 1
        persistence = (
            persistence_status(self._persist_key)
            if self._persist_key
            else {"available": True, "operation": "disabled", "error": "", "updated_at": 0.0}
        )
        return {
            "total_components": len(self._components),
            "by_stage": counts,
            "persistence": persistence,
        }


_default_supervisor: Optional[ComponentSupervisor] = None


def get_component_supervisor(reset: bool = False) -> ComponentSupervisor:
    """Module-level accessor for a shared ComponentSupervisor.

    The shared supervisor persists under the ``"supervisor"`` key so ALL NEXUS
    components share one recovery/ordering registry across process restarts.
    Pass ``reset=True`` to rebuild it (discarding the in-memory singleton and
    re-reading whatever was persisted on disk).
    """
    global _default_supervisor
    if _default_supervisor is None or reset:
        _default_supervisor = ComponentSupervisor()
    return _default_supervisor


__all__ = [
    "LifecycleStage",
    "StageTransitionError",
    "ComponentSupervisor",
    "get_component_supervisor",
    "STAGE_TRANSITIONS",
]
