"""Provider health, capability, and latency tracking."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from providers.reliability import (
    BreakerState,
    CircuitBreaker,
    classify_failure,
    redact_secrets,
)

# A provider marked unhealthy is excluded from the mesh only for this long;
# without a decay window a single transient failure banned it permanently.
DEGRADED_TTL_SECONDS = 60.0
logger = logging.getLogger(__name__)


@dataclass
class ProviderCapability:
    text: bool = True
    streaming: bool = True
    vision: bool = False
    local: bool = False
    tool_calling: bool = False
    max_context: int = 0


@dataclass
class ProviderHealth:
    provider_id: str
    healthy: bool
    latency_ms: Optional[float] = None
    last_error: str = ""
    checked_at: float = field(default_factory=time.time)
    capability: ProviderCapability = field(default_factory=ProviderCapability)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["capability"] = asdict(self.capability)
        return data


class ProviderHealthRegistry:
    """Provider telemetry with optional cross-process SQLite persistence."""

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._health: Dict[str, ProviderHealth] = {}
        self._lock = threading.RLock()
        self._store_path = os.path.abspath(store_path) if store_path else ""
        if self._store_path:
            try:
                os.makedirs(os.path.dirname(self._store_path), exist_ok=True)
                with self._connect() as connection:
                    connection.execute(
                        """CREATE TABLE IF NOT EXISTS provider_health (
                            provider_id TEXT PRIMARY KEY,
                            healthy INTEGER NOT NULL,
                            latency_ms REAL,
                            last_error TEXT NOT NULL DEFAULT '',
                            checked_at REAL NOT NULL,
                            capability_json TEXT NOT NULL DEFAULT '{}'
                        )"""
                    )
            except Exception:
                logger.warning("provider health persistence unavailable", exc_info=True)
                self._store_path = ""

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._store_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ProviderHealth:
        try:
            raw_capability = json.loads(str(row["capability_json"] or "{}"))
            capability = ProviderCapability(**{
                key: raw_capability[key]
                for key in ProviderCapability.__dataclass_fields__
                if key in raw_capability
            })
        except Exception:
            capability = ProviderCapability()
        return ProviderHealth(
            provider_id=str(row["provider_id"]),
            healthy=bool(row["healthy"]),
            latency_ms=row["latency_ms"],
            last_error=str(row["last_error"] or ""),
            checked_at=float(row["checked_at"] or 0.0),
            capability=capability,
        )

    def _persist_locked(self, record: ProviderHealth) -> None:
        if not self._store_path:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO provider_health
                    (provider_id, healthy, latency_ms, last_error, checked_at, capability_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider_id) DO UPDATE SET
                      healthy=excluded.healthy,
                      latency_ms=excluded.latency_ms,
                      last_error=excluded.last_error,
                      checked_at=excluded.checked_at,
                      capability_json=excluded.capability_json
                    WHERE excluded.checked_at >= provider_health.checked_at""",
                    (
                        record.provider_id,
                        int(record.healthy),
                        record.latency_ms,
                        record.last_error,
                        record.checked_at,
                        json.dumps(asdict(record.capability), sort_keys=True),
                    ),
                )
        except Exception:
            logger.debug("provider health persistence write failed", exc_info=True)

    def _read_persisted_locked(self, provider_id: str) -> Optional[ProviderHealth]:
        if not self._store_path:
            return None
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM provider_health WHERE provider_id=?",
                    (str(provider_id),),
                ).fetchone()
            return self._from_row(row) if row is not None else None
        except Exception:
            logger.debug("provider health persistence read failed", exc_info=True)
            return None

    def mark_success(self, provider_id: str, latency_ms: float, capability: Optional[ProviderCapability] = None) -> None:
        with self._lock:
            previous = self._health.get(provider_id) or self._read_persisted_locked(provider_id)
            record = ProviderHealth(
                provider_id=provider_id,
                healthy=True,
                latency_ms=latency_ms,
                capability=capability or (previous.capability if previous else ProviderCapability()),
            )
            self._health[provider_id] = record
            self._persist_locked(record)

    def mark_failure(self, provider_id: str, error: Exception | str, capability: Optional[ProviderCapability] = None) -> None:
        with self._lock:
            previous = self._health.get(provider_id) or self._read_persisted_locked(provider_id)
            record = ProviderHealth(
                provider_id=provider_id,
                healthy=False,
                last_error=self.normalize_error(error),
                capability=capability or (previous.capability if previous else ProviderCapability()),
            )
            self._health[provider_id] = record
            self._persist_locked(record)

    def get(self, provider_id: str) -> Optional[ProviderHealth]:
        with self._lock:
            local = self._health.get(provider_id)
            persisted = self._read_persisted_locked(provider_id)
            if persisted is not None and (local is None or persisted.checked_at >= local.checked_at):
                self._health[provider_id] = persisted
                return persisted
            return local

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            records = dict(self._health)
            if self._store_path:
                try:
                    with self._connect() as connection:
                        rows = connection.execute("SELECT * FROM provider_health").fetchall()
                    for row in rows:
                        persisted = self._from_row(row)
                        current = records.get(persisted.provider_id)
                        if current is None or persisted.checked_at >= current.checked_at:
                            records[persisted.provider_id] = persisted
                except Exception:
                    logger.debug("provider health persistence snapshot failed", exc_info=True)
            return [h.to_dict() for h in records.values()]

    def is_degraded(self, provider_id: str) -> bool:
        with self._lock:
            health = self.get(provider_id)
        if not health or health.healthy:
            return False
        return (time.time() - health.checked_at) < DEGRADED_TTL_SECONDS

    @staticmethod
    def normalize_error(error: Exception | str) -> str:
        """Classify and redact. Never returns raw credential material."""
        classification = classify_failure(
            error if isinstance(error, BaseException) else None,
            body=None if isinstance(error, BaseException) else error,
        )
        detail = redact_secrets(classification.message)[:400]
        return f"{classification.failure_class.value.upper()}: {detail}" if detail \
            else classification.failure_class.value.upper()


class ProviderCapabilityRegistry:
    """Static model/provider capability registry used by the router.

    It is intentionally conservative. Unknown providers are treated as text
    providers with no tool/vision claim until proven otherwise.
    """

    DEFAULTS: Dict[str, ProviderCapability] = {
        "openrouter": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "openai": ProviderCapability(text=True, streaming=True, vision=True, tool_calling=True, max_context=128000),
        "anthropic": ProviderCapability(text=True, streaming=True, vision=True, tool_calling=True, max_context=200000),
        "gemini": ProviderCapability(text=True, streaming=True, vision=True, tool_calling=True, max_context=1000000),
        "groq": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=131000),
        "mistral": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "qwen": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "deepseek": ProviderCapability(text=True, streaming=True, tool_calling=True, max_context=128000),
        "perplexity": ProviderCapability(text=True, streaming=True, tool_calling=False, max_context=128000),
        "ollama": ProviderCapability(text=True, streaming=True, local=True, max_context=32000),
        "lm_studio": ProviderCapability(text=True, streaming=True, local=True, tool_calling=True, max_context=32000),
        "llama_cpp": ProviderCapability(text=True, streaming=True, local=True, max_context=32000),
        "vlm": ProviderCapability(text=True, streaming=False, vision=True, max_context=128000),
    }

    def get(self, provider_id: str) -> ProviderCapability:
        return self.DEFAULTS.get(str(provider_id or "").lower(), ProviderCapability())

    def supports(self, provider_id: str, *, streaming: bool = False, vision: bool = False, local: Optional[bool] = None) -> bool:
        capability = self.get(provider_id)
        if streaming and not capability.streaming:
            return False
        if vision and not capability.vision:
            return False
        if local is not None and capability.local != local:
            return False
        return capability.text

    def choose(
        self,
        candidates: List[str],
        health: ProviderHealthRegistry,
        *,
        streaming: bool = False,
        vision: bool = False,
        prefer_local: bool = False,
    ) -> List[str]:
        viable = [
            c for c in candidates
            if self.supports(c, streaming=streaming, vision=vision)
            and not health.is_degraded(c)
        ]
        if prefer_local:
            viable.sort(key=lambda c: (not self.get(c).local, -self.get(c).max_context))
        else:
            viable.sort(key=lambda c: (self.get(c).local, -self.get(c).max_context))
        return viable


class ComponentBreakerRegistry:
    """Per-component circuit breakers for non-provider work.

    Keyed by component name (``tool`` / ``plugin`` / ``mcp`` / ``gateway``, or
    any operator-chosen namespace). A component opens after
    ``failure_threshold`` consecutive failures and re-enters service through a
    half-open probe after ``cooldown`` seconds (default 30s). Purely
    in-memory, stdlib-only, thread-safe. ``tools`` is preseeded (empty) so tool
    layers can attach state without a first-touch creation race.
    """

    DEFAULT_FAILURE_THRESHOLD = 3
    DEFAULT_COOLDOWN = 30.0

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown: float = DEFAULT_COOLDOWN,
        half_open_max_calls: int = 1,
        success_threshold: int = 1,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown = float(cooldown)
        self.half_open_max_calls = max(1, int(half_open_max_calls))
        self.success_threshold = max(1, int(success_threshold))
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()
        self._preseed()

    def _new_breaker(self, name: str) -> CircuitBreaker:
        return CircuitBreaker(
            provider_id=name,
            failure_threshold=self.failure_threshold,
            cooldown=self.cooldown,
            half_open_max_calls=self.half_open_max_calls,
            success_threshold=self.success_threshold,
        )

    def _preseed(self) -> None:
        """Warm empty registry key(s) without ever tripping any breaker."""
        for name in ("tools",):
            if name not in self._breakers:
                self._breakers[name] = self._new_breaker(name)

    def get(self, component: str) -> CircuitBreaker:
        """Fetch the breaker for a component, creating it when first seen."""
        key = str(component or "unknown")
        with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = self._new_breaker(key)
                self._breakers[key] = breaker
            return breaker

    def record_success(self, component: str) -> None:
        """Mark one successful call for a component (closes a half-open probe)."""
        self.get(component).record_success()

    def record_failure(self, component: str) -> None:
        """Mark one failed call; opens the component at the failure threshold."""
        self.get(component).record_failure()

    def is_open(self, component: str) -> bool:
        """True when the component is open or half-open (i.e. throttled)."""
        return self.get(component).state is not BreakerState.CLOSED

    def allows(self, component: str) -> bool:
        """True when the component may accept a call right now."""
        return self.get(component).allows()

    def reset(self, component: Optional[str] = None) -> None:
        """Reset one breaker, or every breaker when ``component`` is None."""
        if component is None:
            with self._lock:
                for breaker in self._breakers.values():
                    breaker.reset()
        else:
            self.get(component).reset()

    def snapshot(self, component: Optional[str] = None) -> Dict[str, Any]:
        """State of one (or every) component breaker for diagnostics."""
        if component is None:
            with self._lock:
                return {name: b.snapshot() for name, b in self._breakers.items()}
        return self.get(component).snapshot()


component_breakers = ComponentBreakerRegistry()

