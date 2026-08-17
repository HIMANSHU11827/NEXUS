"""Nexus reliability core: failure envelopes, state machine, goal store,
recovery engine, progress tracking, and observability helpers.

The reliability package gives every Nexus subsystem a shared vocabulary for
failures and recovery: components report structured
:class:`~reliability.failure.FailureEnvelope` instances, the
:class:`~reliability.recovery.RecoveryEngine` selects bounded recovery
strategies, and the :class:`~reliability.states.RunStateMachine` records
validated runtime state transitions. A recoverable component failure must
create a recovery operation, never terminate the runtime.
"""

from reliability.failure import (
    FailureClass,
    FailureEnvelope,
    classify_exception,
    deserialize_envelope,
    envelope_from_exception,
    is_recoverable,
    serialize_envelope,
)
from reliability.goal import GoalState, GoalStep, GoalStore
from reliability.observability import (
    correlation_id,
    emit_reliability_event,
    get_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
    structured_log,
    truncate,
)
from reliability.progress import ProgressTracker, StallSignal
from reliability.recovery import (
    RecoveryContext,
    RecoveryEngine,
    RecoveryResult,
    RecoveryVerdict,
    default_retry_policy,
)
from reliability.states import (
    RECOVERABLE_FROM,
    TRANSITION_TABLE,
    RunState,
    RunStateMachine,
    TransitionRecord,
)

__all__ = [
    "FailureClass",
    "FailureEnvelope",
    "classify_exception",
    "deserialize_envelope",
    "envelope_from_exception",
    "is_recoverable",
    "serialize_envelope",
    "GoalState",
    "GoalStep",
    "GoalStore",
    "correlation_id",
    "emit_reliability_event",
    "get_correlation_id",
    "new_correlation_id",
    "reset_correlation_id",
    "set_correlation_id",
    "structured_log",
    "truncate",
    "ProgressTracker",
    "StallSignal",
    "RecoveryContext",
    "RecoveryEngine",
    "RecoveryResult",
    "RecoveryVerdict",
    "default_retry_policy",
    "RECOVERABLE_FROM",
    "TRANSITION_TABLE",
    "RunState",
    "RunStateMachine",
    "TransitionRecord",
]