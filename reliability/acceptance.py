"""Mission / milestone acceptance verification for Nexus.

This module closes a reliability gap: a goal or queue task could previously
be marked complete on the basis of its status alone, without any evidence
that the stated verification criteria were actually met. A verifier
rejection must instead route the milestone back to replanning, and only
verified evidence may mark a goal done.

Design constraints honored here:

* Pure functions over ``GoalState`` -- tests can inject fake goals with the
  same attribute shape. No reliance on the missions watchdog or any runtime
  subsystem.
* Time-injectable via a ``clock`` callable so tests are deterministic.
* Never raises: every entry point catches all exceptions, logs a warning,
  and returns a safe ``AcceptanceResult``. A malformed / ``None`` goal is
  treated as ``accepted=False`` rather than crashing the caller.

The default verifier strategy is deliberately conservative: every entry in
``goal.verification_criteria`` must have at least one matching piece of
evidence (case-insensitive substring match across step evidence, goal
evidence, and goal completion evidence). When no criteria are declared we
fall back to the structural rule "all plan steps are completed and the goal
is not in a terminal failure state".
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from reliability.goal import GoalState  # noqa: F401  (re-exported for callers)
from reliability.observability import emit_reliability_event
from reliability.states import RunState

logger = logging.getLogger("nexus.reliability.acceptance")

# Terminal states that represent failure / non-completion. Used by the
# empty-criteria default rule so a goal that already failed is never
# silently accepted just because its (empty) criteria are trivially met.
_TERMINAL_FAILED = {
    RunState.FAILED,
    RunState.TIMED_OUT,
    RunState.CANCELLED_BY_USER,
}

# Marker prefix appended to ``completion_evidence`` when a goal is accepted.
ACCEPTANCE_MARKER_PREFIX = "acceptance-verified:"

# Kind written into ``recovery_history`` when acceptance is rejected.
ACCEPTANCE_REJECTED_KIND = "acceptance_rejected"

# Reliability event emitted on every acceptance decision.
ACCEPTANCE_EVENT_TYPE = "mission.acceptance"


@dataclass
class AcceptanceResult:
    """Outcome of an acceptance verification pass."""

    accepted: bool
    missing: List[str] = field(default_factory=list)
    satisfied: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "missing": list(self.missing),
            "satisfied": list(self.satisfied),
            "reason": self.reason,
        }


def _safe_list(value: Any) -> List[str]:
    """Coerce an arbitrary value into a list of strings.

    Never raises: ``None`` and non-iterables become an empty list; items
    that fail to stringify are skipped.
    """
    if value is None:
        return []
    try:
        return [str(item) for item in value]
    except Exception:
        return []


def _norm_token(text: str) -> Optional[str]:
    """Lower-case, punctuation-stripped token for evidence matching.

    Returns ``None`` for blank/whitespace-only input so empty criteria never
    match (an empty criterion must not be trivially satisfied).
    """
    token = re.sub(r"[^0-9a-z]+", " ", str(text).lower()).strip()
    return token or None


def _criterion_satisfied(criterion: str, evidence: List[str]) -> bool:
    """True only when the criterion appears as a whole word/token in evidence.

    A naive ``criterion in evidence`` substring check is unsafe: ``'api'``
    matches ``'rApiD'`` and ``'done'`` matches ``'abandOned'``, which would
    let a goal be falsely marked complete. We require a word-boundary match on
    the normalized token so only deliberate, whole-word evidence counts.
    Blank criteria are ignored (never satisfied).
    """
    needle = _norm_token(criterion)
    if needle is None:
        return False
    pattern = re.compile(rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])")
    for ev in evidence:
        ev_tokens = _norm_token(ev)
        if ev_tokens and pattern.search(ev_tokens):
            return True
    return False


def _gather_evidence(goal: Any) -> List[str]:
    """Collect every piece of accumulated evidence for a goal.

    Pulls from ``goal.evidence``, ``goal.completion_evidence`` and each
    plan step's ``evidence``. Tolerant of missing attributes.
    """
    evidence: List[str] = []
    evidence.extend(_safe_list(getattr(goal, "evidence", None)))
    evidence.extend(_safe_list(getattr(goal, "completion_evidence", None)))
    plan = getattr(getattr(goal, "plan", None), "__iter__", None) and goal.plan
    if plan:
        for step in plan:
            try:
                evidence.extend(_safe_list(getattr(step, "evidence", None)))
            except Exception:
                continue
    return evidence


class MilestoneAcceptanceVerifier:
    """Decides whether a goal's verification criteria are satisfied.

    The object is stateless apart from the injected clock, so it can be
    shared across goals and reused freely.
    """

    def __init__(self, *, clock: Optional[Callable[[], float]] = None):
        self._clock = clock or time.time

    # -- public API ------------------------------------------------------

    def verify(self, goal: Any) -> AcceptanceResult:
        """Pure, never-raising verification of a goal's acceptance.

        Guards against malformed / ``None`` goals by returning a safe
        ``accepted=False`` result rather than propagating exceptions.
        """
        try:
            return self._verify(goal)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "acceptance verify failed; guarding: %s", exc, exc_info=True
            )
            return AcceptanceResult(
                accepted=False,
                missing=[],
                satisfied=[],
                reason=f"verify-error: {exc}",
            )

    def mark_completed_if_verified(
        self,
        goal: Any,
        store: Optional[Any] = None,
        *,
        sink: Optional[Callable[[dict], None]] = None,
    ) -> AcceptanceResult:
        """Verify and mutate the goal to its correct terminal state.

        On acceptance: ``goal.status = GOAL_COMPLETED`` and an
        ``acceptance-verified:<timestamp>`` marker is appended to
        ``completion_evidence``.

        On rejection: ``goal.status = BLOCKED_NON_RECOVERABLE`` (never
        falsely completed) and an ``acceptance_rejected`` entry is appended
        to ``recovery_history`` so the milestone can be replanned.

        A ``mission.acceptance`` reliability event is always emitted with
        the accepted flag and the missing criteria. If ``store`` is provided
        the resulting goal is persisted.

        Never raises.
        """
        try:
            return self._mark_completed_if_verified(goal, store=store, sink=sink)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "mark_completed_if_verified failed; guarding: %s", exc, exc_info=True
            )
            return AcceptanceResult(
                accepted=False,
                missing=[],
                satisfied=[],
                reason=f"mark-error: {exc}",
            )

    # -- internals -------------------------------------------------------

    def _verify(self, goal: Any) -> AcceptanceResult:
        if goal is None:
            return AcceptanceResult(
                accepted=False,
                missing=[],
                satisfied=[],
                reason="goal is None",
            )

        criteria = _safe_list(getattr(goal, "verification_criteria", None))
        if not criteria:
            return self._verify_empty_criteria(goal)

        evidence = _gather_evidence(goal)
        satisfied: List[str] = []
        missing: List[str] = []
        for criterion in criteria:
            # Blank criteria are reported as missing (never auto-satisfied),
            # so a goal can never be accepted on the strength of an empty check.
            if _norm_token(criterion) is None:
                missing.append(str(criterion))
                continue
            if _criterion_satisfied(criterion, evidence):
                satisfied.append(criterion)
            else:
                missing.append(criterion)

        accepted = not missing
        return AcceptanceResult(
            accepted=accepted,
            missing=missing,
            satisfied=satisfied,
            reason=(
                "all verification criteria satisfied by evidence"
                if accepted
                else (
                    f"{len(missing)} verification criteria unmet: "
                    f"{', '.join(missing)}"
                )
            ),
        )

    def _verify_empty_criteria(self, goal: Any) -> AcceptanceResult:
        """Default rule when no verification criteria are declared.

        Accept only when every plan step is ``completed`` *and* the goal is
        not already in a terminal failure state.
        """
        try:
            plan = goal.plan
        except Exception:
            plan = None
        steps = list(plan) if plan else []
        all_completed = bool(steps) and all(
            getattr(step, "status", None) == "completed" for step in steps
        )
        status = getattr(goal, "status", None)
        not_failed = status not in _TERMINAL_FAILED

        if all_completed and not_failed:
            return AcceptanceResult(
                accepted=True,
                missing=[],
                satisfied=[],
                reason="empty criteria: all steps completed and not terminal-failed",
            )

        gaps = []
        if not all_completed:
            gaps.append("not-all-steps-completed")
        if not not_failed:
            gaps.append("status-terminal-failed")
        return AcceptanceResult(
            accepted=False,
            missing=gaps,
            satisfied=[],
            reason="empty criteria default rule failed: " + ", ".join(gaps),
        )

    def _mark_completed_if_verified(
        self, goal: Any, store: Optional[Any], sink: Optional[Callable[[dict], None]]
    ) -> AcceptanceResult:
        result = self._verify(goal)

        if goal is not None:
            # Mutation is best-effort: a malformed goal must not prevent the
            # reliability event (below) from firing.
            try:
                if result.accepted:
                    goal.status = RunState.GOAL_COMPLETED
                    goal.completion_evidence.append(
                        f"{ACCEPTANCE_MARKER_PREFIX}{self._clock()}"
                    )
                else:
                    goal.status = RunState.BLOCKED_NON_RECOVERABLE
                    goal.recovery_history.append(
                        {
                            "kind": ACCEPTANCE_REJECTED_KIND,
                            "missing": list(result.missing),
                            "satisfied": list(result.satisfied),
                            "reason": result.reason,
                            "timestamp": self._clock(),
                        }
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "could not mutate goal on acceptance decision: %s",
                    exc,
                    exc_info=True,
                )

        emit_reliability_event(
            sink,
            ACCEPTANCE_EVENT_TYPE,
            accepted=result.accepted,
            missing=list(result.missing),
            satisfied=list(result.satisfied),
            goal_id=getattr(goal, "goal_id", None) if goal is not None else None,
        )

        if store is not None:
            try:
                store.save(goal)
            except Exception as exc:  # never raise on persistence failure
                logger.warning(
                    "could not persist goal after acceptance: %s", exc, exc_info=True
                )

        return result
