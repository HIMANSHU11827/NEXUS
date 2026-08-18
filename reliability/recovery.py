"""Central, policy-driven recovery engine.

Every subsystem reports a :class:`FailureEnvelope` to :class:`RecoveryEngine`;
the engine selects a bounded recovery strategy via the recovery ladder, tracks
previous strategies per failure signature so identical failures never repeat
the same strategy endlessly, quarantines unhealthy components, and persists a
resumable blocked state when no automated recovery remains.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from reliability.failure import FailureClass, FailureEnvelope, is_recoverable
from reliability.goal import GoalState
from reliability.observability import emit_reliability_event
from reliability.states import RunState, RunStateMachine

logger = logging.getLogger("nexus.reliability.recovery")


class RecoveryVerdict(str, Enum):
    RECOVERED = "recovered"
    DEGRADED = "degraded"
    CONTINUED_INDEPENDENT = "continued_independent"
    BLOCKED_NON_RECOVERABLE = "blocked_non_recoverable"
    WAITING_FOR_USER = "waiting_for_user"
    NOT_NEEDED = "not_needed"


@dataclass
class RecoveryResult:
    verdict: RecoveryVerdict
    strategy: str
    detail: str = ""
    attempts: int = 1
    recovered_component: str = ""
    next_action: str = ""
    checkpoint_ref: Optional[str] = None
    correlation_id: Optional[str] = None
    previous_strategies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "strategy": self.strategy,
            "detail": self.detail,
            "attempts": self.attempts,
            "recovered_component": self.recovered_component,
            "next_action": self.next_action,
            "checkpoint_ref": self.checkpoint_ref,
            "correlation_id": self.correlation_id,
            "previous_strategies": list(self.previous_strategies),
        }


@dataclass
class RecoveryContext:
    """Per-recovery bookkeeping passed to adapters."""

    envelope: FailureEnvelope
    goal: Optional[GoalState] = None
    state_machine: Optional[RunStateMachine] = None
    attempt_count: int = 1
    previous_strategies: List[str] = field(default_factory=list)

    def record_strategy(self, name: str) -> None:
        self.previous_strategies.append(name)


# Adapter signature: (FailureEnvelope, RecoveryContext) -> Optional[RecoveryResult]
ComponentAdapter = Callable[[FailureEnvelope, "RecoveryContext"], Optional[RecoveryResult]]

_BLOCKED_VERDICTS = {
    RecoveryVerdict.BLOCKED_NON_RECOVERABLE,
    RecoveryVerdict.WAITING_FOR_USER,
}

_UNREACHABLE = object()


class RecoveryEngine:
    """Policy-driven recovery with strategy tracking and quarantine."""

    def __init__(
        self,
        *,
        persist_dir: Optional[str] = ".nexus/v5/recovery",
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        multiplier: float = 2.0,
        jitter: float = 0.25,
        rng: Optional[random.Random] = None,
    ):
        self._persist_dir = persist_dir
        self._event_sink = event_sink
        self._max_attempts = max(1, int(max_attempts))
        self._base_delay = max(0.0, float(base_delay))
        self._max_delay = max(0.1, float(max_delay))
        self._multiplier = max(1.0, float(multiplier))
        self._jitter = min(1.0, max(0.0, float(jitter)))
        self._rng = rng or random.Random()
        self._adapters: List[ComponentAdapter] = []
        self._lock = asyncio.Lock()
        self._strategy_history: Dict[str, Dict[str, Any]] = {}
        self._quarantine: Dict[str, float] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # state
    # ------------------------------------------------------------------ #

    def _strategy_path(self) -> str:
        return os.path.join(self._persist_dir or ".nexus/v5/recovery", "strategies.json")

    def _quarantine_path(self) -> str:
        return os.path.join(self._persist_dir or ".nexus/v5/recovery", "quarantine.json")

    def _atomic_write(self, path: str, payload: Dict[str, Any]) -> None:
        if not self._persist_dir:
            return
        try:
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                prefix=".rec-", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, default=str, indent=1)
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
            logger.warning("could not write %s", path, exc_info=True)

    def _load(self) -> None:
        if not self._persist_dir:
            return
        try:
            path = self._strategy_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    self._strategy_history = loaded
        except Exception:
            logger.warning("could not load recovery strategy history", exc_info=True)
        try:
            path = self._quarantine_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    self._quarantine = {
                        str(key): float(value)
                        for key, value in loaded.items()
                    }
        except Exception:
            logger.warning("could not load quarantine state", exc_info=True)

    def _persist_strategies(self) -> None:
        self._atomic_write(self._strategy_path(), self._strategy_history)

    def _persist_quarantine(self) -> None:
        self._atomic_write(self._quarantine_path(), self._quarantine)

    # ------------------------------------------------------------------ #
    # adapters
    # ------------------------------------------------------------------ #

    def register_adapter(self, adapter: ComponentAdapter) -> None:
        """Register a component-specific recovery adapter.

        Adapters run in registration order; the first non-None result wins,
        except that a blocked verdict from an earlier adapter does not
        prevent later adapters from attempting recovery.
        """
        self._adapters.append(adapter)

    def adapters(self) -> List[ComponentAdapter]:
        return list(self._adapters)

    # ------------------------------------------------------------------ #
    # quarantine
    # ------------------------------------------------------------------ #

    def quarantine(self, component_type: str, component_id: str, reason: str) -> None:
        key = f"{component_type}:{component_id}"
        self._quarantine[key] = time.time()
        self._persist_quarantine()
        emit_reliability_event(
            self._event_sink,
            "reliability.quarantine",
            component_type=component_type,
            component_id=component_id,
            reason=reason,
        )
        logger.warning("quarantined %s %s: %s", component_type, component_id, reason)

    def unquarantine(self, component_type: str, component_id: str) -> None:
        key = f"{component_type}:{component_id}"
        if key in self._quarantine:
            del self._quarantine[key]
            self._persist_quarantine()
            emit_reliability_event(
                self._event_sink,
                "reliability.unquarantine",
                component_type=component_type,
                component_id=component_id,
            )
            logger.info("unquarantined %s %s", component_type, component_id)

    def is_quarantined(self, component_type: str, component_id: str) -> bool:
        return f"{component_type}:{component_id}" in self._quarantine

    def quarantined_components(self) -> List[Dict[str, Any]]:
        return [
            {"key": key, "since": since}
            for key, since in self._quarantine.items()
        ]

    # ------------------------------------------------------------------ #
    # strategy bookkeeping
    # ------------------------------------------------------------------ #

    def strategy_history(self, signature: str) -> Dict[str, Any]:
        return dict(self._strategy_history.get(signature, {}))

    def _strategy_state(self, signature: str) -> Dict[str, Any]:
        entry = self._strategy_history.get(signature)
        if entry is None:
            entry = {
                "attempts": 0,
                "strategies": [],
                "frozen": [],
                "last_seen": 0.0,
            }
            self._strategy_history[signature] = entry
        return entry

    def _record_strategy(
        self, signature: str, strategy: str, *, success: bool
    ) -> None:
        entry = self._strategy_state(signature)
        entry["attempts"] = entry.get("attempts", 0) + 1
        entry["strategies"].append(
            {"name": strategy, "success": bool(success), "at": time.time()}
        )
        entry["last_seen"] = time.time()
        if not success:
            frozen = entry.setdefault("frozen", [])
            if strategy not in frozen:
                frozen.append(strategy)
        self._persist_strategies()

    def _frozen_strategies(self, signature: str) -> List[str]:
        return list(self._strategy_state(signature).get("frozen", []))

    # ------------------------------------------------------------------ #
    # recovery ladder
    # ------------------------------------------------------------------ #

    def _generic_ladder(
        self,
        context: RecoveryContext,
        signatures: List[str],
        previous: List[str],
    ) -> RecoveryResult:
        """Bounded generic retry with backoff, then strategy switch, then
        precise blocked state."""
        envelope = context.envelope
        signature = signatures[0]
        frozen = self._frozen_strategies(signature)
        attempts_so_far = context.attempt_count

        if envelope.failure_class == FailureClass.RATE_LIMIT:
            strategy = "backoff_retry"
            if strategy in frozen:
                strategy = "switch_provider_or_endpoint"
        elif envelope.failure_class == FailureClass.TIMEOUT:
            strategy = "retry_with_backoff"
            if strategy in frozen:
                strategy = "fallback_equivalent_tool"
        elif envelope.failure_class in {
            FailureClass.NETWORK, FailureClass.DNS, FailureClass.PROVIDER_OUTAGE,
            FailureClass.DEPENDENCY_UNAVAILABLE,
        }:
            strategy = "backoff_retry"
            if strategy in frozen:
                strategy = "switch_provider"
        elif envelope.failure_class == FailureClass.EMPTY_MODEL_RESPONSE:
            strategy = "retry_model_call"
            if strategy in frozen:
                strategy = "switch_provider"
        else:
            strategy = "retry_with_backoff"

        if attempts_so_far >= self._max_attempts or strategy in frozen:
            next_action = envelope.recommended_recovery or (
                "inspect logs, repair the component, then resume from the last checkpoint"
            )
            result = RecoveryResult(
                verdict=RecoveryVerdict.BLOCKED_NON_RECOVERABLE,
                strategy="bounded_retries_exhausted",
                detail=(
                    f"{attempts_so_far} attempt(s) of {envelope.failure_class.value} "
                    f"on {envelope.component_type}:{envelope.component_id} did not recover"
                ),
                attempts=attempts_so_far,
                recovered_component=envelope.component_id,
                next_action=next_action,
                correlation_id=envelope.correlation_id,
                previous_strategies=list(previous),
            )
            return result

        delay = min(
            self._max_delay,
            self._base_delay * (self._multiplier ** max(0, attempts_so_far - 1)),
        )
        if self._jitter > 0:
            delay *= 1.0 + self._rng.uniform(-self._jitter, self._jitter)
        result = RecoveryResult(
            verdict=RecoveryVerdict.RECOVERED,
            strategy=strategy,
            detail=(
                f"retrying {envelope.component_type}:{envelope.component_id} "
                f"(attempt {attempts_so_far}/{self._max_attempts}, backoff {delay:.1f}s)"
            ),
            attempts=attempts_so_far,
            recovered_component=envelope.component_id,
            next_action="resume the interrupted step from the last valid checkpoint",
            correlation_id=envelope.correlation_id,
            previous_strategies=list(previous),
        )
        result.__dict__["_retry_delay"] = delay
        return result

    def _retry_delay(self, result: RecoveryResult) -> float:
        return float(result.__dict__.get("_retry_delay", 0.0))

    async def recover(
        self,
        envelope: FailureEnvelope,
        *,
        goal: Optional[GoalState] = None,
        state_machine: Optional[RunStateMachine] = None,
    ) -> RecoveryResult:
        """Run the recovery ladder for one failure envelope.

        Order: user action required -> non-recoverable -> component adapters
        -> generic bounded ladder. The original goal object is preserved and
        receives recovery history.
        """
        signature = envelope.signature()
        previous: List[str] = []

        async with self._lock:
            entry = self._strategy_state(signature)
            attempt_count = int(entry.get("attempts", 0)) + 1
            previous = [item.get("name", "") for item in entry.get("strategies", [])]

        if state_machine is not None and state_machine.state != RunState.RECOVERING:
            state_machine.transition(
                RunState.RECOVERING,
                reason=f"recovering {envelope.failure_class.value} on {envelope.component_id}",
            )

        context = RecoveryContext(
            envelope=envelope,
            goal=goal,
            state_machine=state_machine,
            attempt_count=attempt_count,
            previous_strategies=list(previous),
        )

        if envelope.is_user_action_required:
            result = RecoveryResult(
                verdict=RecoveryVerdict.WAITING_FOR_USER,
                strategy="request_user_action",
                detail=envelope.message,
                attempts=attempt_count,
                recovered_component=envelope.component_id,
                next_action=envelope.recommended_recovery or "user approval required",
                correlation_id=envelope.correlation_id,
                previous_strategies=list(previous),
            )
            self._finish(envelope, goal, context, result, success=False)
            return result

        if not is_recoverable(envelope):
            result = RecoveryResult(
                verdict=RecoveryVerdict.BLOCKED_NON_RECOVERABLE,
                strategy="non_recoverable_failure",
                detail=(
                    f"{envelope.failure_class.value} is not recoverable: {envelope.message}"
                ),
                attempts=attempt_count,
                recovered_component=envelope.component_id,
                next_action=envelope.recommended_recovery or (
                    "external action required before this goal can continue"
                ),
                correlation_id=envelope.correlation_id,
                previous_strategies=list(previous),
            )
            self._finish(envelope, goal, context, result, success=False)
            return result

        best: Optional[RecoveryResult] = None
        for adapter in self._adapters:
            try:
                result = adapter(envelope, context)
            except Exception:
                logger.warning(
                    "recovery adapter failed for %s", envelope.component_id,
                    exc_info=True,
                )
                continue
            if result is None:
                continue
            if result.verdict not in _BLOCKED_VERDICTS or best is None:
                best = result
            if result.verdict not in _BLOCKED_VERDICTS:
                break

        if best is None:
            best = self._generic_ladder(context, [signature], previous)

        self._finish(envelope, goal, context, best, success=(
            best.verdict == RecoveryVerdict.RECOVERED
        ))
        return best

    def _finish(
        self,
        envelope: FailureEnvelope,
        goal: Optional[GoalState],
        context: RecoveryContext,
        result: RecoveryResult,
        *,
        success: bool,
    ) -> None:
        signature = envelope.signature()
        self._record_strategy(signature, result.strategy, success=success)
        if goal is not None:
            goal.recovery_history.append(
                {
                    "failure_id": envelope.failure_id,
                    "strategy": result.strategy,
                    "verdict": result.verdict.value,
                    "detail": result.detail,
                    "attempt_count": result.attempts,
                    "timestamp": time.time(),
                }
            )
            goal.touch(progress=True)
        emit_reliability_event(
            self._event_sink,
            "reliability.recovery",
            verdict=result.verdict.value,
            strategy=result.strategy,
            component_type=envelope.component_type,
            component_id=envelope.component_id,
            operation=envelope.operation,
            failure_class=envelope.failure_class.value,
            goal_id=envelope.goal_id,
            correlation_id=envelope.correlation_id,
            attempt_count=result.attempts,
            detail=result.detail,
            next_action=result.next_action,
        )

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def snapshot(self) -> Dict[str, Any]:
        return {
            "strategies": dict(self._strategy_history),
            "quarantine": dict(self._quarantine),
        }


def default_retry_policy(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    multiplier: float = 2.0,
    jitter: float = 0.25,
) -> Callable[[int], float]:
    """Return a delay-seconds function for a given attempt index."""

    def delay_for(attempt_index: int) -> float:
        delay = min(max_delay, base_delay * (multiplier ** max(0, attempt_index - 1)))
        if jitter > 0:
            delay *= 1.0 + random.uniform(-jitter, jitter)
        return max(0.0, delay)

    return delay_for