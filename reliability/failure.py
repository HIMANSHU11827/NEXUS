"""Canonical failure envelope and classification for Nexus.

Every subsystem (tools, skills, plugins, MCP, providers, workers, agents)
reports failures through :class:`FailureEnvelope`. The recovery engine in
``reliability.recovery`` consumes these envelopes; individual components
never need to implement their own retry/classification logic.

Classification reuses ``providers.reliability.classify_failure`` when
available and falls back to type- and text-based heuristics so this module
stays importable even when provider modules are broken.
"""

from __future__ import annotations

import json
import socket
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from models.providers.core.reliability import redact_secrets
except Exception:  # pragma: no cover - defensive import fallback

    _SECRET_PATTERNS = [
        r"sk-[A-Za-z0-9\-_]{8,}",
        r"AKIA[0-9A-Z]{16}",
        r"(?:bearer\s+)[A-Za-z0-9._\-]+",
        r"(?:password\s*[=:]\s*)[^\s\"']+",
        r"(?:api[_-]?key\s*[=:]\s*)[^\s\"']+",
        r"xox[baprs]-[A-Za-z0-9\-]{10,}",
    ]

    def redact_secrets(value: str) -> str:
        import re

        for pattern in _SECRET_PATTERNS:
            value = re.sub(pattern, "***REDACTED***", value, flags=re.IGNORECASE)
        return value


class FailureClass(str, Enum):
    """Unified failure taxonomy shared by every Nexus subsystem."""

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    PERMISSION_REQUIRED = "permission_required"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    DNS = "dns"
    PROVIDER_OUTAGE = "provider_outage"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    TOOL_UNAVAILABLE = "tool_unavailable"
    PLUGIN_INIT = "plugin_init"
    SKILL_LOAD = "skill_load"
    MCP_TRANSPORT = "mcp_transport"
    MCP_PROTOCOL = "mcp_protocol"
    TOOL_EXECUTION = "tool_execution"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    MALFORMED_TOOL_CALL = "malformed_tool_call"
    EMPTY_MODEL_RESPONSE = "empty_model_response"
    STREAM_INTERRUPTION = "stream_interruption"
    CONTEXT_OVERFLOW = "context_overflow"
    MEMORY_FAILURE = "memory_failure"
    DATABASE_FAILURE = "database_failure"
    QUEUE_FAILURE = "queue_failure"
    WORKER_CRASH = "worker_crash"
    SUBAGENT_CRASH = "subagent_crash"
    DEADLOCK = "deadlock"
    STALL = "stall"
    REPEATED_NO_PROGRESS = "repeated_no_progress"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    SECURITY_POLICY_REJECTION = "security_policy_rejection"
    USER_CANCELLATION = "user_cancellation"
    NON_RECOVERABLE_EXTERNAL = "non_recoverable_external"
    UNKNOWN = "unknown"


_RETRYABLE_CLASSES = {
    FailureClass.RATE_LIMIT,
    FailureClass.TIMEOUT,
    FailureClass.NETWORK,
    FailureClass.DNS,
    FailureClass.PROVIDER_OUTAGE,
    FailureClass.DEPENDENCY_UNAVAILABLE,
    FailureClass.TOOL_EXECUTION,
    FailureClass.STREAM_INTERRUPTION,
    FailureClass.MEMORY_FAILURE,
    FailureClass.DATABASE_FAILURE,
    FailureClass.QUEUE_FAILURE,
    FailureClass.WORKER_CRASH,
    FailureClass.SUBAGENT_CRASH,
    FailureClass.MCP_TRANSPORT,
    FailureClass.PLUGIN_INIT,
    FailureClass.SKILL_LOAD,
    FailureClass.EMPTY_MODEL_RESPONSE,
    FailureClass.INVALID_MODEL_OUTPUT,
    FailureClass.UNKNOWN,
}

_TRANSIENT_CLASSES = {
    FailureClass.RATE_LIMIT,
    FailureClass.TIMEOUT,
    FailureClass.NETWORK,
    FailureClass.DNS,
    FailureClass.PROVIDER_OUTAGE,
    FailureClass.DEPENDENCY_UNAVAILABLE,
    FailureClass.STREAM_INTERRUPTION,
    FailureClass.MCP_TRANSPORT,
    FailureClass.WORKER_CRASH,
}

_TERMINAL_CLASSES = {
    FailureClass.USER_CANCELLATION,
    FailureClass.NON_RECOVERABLE_EXTERNAL,
    FailureClass.SECURITY_POLICY_REJECTION,
}

_DEFAULT_RECOMMENDATIONS: Dict[FailureClass, str] = {
    FailureClass.VALIDATION: "correct the tool arguments using the actionable error and retry once",
    FailureClass.AUTHENTICATION: "refresh credentials, then retry the operation",
    FailureClass.AUTHORIZATION: "request elevated permission from the user",
    FailureClass.PERMISSION_REQUIRED: "request user approval; the step is resumable",
    FailureClass.RATE_LIMIT: "backoff retry with jitter, then switch provider or endpoint",
    FailureClass.TIMEOUT: "retry with a longer timeout, then fall back to an equivalent tool",
    FailureClass.NETWORK: "retry with backoff; if persistent, switch provider or verify connectivity",
    FailureClass.DNS: "retry once, then verify DNS resolution and switch endpoint",
    FailureClass.PROVIDER_OUTAGE: "switch to a fallback provider, then re-probe the original",
    FailureClass.DEPENDENCY_UNAVAILABLE: "install, configure, or replace the missing dependency",
    FailureClass.TOOL_UNAVAILABLE: "select an alternate tool or repair the failing tool",
    FailureClass.PLUGIN_INIT: "disable the failing plugin, roll back partial registration, continue runtime",
    FailureClass.SKILL_LOAD: "validate skill metadata and referenced files, then repair or disable the skill",
    FailureClass.MCP_TRANSPORT: "reconnect the MCP server with backoff and refresh its tool list",
    FailureClass.MCP_PROTOCOL: "restart the MCP server and refresh capabilities",
    FailureClass.TOOL_EXECUTION: "retry transient failures; quarantine the tool after repeated failure",
    FailureClass.INVALID_MODEL_OUTPUT: "repair or regenerate the model output",
    FailureClass.MALFORMED_TOOL_CALL: "repair the malformed tool call arguments",
    FailureClass.EMPTY_MODEL_RESPONSE: "retry the model call once, then switch provider",
    FailureClass.STREAM_INTERRUPTION: "determine whether the remote operation completed; resume or safely repeat",
    FailureClass.CONTEXT_OVERFLOW: "compact context or switch to a larger-context model",
    FailureClass.MEMORY_FAILURE: "preserve working state, use an alternative store, repair persistence",
    FailureClass.DATABASE_FAILURE: "retry with backoff; verify database availability before continuing",
    FailureClass.QUEUE_FAILURE: "retry the queue operation; verify queue health",
    FailureClass.WORKER_CRASH: "reclaim the worker's leased tasks and restart the worker",
    FailureClass.SUBAGENT_CRASH: "preserve partial output, reclaim its task, assign to another worker",
    FailureClass.DEADLOCK: "release stale locks and replan the affected step",
    FailureClass.STALL: "freeze the ineffective strategy and replan with different assumptions",
    FailureClass.REPEATED_NO_PROGRESS: "switch strategy, escalate to a diagnostic agent, replan",
    FailureClass.RESOURCE_EXHAUSTION: "reduce concurrency or split the task",
    FailureClass.SECURITY_POLICY_REJECTION: "do not retry; request policy exception or user consent",
    FailureClass.USER_CANCELLATION: "preserve state as resumable; do not auto-retry",
    FailureClass.NON_RECOVERABLE_EXTERNAL: "persist a resumable blocked state and request external action",
    FailureClass.UNKNOWN: "capture full diagnostics, retry once, then delegate diagnosis",
}

_MISSING = object()


def _truncate(value: str, limit: int) -> str:
    if value is None:
        return ""
    value = str(value)
    return value if len(value) <= limit else value[:limit]


def _redact(value: Any) -> str:
    try:
        return redact_secrets(str(value))
    except Exception:
        return str(value)


@dataclass
class FailureEnvelope:
    """Normalized, structured description of a single failure."""

    failure_id: str
    component_type: str
    component_id: str
    operation: str
    failure_class: FailureClass
    message: str
    timestamp: float
    goal_id: Optional[str] = None
    task_id: Optional[str] = None
    attempt_id: Optional[str] = None
    error_code: str = ""
    root_cause_hint: str = ""
    raw_exception: Optional[str] = None
    stack_trace: Optional[str] = None
    input_summary: str = ""
    provider: Optional[str] = None
    model: Optional[str] = None
    tool: Optional[str] = None
    agent: Optional[str] = None
    duration_ms: float = 0.0
    is_transient: bool = False
    is_retryable: bool = False
    is_user_action_required: bool = False
    is_security_related: bool = False
    side_effect_status: str = "none"
    idempotency_key: Optional[str] = None
    recommended_recovery: str = ""
    attempt_count: int = 1
    previous_strategies: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "component_type": self.component_type,
            "component_id": self.component_id,
            "operation": self.operation,
            "failure_class": self.failure_class.value,
            "error_code": self.error_code,
            "message": self.message,
            "root_cause_hint": self.root_cause_hint,
            "provider": self.provider,
            "model": self.model,
            "tool": self.tool,
            "agent": self.agent,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "is_transient": self.is_transient,
            "is_retryable": self.is_retryable,
            "is_user_action_required": self.is_user_action_required,
            "is_security_related": self.is_security_related,
            "side_effect_status": self.side_effect_status,
            "idempotency_key": self.idempotency_key,
            "recommended_recovery": self.recommended_recovery,
            "attempt_count": self.attempt_count,
            "previous_strategies": list(self.previous_strategies),
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailureEnvelope":
        try:
            failure_class = FailureClass(str(data.get("failure_class", "unknown")))
        except ValueError:
            failure_class = FailureClass.UNKNOWN
        kwargs: Dict[str, Any] = {
            key: data.get(key)
            for key in (
                "goal_id", "task_id", "attempt_id", "error_code",
                "root_cause_hint", "provider", "model", "tool", "agent",
                "idempotency_key", "correlation_id", "input_summary",
            )
        }
        return cls(
            failure_id=str(data.get("failure_id") or uuid.uuid4().hex[:12]),
            component_type=str(data.get("component_type") or "unknown"),
            component_id=str(data.get("component_id") or "unknown"),
            operation=str(data.get("operation") or ""),
            failure_class=failure_class,
            message=_redact(data.get("message") or ""),
            timestamp=float(data.get("timestamp") or 0.0),
            raw_exception=_truncate(_redact(data.get("raw_exception") or ""), 2000) or None,
            stack_trace=_truncate(_redact(data.get("stack_trace") or ""), 4000) or None,
            duration_ms=float(data.get("duration_ms") or 0.0),
            is_transient=bool(data.get("is_transient")),
            is_retryable=bool(data.get("is_retryable")),
            is_user_action_required=bool(data.get("is_user_action_required")),
            is_security_related=bool(data.get("is_security_related")),
            side_effect_status=str(data.get("side_effect_status") or "none"),
            recommended_recovery=str(data.get("recommended_recovery") or ""),
            attempt_count=int(data.get("attempt_count") or 1),
            previous_strategies=[
                str(item) for item in (data.get("previous_strategies") or [])
            ],
            **kwargs,
        )

    def with_attempt(
        self, attempt_count: int, previous_strategies: List[str]
    ) -> "FailureEnvelope":
        """Return a copy carrying updated retry bookkeeping."""
        import copy

        clone = copy.copy(self)
        clone.attempt_count = attempt_count
        clone.previous_strategies = list(previous_strategies)
        return clone

    def signature(self) -> str:
        """Stable key used to detect repeated identical failures."""
        return "|".join(
            [
                self.component_type,
                self.component_id,
                self.operation,
                self.failure_class.value,
                self.error_code,
            ]
        )


def _classify_by_text(message: str, hint: str) -> Optional[FailureClass]:
    lowered = (message or "").lower()
    combined = f"{lowered} {hint.lower()}"
    if any(token in combined for token in ("rate limit", "429", "too many requests", "throttl")):
        return FailureClass.RATE_LIMIT
    if "timed out" in combined or "timeout" in combined:
        return FailureClass.TIMEOUT
    if "dns" in combined or "name or service not known" in combined:
        return FailureClass.DNS
    if any(token in combined for token in ("connection refused", "connection reset", "network", "unreachable", "socket")):
        return FailureClass.NETWORK
    if any(token in combined for token in ("quota", "billing", "insufficient_quota", "402")):
        return FailureClass.RESOURCE_EXHAUSTION
    if any(token in combined for token in ("unauthorized", "authentication", "invalid api key", "401", "403")):
        return FailureClass.AUTHENTICATION
    if any(token in combined for token in ("permission", "approval required", "consent")):
        return FailureClass.PERMISSION_REQUIRED
    if any(token in combined for token in ("unavailable", "overloaded", "503", "502", "500", "temporarily")):
        return FailureClass.PROVIDER_OUTAGE
    if "empty response" in combined or "no output" in combined:
        return FailureClass.EMPTY_MODEL_RESPONSE
    return None


def classify_exception(exc: BaseException, hint: str = "") -> FailureClass:
    """Classify an exception into the unified taxonomy.

    Prefers ``providers.reliability.classify_failure`` and falls back to
    type- and text-based heuristics so classification never raises.
    """
    try:
        from models.providers.core.reliability import classify_failure

        provider_class = classify_failure(exc, str(hint or ""))
        if provider_class is not None:
            name = str(getattr(provider_class, "name", "")).lower()
            mapping = {
                "auth_error": FailureClass.AUTHENTICATION,
                "rate_limit": FailureClass.RATE_LIMIT,
                "timeout": FailureClass.TIMEOUT,
                "network": FailureClass.NETWORK,
                "temporary_outage": FailureClass.PROVIDER_OUTAGE,
                "context_overflow": FailureClass.CONTEXT_OVERFLOW,
                "billing_quota": FailureClass.RESOURCE_EXHAUSTION,
                "malformed": FailureClass.INVALID_MODEL_OUTPUT,
            }
            if name in mapping:
                return mapping[name]
    except Exception:
        pass

    try:
        import asyncio

        if isinstance(exc, asyncio.CancelledError):
            return FailureClass.USER_CANCELLATION
    except Exception:
        pass
    if isinstance(exc, (TimeoutError,)):
        return FailureClass.TIMEOUT
    if isinstance(exc, (ConnectionError, BrokenPipeError)):
        return FailureClass.NETWORK
    if isinstance(exc, (socket.gaierror,)):
        return FailureClass.DNS
    if isinstance(exc, (PermissionError,)):
        return FailureClass.AUTHORIZATION
    if isinstance(exc, (ValueError, TypeError, KeyError)) and "tool" not in hint.lower():
        return FailureClass.VALIDATION
    if isinstance(exc, (MemoryError,)):
        return FailureClass.RESOURCE_EXHAUSTION

    from_type = _classify_by_text(str(exc), hint)
    if from_type is not None:
        return from_type
    return FailureClass.UNKNOWN


def asyncio_CancelledError_type():  # pragma: no cover - compatibility shim
    return None


def envelope_from_exception(
    exc: BaseException,
    *,
    component_type: str,
    component_id: str,
    operation: str,
    goal_id: Optional[str] = None,
    task_id: Optional[str] = None,
    tool: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    agent: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    correlation_id: Optional[str] = None,
    side_effect_status: str = "none",
    is_retryable: Optional[bool] = None,
    is_transient: Optional[bool] = None,
    recommended_recovery: str = "",
    input_summary: str = "",
    error_code: str = "",
    duration_ms: float = 0.0,
    failure_class: Optional[FailureClass] = None,
) -> FailureEnvelope:
    """Build a :class:`FailureEnvelope` from an exception.

    ``failure_class`` overrides automatic classification when the caller
    already knows the failure class (e.g. from a provider status code).
    """
    import asyncio as _asyncio
    import time as _time

    if failure_class is None:
        failure_class = classify_exception(exc)
    message = _redact(str(exc) or failure_class.value)
    if is_retryable is None:
        is_retryable = failure_class in _RETRYABLE_CLASSES
    if is_transient is None:
        is_transient = failure_class in _TRANSIENT_CLASSES
    if not recommended_recovery:
        recommended_recovery = _DEFAULT_RECOMMENDATIONS.get(failure_class, "")
    stack = None
    if isinstance(exc, Exception):
        stack = _truncate(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            4000,
        )
    return FailureEnvelope(
        failure_id=uuid.uuid4().hex[:12],
        goal_id=goal_id,
        task_id=task_id,
        component_type=component_type,
        component_id=component_id,
        operation=operation,
        failure_class=failure_class,
        error_code=error_code or failure_class.value,
        message=message,
        root_cause_hint=_classify_by_text(str(exc), "") and failure_class.value or "",
        raw_exception=_truncate(message, 2000) or None,
        stack_trace=stack,
        input_summary=_truncate(input_summary, 1000),
        provider=provider,
        model=model,
        tool=tool,
        agent=agent,
        timestamp=_time.time(),
        duration_ms=duration_ms,
        is_transient=is_transient,
        is_retryable=is_retryable,
        is_user_action_required=failure_class == FailureClass.PERMISSION_REQUIRED,
        is_security_related=failure_class
        in {
            FailureClass.SECURITY_POLICY_REJECTION,
            FailureClass.AUTHENTICATION,
            FailureClass.AUTHORIZATION,
        },
        side_effect_status=side_effect_status,
        idempotency_key=idempotency_key,
        recommended_recovery=recommended_recovery,
        attempt_count=1,
        correlation_id=correlation_id,
    )


def is_recoverable(envelope: FailureEnvelope) -> bool:
    """A failure is recoverable unless it is a user cancellation, a hard
    security rejection, or a permanent external restriction."""
    return envelope.failure_class not in _TERMINAL_CLASSES


def serialize_envelope(envelope: FailureEnvelope) -> str:
    return json.dumps(envelope.to_dict(), default=str)


def deserialize_envelope(raw: str) -> Optional[FailureEnvelope]:
    try:
        return FailureEnvelope.from_dict(json.loads(raw))
    except Exception:
        return None