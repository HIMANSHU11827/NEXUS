"""Provider reliability primitives.

Failure classification, secret redaction, retry with exponential backoff +
jitter (honouring ``Retry-After``) and a per-provider circuit breaker.

This module is wired into the real call path in :mod:`providers.router`.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, TypeVar, Union

logger = logging.getLogger("NEXUS_PROVIDER_RELIABILITY")

T = TypeVar("T")


# --------------------------------------------------------------------------
# Secret redaction
# --------------------------------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bgsk_[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bhf_[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{12,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}"),
    re.compile(r"\b(?:npm_|pypi-)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\bAIza[A-Za-z0-9._\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
    ),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|authorization)\b\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{8,}[\"']?"),
    re.compile(r"(?i)\b(?:token|secret|password)\b\s*[:=]\s*[\"']?[A-Za-z0-9._\-+/=]{16,}[\"']?"),
    re.compile(r"(?i)([?&](?:key|api_key|access_token)=)[A-Za-z0-9._\-]{8,}"),
]

_REDACTED = "***REDACTED***"


def redact_secrets(text: Any) -> str:
    """Remove API keys / bearer tokens from any text before logging or raising."""
    out = "" if text is None else str(text)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(_REDACTED, out)
    # Also scrub any live key material present in the environment.
    for name, value in os.environ.items():
        if not value or len(value) < 12:
            continue
        upper = name.upper()
        if upper.endswith("_API_KEY") or upper.endswith("_TOKEN") or upper.endswith("_SECRET"):
            out = out.replace(value, _REDACTED)
    return out


# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------

class FailureClass(str, Enum):
    AUTH_ERROR = "auth_error"
    BILLING_QUOTA = "billing_quota"
    RATE_LIMIT = "rate_limit"
    TEMPORARY_OUTAGE = "temporary_outage"
    CONTEXT_OVERFLOW = "context_overflow"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    INVALID_REQUEST = "invalid_request"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    MALFORMED_RESPONSE = "malformed_response"
    MODEL_MISSING = "model_missing"
    UNKNOWN = "unknown"


class Strategy(str, Enum):
    RETRY = "retry"
    BACKOFF = "backoff"
    FALLBACK_MODEL = "fallback_model"
    FALLBACK_PROVIDER = "fallback_provider"
    FAIL_FAST = "fail_fast"


@dataclass(frozen=True)
class Classification:
    failure_class: FailureClass
    retryable: bool
    strategy: Strategy
    retry_after: Optional[float] = None
    message: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "failure_class": self.failure_class.value,
            "retryable": self.retryable,
            "strategy": self.strategy.value,
            "retry_after": self.retry_after,
            "message": self.message,
        }


# class -> (retryable, strategy)
_CLASS_POLICY: Dict[FailureClass, Any] = {
    FailureClass.AUTH_ERROR: (False, Strategy.FAIL_FAST),
    FailureClass.BILLING_QUOTA: (False, Strategy.FALLBACK_PROVIDER),
    FailureClass.RATE_LIMIT: (True, Strategy.BACKOFF),
    FailureClass.TEMPORARY_OUTAGE: (True, Strategy.RETRY),
    FailureClass.CONTEXT_OVERFLOW: (False, Strategy.FALLBACK_MODEL),
    FailureClass.UNSUPPORTED_FEATURE: (False, Strategy.FALLBACK_MODEL),
    FailureClass.INVALID_REQUEST: (False, Strategy.FAIL_FAST),
    FailureClass.NETWORK_ERROR: (True, Strategy.RETRY),
    FailureClass.TIMEOUT: (True, Strategy.RETRY),
    FailureClass.MALFORMED_RESPONSE: (True, Strategy.RETRY),
    FailureClass.MODEL_MISSING: (False, Strategy.FALLBACK_MODEL),
    FailureClass.UNKNOWN: (True, Strategy.FALLBACK_PROVIDER),
}

_STATUS_MAP: Dict[int, FailureClass] = {
    400: FailureClass.INVALID_REQUEST,
    401: FailureClass.AUTH_ERROR,
    402: FailureClass.BILLING_QUOTA,
    403: FailureClass.AUTH_ERROR,
    404: FailureClass.MODEL_MISSING,
    408: FailureClass.TIMEOUT,
    409: FailureClass.TEMPORARY_OUTAGE,
    413: FailureClass.CONTEXT_OVERFLOW,
    422: FailureClass.INVALID_REQUEST,
    429: FailureClass.RATE_LIMIT,
    500: FailureClass.TEMPORARY_OUTAGE,
    502: FailureClass.TEMPORARY_OUTAGE,
    503: FailureClass.TEMPORARY_OUTAGE,
    504: FailureClass.TIMEOUT,
    529: FailureClass.TEMPORARY_OUTAGE,
}

_STATUS_RE = re.compile(r"\b(4\d\d|5\d\d)\b")


def parse_retry_after(value: Any) -> Optional[float]:
    """Parse a ``Retry-After`` header value (seconds or HTTP-date)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(text)
        if dt is None:
            return None
        delta = dt.timestamp() - time.time()
        return max(0.0, delta)
    except Exception:
        return None


def _classify_text(text: str) -> Optional[FailureClass]:
    low = text.lower()
    if not low:
        return None
    if "context length" in low or "context_length" in low or "too many tokens" in low \
            or "maximum context" in low or "reduce the length" in low or "context window" in low:
        return FailureClass.CONTEXT_OVERFLOW
    if (
        "billing" in low
        or "payment required" in low
        or "insufficient credits" in low
        or "credits exhausted" in low
        or "quota exceeded" in low
        or "quota exhausted" in low
        or "spending limit" in low
        or "billing limit" in low
    ):
        return FailureClass.BILLING_QUOTA
    if "rate limit" in low or "rate_limit" in low or "quota" in low or "too many requests" in low:
        return FailureClass.RATE_LIMIT
    if "unauthorized" in low or "invalid api key" in low or "authentication" in low \
            or "no api key" in low or "missing or invalid api key" in low or "forbidden" in low \
            or "invalid_api_key" in low or "credentials" in low:
        return FailureClass.AUTH_ERROR
    if "timed out" in low or "timeout" in low:
        return FailureClass.TIMEOUT
    if "does not support" in low or "unsupported" in low or "not supported" in low \
            or "tool use is not" in low:
        return FailureClass.UNSUPPORTED_FEATURE
    if "model not found" in low or "unknown model" in low or "no such model" in low \
            or "model_not_found" in low or "is not a valid model" in low:
        return FailureClass.MODEL_MISSING
    if "connection" in low or "network" in low or "dns" in low or "unreachable" in low \
            or "connection reset" in low or "ssl" in low:
        return FailureClass.NETWORK_ERROR
    if "json" in low and ("decode" in low or "expecting" in low or "parse" in low):
        return FailureClass.MALFORMED_RESPONSE
    if "malformed" in low or "unexpected response" in low or "empty response" in low:
        return FailureClass.MALFORMED_RESPONSE
    if "overload" in low or "service unavailable" in low or "server error" in low \
            or "bad gateway" in low or "temporarily" in low:
        return FailureClass.TEMPORARY_OUTAGE
    return None


def _classify_exception_type(error: BaseException) -> Optional[FailureClass]:
    name = type(error).__name__.lower()
    module = type(error).__module__.lower()
    if isinstance(error, TimeoutError) or "timeout" in name:
        return FailureClass.TIMEOUT
    if "connection" in name or "sslerror" in name or "proxyerror" in name:
        return FailureClass.NETWORK_ERROR
    if "jsondecodeerror" in name or (isinstance(error, ValueError) and "json" in module):
        return FailureClass.MALFORMED_RESPONSE
    if isinstance(error, OSError):
        return FailureClass.NETWORK_ERROR
    return None


def classify_failure(
    error: Optional[BaseException] = None,
    *,
    status_code: Optional[int] = None,
    body: Any = None,
    headers: Optional[Dict[str, Any]] = None,
) -> Classification:
    """Map an exception and/or an HTTP response to a :class:`Classification`."""
    text_parts = []
    if body is not None:
        text_parts.append(str(body))
    if error is not None:
        text_parts.append(str(error))
    raw_text = " ".join(text_parts)
    safe_text = redact_secrets(raw_text)[:500]

    retry_after = None
    if headers:
        lowered = {str(k).lower(): v for k, v in headers.items()}
        retry_after = parse_retry_after(
            lowered.get("retry-after")
            or lowered.get("x-ratelimit-reset-after")
        )

    failure: Optional[FailureClass] = None

    # 1. explicit status code wins for the unambiguous codes
    if status_code is None and raw_text:
        # Try to recover a status code embedded in a provider error string.
        match = _STATUS_RE.search(raw_text)
        if match and ("status" in raw_text.lower() or "returned" in raw_text.lower()
                      or "error" in raw_text.lower() or "http" in raw_text.lower()):
            status_code = int(match.group(1))

    if status_code is not None:
        failure = _STATUS_MAP.get(int(status_code))
        if failure is None:
            failure = (
                FailureClass.TEMPORARY_OUTAGE if 500 <= int(status_code) < 600
                else FailureClass.INVALID_REQUEST
            )
        # Body text can refine an ambiguous 400/404/422/500.
        if failure in (FailureClass.INVALID_REQUEST, FailureClass.MODEL_MISSING,
                       FailureClass.TEMPORARY_OUTAGE):
            refined = _classify_text(raw_text)
            if refined in (FailureClass.CONTEXT_OVERFLOW, FailureClass.MODEL_MISSING,
                           FailureClass.UNSUPPORTED_FEATURE, FailureClass.BILLING_QUOTA):
                failure = refined

    if failure is None:
        failure = _classify_text(raw_text)
    if failure is None and error is not None:
        failure = _classify_exception_type(error)
    if failure is None:
        failure = FailureClass.UNKNOWN

    retryable, strategy = _CLASS_POLICY[failure]
    return Classification(
        failure_class=failure,
        retryable=bool(retryable),
        strategy=strategy,
        retry_after=retry_after,
        message=safe_text,
    )


class ProviderCallError(RuntimeError):
    """Raised for a classified provider failure. Never contains secrets."""

    def __init__(self, classification: Classification, provider_id: str = ""):
        self.classification = classification
        self.provider_id = provider_id
        super().__init__(
            f"[{provider_id or 'provider'}] {classification.failure_class.value}: "
            f"{redact_secrets(classification.message)}"
        )


# --------------------------------------------------------------------------
# Retry policy
# --------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.25          # +/- fraction of the computed delay
    respect_retry_after: bool = True
    max_retry_after: float = 120.0

    def compute_delay(self, attempt: int, retry_after: Optional[float] = None,
                      rng: Optional[random.Random] = None) -> float:
        """Delay before retry number ``attempt`` (1 = after the first failure)."""
        rand = rng or random
        if self.respect_retry_after and retry_after is not None:
            return float(min(max(retry_after, 0.0), self.max_retry_after))
        exp = self.base_delay * (self.multiplier ** max(0, attempt - 1))
        exp = min(exp, self.max_delay)
        if self.jitter <= 0:
            return exp
        low = exp * (1.0 - self.jitter)
        high = exp * (1.0 + self.jitter)
        return float(min(max(rand.uniform(low, high), 0.0), self.max_delay))

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]]) -> "RetryPolicy":
        cfg = cfg or {}
        return cls(
            max_attempts=int(cfg.get("max_attempts", 3)),
            base_delay=float(cfg.get("base_delay", 0.5)),
            max_delay=float(cfg.get("max_delay", 30.0)),
            multiplier=float(cfg.get("multiplier", 2.0)),
            jitter=float(cfg.get("jitter", 0.25)),
            respect_retry_after=bool(cfg.get("respect_retry_after", True)),
            max_retry_after=float(cfg.get("max_retry_after", 120.0)),
        )


# --------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------

class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    def __init__(self, provider_id: str, remaining: float):
        self.provider_id = provider_id
        self.remaining = remaining
        super().__init__(
            f"circuit open for provider '{provider_id}' ({remaining:.1f}s remaining)"
        )


@dataclass
class CircuitBreaker:
    provider_id: str = ""
    failure_threshold: int = 3
    cooldown: float = 30.0
    half_open_max_calls: int = 1
    success_threshold: int = 1

    _state: BreakerState = field(default=BreakerState.CLOSED, init=False)
    _failures: int = field(default=0, init=False)
    _successes: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _clock: Callable[[], float] = field(default=time.monotonic, init=False, repr=False)

    def set_clock(self, clock: Callable[[], float]) -> None:
        """Inject a clock (tests use this instead of sleeping)."""
        self._clock = clock

    @property
    def state(self) -> BreakerState:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def _maybe_half_open(self) -> None:
        if self._state is BreakerState.OPEN and \
                (self._clock() - self._opened_at) >= self.cooldown:
            self._state = BreakerState.HALF_OPEN
            self._half_open_calls = 0
            self._successes = 0

    def allows(self) -> bool:
        with self._lock:
            self._maybe_half_open()
            if self._state is BreakerState.CLOSED:
                return True
            if self._state is BreakerState.OPEN:
                return False
            return self._half_open_calls < self.half_open_max_calls

    def remaining_cooldown(self) -> float:
        with self._lock:
            if self._state is not BreakerState.OPEN:
                return 0.0
            return max(0.0, self.cooldown - (self._clock() - self._opened_at))

    def before_call(self) -> None:
        with self._lock:
            if not self.allows():
                raise CircuitOpenError(self.provider_id, self.remaining_cooldown())
            if self._state is BreakerState.HALF_OPEN:
                self._half_open_calls += 1

    def record_success(self) -> None:
        with self._lock:
            if self._state is BreakerState.HALF_OPEN:
                self._successes += 1
                if self._successes >= self.success_threshold:
                    self._reset_locked()
            else:
                self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            if self._state is BreakerState.HALF_OPEN:
                self._trip_locked()
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._trip_locked()

    def _trip_locked(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._half_open_calls = 0
        self._successes = 0
        logger.warning("Circuit breaker OPEN for provider '%s'", self.provider_id)

    def _reset_locked(self) -> None:
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._successes = 0
        self._half_open_calls = 0

    def reset(self) -> None:
        with self._lock:
            self._reset_locked()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._maybe_half_open()
            return {
                "provider_id": self.provider_id,
                "state": self._state.value,
                "failures": self._failures,
                "cooldown_remaining": round(self.remaining_cooldown(), 2),
            }


class CircuitBreakerRegistry:
    """Per-provider circuit breakers."""

    def __init__(self, failure_threshold: int = 3, cooldown: float = 30.0,
                 half_open_max_calls: int = 1, success_threshold: int = 1) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()

    def get(self, provider_id: str) -> CircuitBreaker:
        key = str(provider_id or "unknown")
        with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = CircuitBreaker(
                    provider_id=key,
                    failure_threshold=self.failure_threshold,
                    cooldown=self.cooldown,
                    half_open_max_calls=self.half_open_max_calls,
                    success_threshold=self.success_threshold,
                )
                self._breakers[key] = breaker
            return breaker

    def allows(self, provider_id: str) -> bool:
        return self.get(provider_id).allows()

    def all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: b.snapshot() for k, b in self._breakers.items()}

    def reset_all(self) -> None:
        with self._lock:
            for b in self._breakers.values():
                b.reset()

    @classmethod
    def from_config(cls, cfg: Optional[Dict[str, Any]]) -> "CircuitBreakerRegistry":
        cfg = cfg or {}
        return cls(
            failure_threshold=int(cfg.get("failure_threshold", 3)),
            cooldown=float(cfg.get("cooldown", 30.0)),
            half_open_max_calls=int(cfg.get("half_open_max_calls", 1)),
            success_threshold=int(cfg.get("success_threshold", 1)),
        )


# --------------------------------------------------------------------------
# Unified call wrapper
# --------------------------------------------------------------------------

def _looks_like_error_string(result: Any) -> bool:
    if not isinstance(result, str):
        return False
    low = result.strip().lower()
    return low.startswith("error:") or low.startswith("error in ") or low.startswith("[provider_error]")


def call_with_reliability(
    provider_id: Any,
    func: Optional[Callable[..., T]] = None,
    *args: Any,
    policy: Optional[RetryPolicy] = None,
    retry_policy: Optional[Union[RetryPolicy, int]] = None,
    breakers: Optional[CircuitBreakerRegistry] = None,
    sleep: Callable[[float], None] = time.sleep,
    on_attempt_failure: Optional[Callable[[Classification, int], None]] = None,
    **kwargs: Any,
) -> Any:
    """Execute a callable with classification, bounded retry/backoff and, in
    the provider form, a circuit breaker.

    Two call signatures are supported:

    * Provider form (unchanged behaviour, used by ``providers.router``)::

          call_with_reliability(provider_id, provider.generate, messages=...,
                                policy=self.retry_policy, breakers=self.breakers, ...)

    * Gateway / tool form (no provider key)::

          call_with_reliability(fn, retry_policy=2)          # 2 retries
          call_with_reliability(fn, retry_policy=RetryPolicy(...))

      ``fn`` may be sync (invoked directly) or async (awaited); when unwrapped
      the returned awaitable is carried untouched.

    Raises :class:`ProviderCallError` (never containing secrets) on final
    failure, or :class:`CircuitOpenError` if the provider breaker is open.
    """
    provider_form = func is not None
    if provider_form:
        fn, p_id = func, provider_id
        rp = policy if policy is not None else retry_policy
    else:
        fn, p_id = provider_id, ""
        rp = retry_policy if retry_policy is not None else policy

    if rp is None:
        rp = RetryPolicy()
    elif isinstance(rp, int):
        # ``retry_policy=2`` means "retry up to 2 times" -> 3 attempts.
        rp = RetryPolicy(max_attempts=max(1, int(rp) + 1))

    breaker = breakers.get(p_id) if (breakers is not None and provider_form) else None
    provider_label = p_id or "gateway/tool"

    # ``inspect.iscoroutinefunction`` does not recognize an object whose
    # asynchronous behavior is implemented by ``async __call__``. Treat such
    # callable instances like async functions so retries are awaited instead
    # of leaking a coroutine object through the synchronous path.
    is_async_callable = inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(
        getattr(fn, "__call__", None)
    )
    if is_async_callable:
        async def _async_call() -> T:
            last: Optional[Classification] = None
            for attempt in range(1, max(1, rp.max_attempts) + 1):
                if breaker is not None:
                    breaker.before_call()  # raises CircuitOpenError when open
                try:
                    result = await fn(*args, **kwargs)
                    if _looks_like_error_string(result):
                        raise ProviderCallError(classify_failure(body=result), p_id)
                    if breaker is not None:
                        breaker.record_success()
                    return result
                except CircuitOpenError:
                    raise
                except asyncio.CancelledError:
                    # Cancellation is caller control flow, not a provider
                    # failure. Never convert it into a retry or ProviderCallError.
                    raise
                except ProviderCallError as exc:
                    classification = exc.classification
                except Exception as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    headers = getattr(getattr(exc, "response", None), "headers", None)
                    classification = classify_failure(exc, status_code=status, headers=headers)

                last = classification
                if breaker is not None:
                    breaker.record_failure()
                if on_attempt_failure is not None:
                    try:
                        on_attempt_failure(classification, attempt)
                    except Exception:
                        logger.debug("on_attempt_failure hook raised", exc_info=True)

                logger.warning(
                    "'%s' attempt %d/%d failed: %s (%s)",
                    provider_label, attempt, rp.max_attempts,
                    classification.failure_class.value, classification.strategy.value,
                )

                if not classification.retryable or attempt >= rp.max_attempts:
                    raise ProviderCallError(classification, p_id)

                delay = rp.compute_delay(attempt, classification.retry_after)
                if delay > 0:
                    if sleep is time.sleep:
                        await asyncio.sleep(delay)
                    else:
                        sleep(delay)

            raise ProviderCallError(last or classify_failure(body="unknown failure"), p_id)

        return _async_call()

    last = None
    for attempt in range(1, max(1, rp.max_attempts) + 1):
        if breaker is not None:
            breaker.before_call()  # raises CircuitOpenError when open
        try:
            result = fn(*args, **kwargs)
            if _looks_like_error_string(result):
                raise ProviderCallError(
                    classify_failure(body=result), p_id
                )
            if breaker is not None:
                breaker.record_success()
            return result
        except CircuitOpenError:
            raise
        except ProviderCallError as exc:
            classification = exc.classification
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            headers = getattr(getattr(exc, "response", None), "headers", None)
            classification = classify_failure(exc, status_code=status, headers=headers)

        last = classification
        if breaker is not None:
            breaker.record_failure()
        if on_attempt_failure is not None:
            try:
                on_attempt_failure(classification, attempt)
            except Exception:
                logger.debug("on_attempt_failure hook raised", exc_info=True)

        logger.warning(
            "'%s' attempt %d/%d failed: %s (%s)",
            provider_label, attempt, rp.max_attempts,
            classification.failure_class.value, classification.strategy.value,
        )

        if not classification.retryable or attempt >= rp.max_attempts:
            raise ProviderCallError(classification, p_id)

        delay = rp.compute_delay(attempt, classification.retry_after)
        if delay > 0:
            sleep(delay)

    raise ProviderCallError(last or classify_failure(body="unknown failure"), p_id)


def bounded_tool_retry(
    fn: Callable[..., T],
    *args: Any,
    retry_policy: Optional[Union[RetryPolicy, int]] = None,
    **kwargs: Any,
) -> Any:
    """Run ``fn`` with a bounded retry/backoff policy for tool and gateway work.

    ``retry_policy`` may be a :class:`RetryPolicy` or an ``int`` meaning the
    number of retries (``retries + 1`` total attempts). Async callables are
    awaited (the returned awaitable must be ``await``-ed); sync callables are
    invoked directly. Degrades to a plain single-call when ``fn`` is not
    callable.
    """
    if not callable(fn):
        return fn
    return call_with_reliability(
        fn, None, *args, retry_policy=retry_policy, **kwargs
    )
