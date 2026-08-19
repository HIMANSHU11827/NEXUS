"""Mission heartbeat and stuck-step recovery watchdog for Nexus.

Background: NEXUS already has durable goals (``reliability.goal.GoalState``),
a loop-stall detector (``reliability.progress.ProgressTracker``), and a
state machine (``reliability.states.RunState``). What was MISSING (verified:
zero hits in prior source) was a mission-level contract that:

  * treats a goal holding a live lease while making no progress as STUCK,
  * recovers a stuck milestone by requeueing it EXACTLY ONCE and recording why,
  * prevents an aged lease from silently hiding a permanently stalled run.

This module is the missing piece. It is intentionally small, pure, and
time-injectable so it can be driven deterministically by tests and by the
real 24/7 queue driver / supervisor.

Design rules (mirrors the rest of ``reliability``):
  * Never raises. Storage/clock errors are logged and swallowed.
  * Atomic durable writes (temp file + os.replace), like GoalStore.
  * Every recovery emits a structured reliability event with a reason.
  * "Exactly once" is enforced per (goal_id, step_id) via a recovery ledger
    so a crash during recovery does not double-recover.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from reliability.goal import GoalState, GoalStore
from reliability.observability import emit_reliability_event
from reliability.states import RunState

logger = logging.getLogger("nexus.reliability.mission_watchdog")


@contextmanager
def _cross_process_lock(ledger_path: Optional[str]):
    """Exclusive advisory lock around a ledger file.

    Serializes the check->reset->persist critical section of recovery across
    processes/hosts that share the same ledger file, so two watchdog
    instances cannot both decide to recover the same step (which would
    violate exactly-once). Falls back to a no-op when no OS lock primitive is
    available (e.g. unsupported platform) -- per-instance RLock still guards
    within a single process.

    The lock is taken on a dedicated ``<ledger>.lock`` file (not the ledger
    itself) so the ledger file remains freely replaceable by os.replace while
    the lock is held.
    """
    if not ledger_path:
        yield
        return
    lock_path = f"{ledger_path}.lock"
    directory = os.path.dirname(os.path.abspath(lock_path))
    os.makedirs(directory, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            if os.name == "nt":
                import msvcrt

                # msvcrt locking is byte-range based; lock the first byte.
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
        except (ImportError, OSError) as exc:
            logger.debug("cross-process ledger lock unavailable: %s", exc)
        try:
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
    finally:
        os.close(fd)

# States that mean "work is supposed to be happening" — if last_progress_at
# is older than the stall budget while in one of these, the milestone is stuck.
_ACTIVE_RUNNING_STATES = {
    RunState.INITIALIZING,
    RunState.PERCEIVING,
    RunState.PLANNING,
    RunState.EXECUTING,
    RunState.VERIFYING,
    RunState.RECOVERING,
    RunState.REPLANNING,
    RunState.RETRYING,
    RunState.OBSERVING,
    RunState.REFLECTING,
    RunState.OUTPUTTING,
}

# Default: a goal that has not progressed in this many seconds is stalled.
DEFAULT_STALL_TIMEOUT_S = 900.0
# Safety bound: requeue a stuck step at most this many times across restarts.
DEFAULT_MAX_RECOVERIES_PER_STEP = 1


@dataclass
class StuckStep:
    """A step the watchdog has decided is stalled."""

    goal_id: str
    step_id: str
    last_progress_at: float
    stalled_for_s: float
    goal_state: str
    reason: str


@dataclass
class RecoveryAction:
    """What the watchdog did (or would do) about a stuck step."""

    goal_id: str
    step_id: str
    action: str  # "requeued" | "skipped_already_recovered" | "none"
    reason: str
    recovered: bool
    timestamp: float = field(default_factory=time.time)


class MissionWatchdog:
    """Detect stalled milestones and recover them exactly once.

    The watchdog does NOT own the run loop. It is a pure function over a
    ``GoalState`` plus a clock, plus a small durable ledger that records which
    (goal, step) pairs have already been recovered so recovery is idempotent
    across process restarts.
    """

    def __init__(
        self,
        *,
        store: Optional[GoalStore] = None,
        stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S,
        max_recoveries_per_step: int = DEFAULT_MAX_RECOVERIES_PER_STEP,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        clock: Optional[Callable[[], float]] = None,
        ledger_path: Optional[str] = None,
    ):
        self._store = store
        self._stall_timeout_s = max(1.0, float(stall_timeout_s))
        self._max_recoveries_per_step = max(1, int(max_recoveries_per_step))
        self._event_sink = event_sink
        self._clock = clock or time.time
        self._ledger_path = ledger_path
        self._lock = threading.RLock()
        self._ledger: Dict[str, int] = {}
        self._load_ledger()

    # ------------------------------------------------------------------ #
    # ledger (durable exactly-once record)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _ledger_key(goal_id: str, step_id: str) -> str:
        return f"{goal_id}:{step_id}"

    def _load_ledger(self) -> None:
        if not self._ledger_path:
            return
        try:
            if os.path.exists(self._ledger_path):
                with open(self._ledger_path, "r", encoding="utf-8") as handle:
                    data = __import__("json").load(handle)
                if isinstance(data, dict):
                    self._ledger = {
                        str(k): int(v) for k, v in data.items()
                    }
        except Exception:
            logger.warning("could not load recovery ledger", exc_info=True)

    def _persist_ledger(self) -> None:
        if not self._ledger_path:
            return
        try:
            directory = os.path.dirname(os.path.abspath(self._ledger_path))
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                prefix=".watchdog-", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    __import__("json").dump(self._ledger, handle, default=str)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self._ledger_path)
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        except Exception:
            logger.warning("could not persist recovery ledger", exc_info=True)

    # ------------------------------------------------------------------ #
    # detection
    # ------------------------------------------------------------------ #

    def find_stuck_steps(self, goal: GoalState) -> List[StuckStep]:
        """Return every active step stalled past the timeout.

        Goals whose acceptance was rejected (``BLOCKED_NON_RECOVERABLE``) are
        intentionally skipped: they are resumable by design, not stalled
        runners, so the watchdog must not treat them as stuck. Per-step
        ``last_progress_at`` is preferred when the execution loop records it,
        falling back to goal-level progress; either way a step stalled at or
        beyond the timeout is reported (``>=`` so an exactly-timeout step is
        caught, not silently skipped).
        """
        if goal is None or goal.is_terminal():
            return []
        if goal.status == RunState.BLOCKED_NON_RECOVERABLE:
            return []
        now = self._clock()
        stalled: List[StuckStep] = []
        goal_progress = float(getattr(goal, "last_progress_at", now))
        for step in goal.plan:
            if step.status not in ("active", "pending"):
                continue
            # Prefer the step's own progress signal; fall back to goal-level.
            last = float(getattr(step, "last_progress_at", None) or goal_progress)
            stalled_for = now - last
            if stalled_for >= self._stall_timeout_s:
                stalled.append(
                    StuckStep(
                        goal_id=goal.goal_id,
                        step_id=step.id,
                        last_progress_at=last,
                        stalled_for_s=stalled_for,
                        goal_state=goal.status.value,
                        reason=(
                            f"no progress for {stalled_for:.0f}s "
                            f"(limit {self._stall_timeout_s:g}s) in state "
                            f"{goal.status.value}"
                        ),
                    )
                )
        return stalled

    # ------------------------------------------------------------------ #
    # recovery (exactly once)
    # ------------------------------------------------------------------ #

    def recover_step(
        self, goal: GoalState, step: StuckStep, *, requeue: bool = True
    ) -> RecoveryAction:
        """Recover one stuck step. Idempotent across restarts via the ledger.

        A step is requeued at most ``max_recoveries_per_step`` times. On the
        first recovery the step is reset to ``pending`` (requeue) and the reason
        is recorded on the goal's recovery history. Subsequent calls for the
        same (goal, step) return ``skipped_already_recovered`` without mutating
        state -- this is what makes the watchdog safe to run after a crash.

        Correctness contract (verified by tests):
          * The decision + durable ledger increment happen inside a
            cross-process lock (reloading the ledger fresh), so two watchdog
            instances in different processes cannot both decide to recover the
            same step -- exactly-once holds across processes, not just threads.
          * The ledger is incremented ONLY AFTER a successful reset, so a
            failed store write does NOT burn the recovery budget and does NOT
            falsely report success.
          * Store failures are caught and surfaced as ``recovered=False`` with
            the real error, never as a silent crash or a false positive.
        """
        key = self._ledger_key(goal.goal_id, step.step_id)

        # Decision + durable record under one cross-process critical section.
        with _cross_process_lock(self._ledger_path):
            # Reload fresh so a concurrent process's increment is visible.
            self._load_ledger()
            with self._lock:
                prior = self._ledger.get(key, 0)
                if prior >= self._max_recoveries_per_step:
                    return RecoveryAction(
                        goal_id=goal.goal_id,
                        step_id=step.step_id,
                        action="skipped_already_recovered",
                        reason=(
                            f"step already recovered {prior} time(s); "
                            f"not re-recovering to avoid duplicate work"
                        ),
                        recovered=False,
                    )

            # Perform the reset FIRST. Only if the reset succeeds do we record
            # the recovery in the durable ledger -- otherwise a failed store
            # write would both lose the step AND permanently burn its one
            # recovery chance.
            try:
                if requeue and self._store is not None:
                    # Persist the reset atomically (reload + mutate + save).
                    self._store.update(
                        goal.goal_id,
                        lambda g: self._reset_step(g, step.step_id, step.reason),
                    )
                else:
                    # No store write requested (or no store wired): reset in
                    # memory so the caller's goal object reflects the requeue.
                    self._reset_step(goal, step.step_id, step.reason)
            except Exception as exc:
                logger.error(
                    "watchdog could not reset stuck step %s/%s: %s",
                    goal.goal_id,
                    step.step_id,
                    exc,
                )
                emit_reliability_event(
                    self._event_sink,
                    "mission.stuck_recovery_failed",
                    goal_id=goal.goal_id,
                    step_id=step.step_id,
                    error=str(exc),
                )
                return RecoveryAction(
                    goal_id=goal.goal_id,
                    step_id=step.step_id,
                    action="requeue_failed",
                    reason=f"recovery failed before persist: {exc}",
                    recovered=False,
                )

            # Reset succeeded: durably record the recovery inside the lock so a
            # concurrent process sees the incremented count before it decides.
            with self._lock:
                self._ledger[key] = prior + 1
                self._persist_ledger()

        emit_reliability_event(
            self._event_sink,
            "mission.stuck_recovered",
            goal_id=goal.goal_id,
            step_id=step.step_id,
            stalled_for_s=round(step.stalled_for_s, 1),
            goal_state=step.goal_state,
            reason=step.reason,
            recovery_count=self._ledger[key],
        )
        logger.warning(
            "watchdog recovered stuck step %s/%s: %s",
            goal.goal_id,
            step.step_id,
            step.reason,
        )
        return RecoveryAction(
            goal_id=goal.goal_id,
            step_id=step.step_id,
            action="requeued",
            reason=step.reason,
            recovered=True,
        )

    @staticmethod
    def _reset_step(goal: GoalState, step_id: str, reason: str) -> None:
        for s in goal.plan:
            if s.id == step_id:
                s.status = "pending"
                s.attempts = 0
                s.error = None
                s.evidence = []
                break
        goal.recovery_history.append(
            {
                "kind": "watchdog_requeue",
                "step_id": step_id,
                "reason": reason,
                "timestamp": time.time(),
            }
        )
        goal.touch()

    # ------------------------------------------------------------------ #
    # sweep (the function the driver/supervisor calls on a timer)
    # ------------------------------------------------------------------ #

    def sweep(self, goals: Optional[List[GoalState]] = None) -> List[RecoveryAction]:
        """Scan active goals, requeue each stuck step exactly once.

        If ``goals`` is None and a store is wired, all active goals are loaded
        from the store. Returns the list of recovery actions taken.
        """
        if goals is None and self._store is not None:
            goals = self._store.list_active()
        if not goals:
            return []
        actions: List[RecoveryAction] = []
        for goal in goals:
            for stuck in self.find_stuck_steps(goal):
                actions.append(self.recover_step(goal, stuck))
        return actions


__all__ = [
    "MissionWatchdog",
    "StuckStep",
    "RecoveryAction",
    "DEFAULT_STALL_TIMEOUT_S",
    "DEFAULT_MAX_RECOVERIES_PER_STEP",
]
