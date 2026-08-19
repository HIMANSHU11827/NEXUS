"""Unified durable run projection for NEXUS.

P0-2 of the reliability gap backlog.  V5, the queue driver, and Hive each
kept their own progress record; on restart/replay they could disagree about
what a run had actually done.  This module is the single normalized view of a
run's progress -- the contract every surface converges on.

It is deliberately dependency-light (only ``reliability.goal``,
``reliability.states``, ``reliability.observability``) and time-injectable so
tests never depend on wall-clock behaviour.  Every public function is
failure-tolerant: malformed or empty input is degraded gracefully and never
raised, because a projection that crashes the recovery path is worse than an
approximate one.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from reliability.goal import GoalState, GoalStep
from reliability.observability import emit_reliability_event
from reliability.states import RunState

logger = logging.getLogger("nexus.reliability.run_projection")

# --------------------------------------------------------------------------- #
# progress ordering -- used to pick the "more progressed" view when surfaces
# disagree.  Higher number == further along.
# --------------------------------------------------------------------------- #

# Per-step status progress.  completed is the goal; active is mid-flight;
# pending/blocked are not-yet; failed/cancelled are dead-ends (treated as
# least progressed so a healthy surface can override a stale failure report).
_STEP_PROGRESS: Dict[str, int] = {
    "cancelled": 0,
    "failed": 0,
    "blocked": 0,
    "pending": 1,
    "active": 2,
    "completed": 3,
}

# Terminal run status preference.  Any terminal beats any non-terminal; among
# terminals GOAL_COMPLETED is the strongest "done" signal, then PARTIALLY_,
# then the hard stops.
_TERMINAL_RANK: Dict[RunState, int] = {
    RunState.GOAL_COMPLETED: 4,
    RunState.PARTIALLY_COMPLETED: 3,
    RunState.CANCELLED_BY_USER: 2,
    RunState.TIMED_OUT: 2,
    RunState.FAILED: 1,
}


def _step_rank(status: Any) -> int:
    return _STEP_PROGRESS.get(str(status).lower(), 1)


def _completed_count(projection: "RunProjection") -> int:
    return sum(
        1
        for step in (projection.step_states or [])
        if isinstance(step, dict) and str(step.get("status")).lower() == "completed"
    )


@dataclass
class RunProjection:
    """Single normalized view of one run's progress across all surfaces.

    All three surfaces (v5 / queue / hive) build this same shape from their
    own durable records so that restart/replay shows identical goal/step/
    attempt state everywhere.  ``disagreements`` is non-empty only on the
    merged (reconciled) projection and records where surfaces diverged.
    """

    goal_id: str = ""
    run_id: str = ""
    canonical_status: RunState = RunState.INITIALIZING
    step_states: List[Dict[str, Any]] = field(default_factory=list)
    last_progress_at: float = 0.0
    version: int = 0
    source_surface: str = "reconciled"  # 'v5' | 'queue' | 'hive' | 'reconciled'
    disagreements: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "run_id": self.run_id,
            "canonical_status": self.canonical_status.value,
            "step_states": [dict(step) for step in self.step_states],
            "last_progress_at": self.last_progress_at,
            "version": self.version,
            "source_surface": self.source_surface,
            "disagreements": list(self.disagreements),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunProjection":
        try:
            status = RunState.from_v5(data.get("canonical_status") or "initializing")
        except (ValueError, TypeError):
            status = RunState.INITIALIZING
        steps: List[Dict[str, Any]] = []
        for raw in data.get("step_states") or []:
            if not isinstance(raw, dict):
                continue
            steps.append(
                {
                    "step_id": str(raw.get("step_id") or ""),
                    "status": str(raw.get("status") or "pending"),
                    "attempts": int(raw.get("attempts") or 0),
                }
            )
        return cls(
            goal_id=str(data.get("goal_id") or ""),
            run_id=str(data.get("run_id") or ""),
            canonical_status=status,
            step_states=steps,
            last_progress_at=float(data.get("last_progress_at") or 0.0),
            version=int(data.get("version") or 0),
            source_surface=str(data.get("source_surface") or "reconciled"),
            disagreements=[str(item) for item in (data.get("disagreements") or [])],
        )


def build_projection(
    goal: Optional[GoalState],
    *,
    run_id: str,
    source_surface: str,
    clock: Optional[Callable[[], float]] = None,
) -> RunProjection:
    """Derive the canonical run projection from a durable ``GoalState``.

    This is the contract all three surfaces converge on: V5, the queue driver,
    and Hive each adapt their own record into a ``GoalState``-like view and
    call this to produce a comparable projection.  Never raises -- a missing
    or malformed goal yields a safe empty projection.
    """
    clock = clock or time.time
    if not isinstance(goal, GoalState):
        return RunProjection(
            goal_id="",
            run_id=str(run_id or ""),
            canonical_status=RunState.INITIALIZING,
            step_states=[],
            last_progress_at=clock(),
            version=0,
            source_surface=str(source_surface),
            disagreements=[],
        )

    step_states: List[Dict[str, Any]] = []
    for step in getattr(goal, "plan", []) or []:
        if not isinstance(step, GoalStep):
            continue
        step_states.append(
            {
                "step_id": str(step.id),
                "status": str(step.status),
                "attempts": int(getattr(step, "attempts", 0) or 0),
            }
        )

    status = getattr(goal, "status", RunState.INITIALIZING)
    if not isinstance(status, RunState):
        status = RunState.from_v5(status)

    return RunProjection(
        goal_id=str(getattr(goal, "goal_id", "")),
        run_id=str(run_id),
        canonical_status=status,
        step_states=step_states,
        last_progress_at=float(getattr(goal, "last_progress_at", clock())),
        version=int(getattr(goal, "version", 1)),
        source_surface=str(source_surface),
        disagreements=[],
    )


def reconcile(
    projections: List[RunProjection],
    *,
    sink: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> RunProjection:
    """Merge projections from v5/queue/hive for the SAME goal+run into one.

    Selection rule:
      * A terminal ``canonical_status`` wins outright (most-positive terminal
        preferred: GOAL_COMPLETED > PARTIALLY_COMPLETED > hard stops).
      * Otherwise prefer the projection with the most completed steps, then the
        highest version, then the most recent ``last_progress_at``.
      * Per-step statuses are merged by taking the *most progressed* status
        across surfaces and the max attempt count.

    Any divergence between surfaces is recorded in ``disagreements``.  Never
    raises; malformed/empty input returns a safe empty projection.
    """
    empty = RunProjection(
        goal_id="",
        run_id="",
        canonical_status=RunState.INITIALIZING,
        step_states=[],
        source_surface="reconciled",
        disagreements=["no projections supplied; nothing to reconcile"],
    )
    if not projections:
        emit_reliability_event(
            sink, "run_projection.reconcile_empty", projections=0
        )
        return empty

    valid = [p for p in projections if isinstance(p, RunProjection)]
    if not valid:
        emit_reliability_event(
            sink, "run_projection.reconcile_malformed", projections=len(projections)
        )
        return empty

    # SAFETY: reconcile is only meaningful for ONE goal+run. Silently merging
    # projections from different goals would let a completion on goal A mask a
    # stall on goal B. If the callers disagree on identity, refuse and report
    # it rather than producing a misleading unified view.
    identities = {(p.goal_id, p.run_id) for p in valid}
    if len(identities) > 1:
        emit_reliability_event(
            sink,
            "run_projection.reconcile_mismatched_identity",
            distinct_goals=len(identities),
        )
        return RunProjection(
            goal_id="",
            run_id="",
            canonical_status=RunState.INITIALIZING,
            step_states=[],
            source_surface="reconciled",
            disagreements=[
                f"refused to reconcile {len(identities)} distinct goal/run "
                f"identities into one projection"
            ],
        )

    terminals = [p for p in valid if p.canonical_status.is_terminal]
    if terminals:
        winner = max(
            terminals,
            key=lambda p: (
                _TERMINAL_RANK.get(p.canonical_status, 1),
                _completed_count(p),
                p.version,
                p.last_progress_at,
            ),
        )
    else:
        winner = max(
            valid,
            key=lambda p: (_completed_count(p), p.version, p.last_progress_at),
        )

    # Merge step states: union of step_ids, most-progressed status, max attempts.
    step_reports: Dict[str, List[tuple]] = {}
    for projection in valid:
        for step in projection.step_states or []:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("step_id") or "")
            if not step_id:
                continue
            step_reports.setdefault(step_id, []).append(
                (
                    projection.source_surface,
                    str(step.get("status") or "pending"),
                    int(step.get("attempts") or 0),
                )
            )

    merged_steps: List[Dict[str, Any]] = []
    disagreements: List[str] = []
    for step_id, reports in step_reports.items():
        if not reports:
            continue
        best = max(reports, key=lambda r: _step_rank(r[1]))
        max_attempts = max(r[2] for r in reports)
        merged_steps.append(
            {"step_id": step_id, "status": best[1], "attempts": max_attempts}
        )
        distinct = {r[1] for r in reports}
        if len(distinct) > 1:
            detail = ", ".join(f"{surf}={st}" for surf, st, _ in reports)
            disagreements.append(f"step {step_id}: {detail}")

    # Run-level status divergence (surfaces disagree on overall status).
    distinct_statuses = {str(p.canonical_status.value) for p in valid}
    if len(distinct_statuses) > 1:
        detail = ", ".join(
            f"{p.source_surface}={p.canonical_status.value}" for p in valid
        )
        disagreements.append(f"status: {detail}")

    merged = RunProjection(
        goal_id=winner.goal_id,
        run_id=winner.run_id,
        canonical_status=winner.canonical_status,
        step_states=merged_steps,
        last_progress_at=max((p.last_progress_at for p in valid), default=0.0),
        version=max((p.version for p in valid), default=0),
        source_surface="reconciled",
        disagreements=disagreements,
    )

    emit_reliability_event(
        sink,
        "run_projection.reconciled",
        goal_id=merged.goal_id,
        run_id=merged.run_id,
        canonical_status=merged.canonical_status.value,
        disagreements=len(merged.disagreements),
    )
    return merged


class RunProjectionStore:
    """Atomic JSON persistence for run projections (mirrors ``GoalStore``).

    Each *surface* (v5/queue/hive) is persisted under its own
    ``(run_id, surface)`` key so concurrent heartbeats never overwrite one
    another -- this is what lets :meth:`load_reconciled` merge the per-surface
    views the way :func:`reconcile` expects.  A surface calls
    :meth:`record_surface_state` (a heartbeat) on each progress tick;
    :meth:`load` returns that surface's last known projection and
    :meth:`load_reconciled` returns the merged view across all surfaces.
    """

    def __init__(
        self,
        root_dir: str = ".nexus/v5/run_projections",
        *,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._root_dir = root_dir
        self._clock = clock or time.time

    @staticmethod
    def _safe(value: str) -> str:
        safe = "".join(
            char for char in str(value) if char.isalnum() or char in "-_"
        )
        return safe or "default"

    def _path(self, run_id: str, surface: str = "reconciled") -> str:
        return os.path.join(
            self._root_dir, f"{self._safe(run_id)}__{self._safe(surface)}.json"
        )

    def save(self, projection: RunProjection) -> None:
        """Atomically persist a projection (temp file + os.replace)."""
        try:
            os.makedirs(self._root_dir, exist_ok=True)
            path = self._path(projection.run_id, projection.source_surface)
            fd, temp_path = tempfile.mkstemp(
                prefix=".rp-", suffix=".tmp", dir=self._root_dir
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(projection.to_dict(), handle, default=str, indent=1)
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
            logger.warning(
                "could not save run projection %s/%s",
                getattr(projection, "run_id", "?"),
                getattr(projection, "source_surface", "?"),
                exc_info=True,
            )

    def load(self, run_id: str, surface: str) -> Optional[RunProjection]:
        """Load the last-known projection for a specific surface."""
        try:
            path = self._path(run_id, surface)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as handle:
                return RunProjection.from_dict(json.load(handle))
        except Exception:
            logger.warning(
                "could not load run projection %s/%s", run_id, surface, exc_info=True
            )
            return None

    def load_reconciled(
        self, run_id: str, *, sink: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Optional[RunProjection]:
        """Merge every persisted surface for ``run_id`` into one projection.

        Surfaces are discovered by scanning the store directory for files
        matching ``<run_id>__<surface>.json``. If none exist, returns None.
        """
        try:
            if not os.path.isdir(self._root_dir):
                return None
            prefix = f"{self._safe(run_id)}__"
            projections: List[RunProjection] = []
            for name in os.listdir(self._root_dir):
                if not name.startswith(prefix) or not name.endswith(".json"):
                    continue
                surface = name[len(prefix):-len(".json")]
                proj = self.load(run_id, surface)
                if proj is not None:
                    projections.append(proj)
            if not projections:
                return None
            return reconcile(projections, sink=sink)
        except Exception:
            logger.warning(
                "could not load reconciled projection %s", run_id, exc_info=True
            )
            return None

    def record_surface_state(
        self,
        run_id: str,
        *,
        goal_id: str,
        surface: str,
        canonical_status: Any,
        step_states: Optional[List[Dict[str, Any]]] = None,
        last_progress_at: Optional[float] = None,
        version: int = 1,
        clock: Optional[Callable[[], float]] = None,
        sink: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> RunProjection:
        """Record a surface heartbeat/state so a restart sees the last known view.

        ``canonical_status`` may be a ``RunState`` or a legacy V5 string; it is
        normalized via ``RunState.from_v5``.  The projection is persisted under
        ``(run_id, surface)`` so concurrent surface heartbeats do not clobber
        each other.  Returns the persisted projection.
        """
        clock = clock or self._clock
        normalized_steps: List[Dict[str, Any]] = []
        for raw in step_states or []:
            if not isinstance(raw, dict):
                continue
            normalized_steps.append(
                {
                    "step_id": str(raw.get("step_id") or ""),
                    "status": str(raw.get("status") or "pending"),
                    "attempts": int(raw.get("attempts") or 0),
                }
            )
        status = RunState.from_v5(canonical_status)
        projection = RunProjection(
            goal_id=str(goal_id),
            run_id=str(run_id),
            canonical_status=status,
            step_states=normalized_steps,
            last_progress_at=float(
                last_progress_at if last_progress_at is not None else clock()
            ),
            version=int(version),
            source_surface=str(surface),
            disagreements=[],
        )
        self.save(projection)
        emit_reliability_event(
            sink,
            "run_projection.recorded",
            goal_id=projection.goal_id,
            run_id=projection.run_id,
            surface=projection.source_surface,
            canonical_status=projection.canonical_status.value,
        )
        return projection

    # Alias used by callers that think of this as a heartbeat tick.
    record_heartbeat = record_surface_state
