"""Redacted, bounded provider-attempt telemetry.

Provider failures are operationally important, but raw exception text can
contain credentials, URLs with query secrets, or vendor payloads.  This
recorder keeps only safe classification and routing metadata in memory and
supports an optional callback for the host runtime to persist or emit it.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Any, Callable, Deque, Dict, Optional

from models.providers.core.reliability import Classification, redact_secrets


@dataclass(frozen=True)
class ProviderAttempt:
    provider_id: str
    credential_id: str = ""
    profile: str = ""
    model: str = ""
    attempt: int = 1
    status: str = "started"
    failure_class: str = ""
    strategy: str = ""
    reason: str = ""
    duration_ms: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ProviderAttemptRecorder:
    """Thread-safe bounded recorder for provider routing diagnostics."""

    def __init__(self, max_entries: int = 128,
                 sink: Optional[Callable[[Dict[str, Any]], Any]] = None) -> None:
        self._entries: Deque[ProviderAttempt] = deque(maxlen=max(1, int(max_entries)))
        self._lock = RLock()
        self.sink = sink

    def record(self, provider_id: Any, *, credential_id: Any = "", profile: Any = "", model: Any = "",
               attempt: int = 1, status: str = "started",
               classification: Optional[Classification] = None,
               reason: Any = "", duration_ms: float = 0.0) -> ProviderAttempt:
        classification = classification or None
        safe_reason = redact_secrets(str(reason or ""))[:240]
        entry = ProviderAttempt(
            provider_id=str(provider_id or "unknown")[:80],
            credential_id=str(credential_id or "")[:120],
            profile=str(profile or "")[:80],
            model=str(model or "")[:160],
            attempt=max(1, int(attempt or 1)),
            status=str(status or "started")[:32],
            failure_class=str(getattr(getattr(classification, "failure_class", None), "value", "") or "")[:64],
            strategy=str(getattr(getattr(classification, "strategy", None), "value", "") or "")[:64],
            reason=safe_reason,
            duration_ms=round(max(0.0, float(duration_ms or 0.0)), 3),
            timestamp=time.time(),
        )
        with self._lock:
            self._entries.append(entry)
        if self.sink is not None:
            try:
                self.sink(entry.to_dict())
            except Exception:
                pass
        return entry

    def snapshot(self) -> list[Dict[str, Any]]:
        with self._lock:
            return [entry.to_dict() for entry in self._entries]


__all__ = ["ProviderAttempt", "ProviderAttemptRecorder"]
