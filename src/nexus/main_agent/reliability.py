"""V5Reliability mixin — wires the reliability core into the V5 loop.

The mixin connects the loop to:

* :class:`reliability.states.RunStateMachine` — validated, recorded,
  persistable state transitions mirrored from ``_transition_to``.
* :class:`reliability.goal.GoalStore` — a durable GoalState per session so
  the original goal, plan, blockers, and completion evidence survive
  restarts and are never replaced by the current error.
* :class:`reliability.recovery.RecoveryEngine` — structured failure
  envelopes, bounded recovery strategies, strategy switching after repeated
  identical failures, and component quarantine.
* :class:`reliability.progress.ProgressTracker` — wall-clock stall detection
  so a slow-but-varying loop cannot run unbounded without progress.

Every method is failure-tolerant: a reliability failure must never break the
loop it is meant to protect. Mixed into ``NexusLoopV5``; no imports from
``core`` (avoids circular imports). The host provides ``self.logger``,
``self.session_id``, ``self.runtime`` (with ``work_event_sink``) and
``self.work_event_sink`` when bound.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from reliability.failure import FailureEnvelope, envelope_from_exception
from reliability.goal import GoalState, GoalStore
from reliability.observability import (
    emit_reliability_event,
    new_correlation_id,
    set_correlation_id,
    structured_log,
)
from reliability.progress import ProgressTracker
from reliability.recovery import RecoveryEngine
from reliability.states import RunState, RunStateMachine

logger = logging.getLogger("nexus.loop.v5.reliability")


def _state_root() -> str:
    return str(os.environ.get("NEXUS_V5_STATE_DIR") or ".nexus/v5")


class V5Reliability:
    """Reliability integration surface for the V5 loop."""

    def _ensure_reliability(self) -> None:
        """Lazily initialize reliability components (once per loop)."""
        if getattr(self, "_reliability_ready", False):
            return
        if getattr(self, "_reliability_disabled", False):
            return
        try:
            root = _state_root()
            session = str(getattr(self, "session_id", "default") or "default")
            sink = self._reliability_sink()
            machine_path = os.path.join(root, "state_machine", f"{session}.json")
            self._state_machine = RunStateMachine(
                initial=RunState.INITIALIZING, persist_path=machine_path
            )
            self._goal_store = GoalStore(os.path.join(root, "goals"))
            self._recovery_engine = RecoveryEngine(
                persist_dir=os.path.join(root, "recovery"),
                event_sink=sink,
            )
            max_idle_s = _env_float("NEXUS_LOOP_STALL_TIMEOUT_S", 600.0, 30.0)
            self._progress_tracker = ProgressTracker(
                max_idle_s=max_idle_s,
                persist_path=os.path.join(root, "progress", f"{session}.json"),
            )
            self._stall_hint_count = 0
            self._reliability_ready = True
        except Exception:
            self._reliability_disabled = True
            logger.warning("reliability integration disabled", exc_info=True)

    def _reliability_sink(self):
        sink = getattr(self, "work_event_sink", None)
        if callable(sink):
            return sink
        runtime = getattr(self, "runtime", None)
        runtime_sink = getattr(runtime, "work_event_sink", None)
        return runtime_sink if callable(runtime_sink) else None

    def _reliability_log(self, event: str, **fields: Any) -> None:
        try:
            structured_log(
                fields.pop("level", "info"),
                "loop.reliability",
                event,
                session=str(getattr(self, "session_id", "")),
                **fields,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # goal
    # ------------------------------------------------------------------ #

    def _get_goal(self, user_request: str = "") -> Optional[GoalState]:
        """Return (creating when needed) the durable goal for this session."""
        self._ensure_reliability()
        if getattr(self, "_reliability_disabled", False):
            return None
        try:
            session = str(getattr(self, "session_id", "default") or "default")
            goal_id = f"goal_{session}"
            goal = self._goal_store.load(goal_id)
            if goal is None:
                goal = GoalState.create(user_request or "unnamed session goal", goal_id=goal_id)
                emit_reliability_event(
                    self._reliability_sink(), "goal.created",
                    goal_id=goal_id, session_id=session,
                )
                self._goal_store.save(goal)
            elif user_request:
                goal.parsed_objective = user_request
                self._goal_store.save(goal)
            return goal
        except Exception:
            self._reliability_log("goal_access_failed", level="warning")
            return None

    def _goal_mutate(self, mutator, *, progress: bool = False) -> None:
        goal = self._get_goal()
        if goal is None:
            return
        try:
            mutator(goal)
            goal.touch(progress=progress)
            self._goal_store.save(goal)
        except Exception:
            self._reliability_log("goal_update_failed", level="warning")

    # ------------------------------------------------------------------ #
    # state machine mirror
    # ------------------------------------------------------------------ #

    def _mirror_transition(self, v5_state: Any, reason: str = "") -> None:
        """Mirror a loop state change through the validated state machine.

        Invalid transitions are rejected (logged) by the machine and never
        raised; this is observability, not control flow.
        """
        self._ensure_reliability()
        if getattr(self, "_reliability_disabled", False):
            return
        try:
            canonical = RunState.from_v5(v5_state)
            if canonical is not None:
                self._state_machine.transition(canonical, reason=reason or "loop phase")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # checkpoint failure surfacing
    # ------------------------------------------------------------------ #

    def _checkpoint_failed(self, callback_name: str, exc: Exception) -> None:
        """Surface a checkpoint persistence failure without crashing the run."""
        self._reliability_log(
            "checkpoint_failed",
            level="error",
            callback=callback_name,
            error=str(exc)[:400],
        )
        try:
            emit_reliability_event(
                self._reliability_sink(),
                "reliability.checkpoint_failed",
                callback=callback_name,
                error=str(exc)[:400],
                session_id=str(getattr(self, "session_id", "")),
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # progress tracking
    # ------------------------------------------------------------------ #

    def _progress_record(self, kind: str, signature: str, status: str = "") -> None:
        self._ensure_reliability()
        if getattr(self, "_reliability_disabled", False):
            return
        try:
            self._progress_tracker.record(
                {
                    "kind": kind,
                    "signature": str(signature)[:200],
                    "status": status,
                    "at": None,
                }
            )
        except Exception:
            pass

    def _stall_check_and_hint(self):
        """Check for a stall; return (signal, hint_text).

        A stall is a wall-clock condition (no meaningful progress for
        NEXUS_LOOP_STALL_TIMEOUT_S) or repeated identical calls/errors. When
        a hint fires, the ineffective strategy is frozen in the recovery
        engine and a fresh approach is suggested to the model instead of
        repeating the same work. ``hint_text`` is None when the stall budget
        is exhausted (the caller should stop the run honestly).
        """
        self._ensure_reliability()
        if getattr(self, "_reliability_disabled", False):
            return None, None
        try:
            signal = self._progress_tracker.check()
            if signal is None:
                return None, None
            self._stall_hint_count = getattr(self, "_stall_hint_count", 0) + 1
            max_hints = int(os.environ.get("NEXUS_LOOP_MAX_STALL_HINTS", "2"))
            emit_reliability_event(
                self._reliability_sink(),
                "reliability.stall",
                kind=signal.kind,
                detail=str(signal.detail)[:400],
                stall_count=self._stall_hint_count,
                session_id=str(getattr(self, "session_id", "")),
            )
            if self._stall_hint_count > max_hints:
                return signal, None
            return signal, (
                "[STALL_DETECTED] The run is not making meaningful progress "
                f"({signal.detail}). STOP repeating the current strategy. "
                "Pick a different approach: use a different tool, different "
                "arguments, a smaller scope, or ask the user for guidance. "
                "Never repeat an identical failing call."
            )
        except Exception:
            return None, None

    def _reset_stall_hints(self) -> None:
        try:
            self._stall_hint_count = 0
        except Exception:
            pass

    def _reset_progress(self) -> None:
        """Clear per-run progress/stall state (call counters, last-progress
        clock) so a new run never inherits another run's stall signals."""
        self._ensure_reliability()
        if getattr(self, "_reliability_disabled", False):
            return
        try:
            self._progress_tracker.reset()
            self._stall_hint_count = 0
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # failure envelopes + recovery
    # ------------------------------------------------------------------ #

    async def _recovery_for_failure(
        self,
        exc: Optional[BaseException] = None,
        *,
        envelope: Optional[FailureEnvelope] = None,
        component_type: str = "unknown",
        component_id: str = "unknown",
        operation: str = "",
        tool: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        failure_class: Any = None,
        message: str = "",
    ) -> Any:
        """Build a failure envelope and run it through the recovery engine.

        Never raises and never changes loop control flow: the result is
        observability + goal bookkeeping + strategy tracking. Returns the
        RecoveryResult (or None when reliability is disabled).
        """
        self._ensure_reliability()
        if getattr(self, "_reliability_disabled", False):
            return None
        try:
            if envelope is None:
                if exc is not None:
                    envelope = envelope_from_exception(
                        exc,
                        component_type=component_type,
                        component_id=component_id,
                        operation=operation,
                        tool=tool,
                        provider=provider,
                        model=model,
                        failure_class=failure_class,
                        goal_id=self._goal_id_or_none(),
                    )
                else:
                    from reliability.failure import FailureClass

                    if failure_class is None:
                        failure_class = FailureClass.UNKNOWN
                    envelope = envelope_from_exception(
                        RuntimeError(message or "unclassified failure"),
                        component_type=component_type,
                        component_id=component_id,
                        operation=operation,
                        tool=tool,
                        provider=provider,
                        model=model,
                        failure_class=failure_class,
                        goal_id=self._goal_id_or_none(),
                    )
            goal = self._get_goal()
            result = await self._recovery_engine.recover(
                envelope, goal=goal, state_machine=self._state_machine
            )
            if result is not None:
                self._consume_recovery_result(result)
            if goal is not None:
                self._goal_store.save(goal)
            return result
        except Exception:
            self._reliability_log("recovery_failed", level="warning")
            return None

    def _consume_recovery_result(self, result: Any) -> None:
        """Surface recovery verdicts: persist intermediate run status and
        consume the operator-facing next_action (never silently dropped).

        Never raises: recovery is observability, not control flow.
        """
        try:
            verdict = str(getattr(result, "verdict", None) or "")
            if verdict.startswith("RecoveryVerdict."):
                verdict = verdict.rsplit(".", 1)[-1]
            verdict = verdict.lower()
            next_action = str(getattr(result, "next_action", "") or "")
            if next_action:
                self._reliability_log(
                    f"recovery requires action: {next_action}", level="warning"
                )
                self._last_recovery_advice = next_action
            status = {
                "waiting_for_user": "waiting_for_permission",
                "blocked_non_recoverable": "blocked",
                "degraded": "degraded",
                "recovered": "recovering",
            }.get(verdict)
            if status:
                run_context = getattr(self, "_current_run_context", None)
                if run_context is not None:
                    run_context.set_intermediate_status(
                        status, detail=next_action or verdict
                    )
        except Exception:
            self._reliability_log(
                "recovery_result_consumption_failed", level="warning"
            )

    def _goal_id_or_none(self) -> Optional[str]:
        try:
            return f"goal_{str(getattr(self, 'session_id', 'default') or 'default')}"
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # run bookkeeping
    # ------------------------------------------------------------------ #

    def _open_run_correlation(self) -> Optional[str]:
        """Assign a fresh correlation id for a new turn and return it."""
        try:
            corr = new_correlation_id()
            set_correlation_id(corr)
            return corr
        except Exception:
            return None

    def _record_terminal_goal(self, v5_state: Any, evidence: Optional[List[str]] = None) -> None:
        """Persist the goal's terminal state with completion evidence."""
        self._ensure_reliability()
        if getattr(self, "_reliability_disabled", False):
            return
        canonical = RunState.from_v5(v5_state)

        def update(goal: GoalState) -> None:
            goal.status = canonical
            if canonical == RunState.GOAL_COMPLETED:
                for item in (evidence or []):
                    if item not in goal.completion_evidence:
                        goal.completion_evidence.append(str(item))
                emit_reliability_event(
                    self._reliability_sink(), "goal.completed",
                    goal_id=goal.goal_id,
                    evidence_count=len(goal.completion_evidence),
                )
            goal.recount_steps()

        self._goal_mutate(update, progress=True)

    def reliability_snapshot(self) -> Dict[str, Any]:
        """Operator-facing snapshot of reliability state."""
        self._ensure_reliability()
        snapshot: Dict[str, Any] = {"disabled": bool(getattr(self, "_reliability_disabled", False))}
        try:
            snapshot["state"] = self._state_machine.state.value
            snapshot["transitions"] = len(self._state_machine.history())
        except Exception:
            pass
        try:
            goal = self._get_goal()
            if goal is not None:
                snapshot["goal"] = {
                    "goal_id": goal.goal_id,
                    "status": goal.status.value,
                    "plan_version": goal.plan_version,
                    "completed_steps": goal.completed_steps,
                    "blocked_steps": goal.blocked_steps,
                    "recovery_ops": len(goal.recovery_history),
                    "blockers": len(goal.blockers),
                    "last_progress_at": goal.last_progress_at,
                }
        except Exception:
            pass
        try:
            snapshot["quarantined"] = self._recovery_engine.quarantined_components()
        except Exception:
            pass
        if getattr(self, "_last_recovery_advice", ""):
            snapshot["recovery_advice"] = self._last_recovery_advice
        return snapshot


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default