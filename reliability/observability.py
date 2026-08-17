"""Observability helpers: correlation IDs, structured logs, reliability events.

Every subsystem can emit one-line structured logs and reliability events that
carry a correlation ID, making retries, fallbacks, and recovery decisions
traceable end to end. Never raises and never logs secrets.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional

try:
    from providers.reliability import redact_secrets
except Exception:  # pragma: no cover - defensive fallback

    def redact_secrets(value: str) -> str:
        return str(value)


logger = logging.getLogger("nexus.reliability")

correlation_id: ContextVar[Optional[str]] = ContextVar(
    "nexus_correlation_id", default=None
)


def new_correlation_id() -> str:
    return f"corr_{uuid.uuid4().hex[:16]}"


def set_correlation_id(value: str) -> None:
    correlation_id.set(value)


def get_correlation_id() -> Optional[str]:
    return correlation_id.get()


def reset_correlation_id() -> None:
    correlation_id.set(None)


def truncate(text: Any, limit: int) -> str:
    try:
        value = str(text)
    except Exception:
        value = repr(text)
    return value if len(value) <= limit else value[:limit]


def structured_log(level: str, component: str, event: str, **fields: Any) -> None:
    """Emit a one-line structured log record with correlation ID.

    Field values are stringified, truncated to 500 chars, and secrets are
    redacted. Never raises.
    """
    try:
        try:
            redacted = {key: redact_secrets(truncate(value, 500)) for key, value in fields.items()}
        except Exception:
            redacted = {key: truncate(value, 500) for key, value in fields.items()}
        corr = correlation_id.get()
        parts = [f"corr={corr}" if corr else "corr=-", component, event]
        parts.extend(f"{key}={value}" for key, value in sorted(redacted.items()))
        message = " ".join(parts)
        normalized = str(level).lower()
        if normalized == "debug":
            logger.debug(message)
        elif normalized in ("warning", "warn"):
            logger.warning(message)
        elif normalized == "error":
            logger.error(message)
        elif normalized == "critical":
            logger.critical(message)
        else:
            logger.info(message)
    except Exception:
        pass


def emit_reliability_event(
    sink: Optional[Callable[[Dict[str, Any]], None]],
    event_type: str,
    **payload: Any,
) -> None:
    """Emit a structured reliability event to a sink (guarded)."""
    if sink is None:
        return
    try:
        event = {
            "event_type": event_type,
            "correlation_id": correlation_id.get(),
            "timestamp": time.time(),
            **payload,
        }
        sink(event)
    except Exception:
        logger.debug("reliability event sink failed", exc_info=True)