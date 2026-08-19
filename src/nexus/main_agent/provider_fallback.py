"""Provider fallback chain — automatic failover for 24/7 autonomous operation.

When the primary provider fails (rate limit, timeout, auth error, outage),
the agent should automatically try the next provider in the chain instead
of failing the task. This is critical for 24/7 non-stop operation.

The fallback chain is configured via:
- NEXUS_PROVIDER_FALLBACK_CHAIN: comma-separated provider list (e.g. "openai,anthropic,ollama")
- NEXUS_PROVIDER_RETRY_DELAY: base delay between retries (seconds, default 2.0)
- NEXUS_PROVIDER_MAX_RETRIES: max retries per provider before trying next (default 2)
- NEXUS_PROVIDER_BACKOFF_MULTIPLIER: exponential backoff multiplier (default 2.0)

Usage:
    chain = ProviderFallbackChain()
    result = await chain.call_with_fallback(call_fn, providers=["openai", "anthropic", "ollama"])
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProviderAttempt:
    """Record of one provider attempt."""
    provider: str
    success: bool
    error: str = ""
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class ProviderFallbackChain:
    """Manages automatic provider failover for 24/7 operation.

    When a provider call fails with a retryable error (rate limit, timeout,
    auth transient), the chain automatically tries the next provider. Non-retryable
    errors (invalid key, model not found) skip to the next provider immediately.
    """

    # Errors that are retryable (worth trying the same provider again)
    RETRYABLE_ERRORS = {
        "rate_limit", "timeout", "529", "429", "503", "502",
        "connection", "overloaded", "capacity", "throttl",
        "temporary", "transient", "busy", "unavailable",
    }

    # Errors that should skip to next provider immediately (don't retry)
    SKIP_ERRORS = {
        "invalid_api_key", "authentication", "unauthorized", "401", "403",
        "model_not_found", "not_found", "does not exist",
        "invalid_request", "context_length", "max_tokens",
    }

    def __init__(self):
        self._chain = self._load_chain()
        self._retry_delay = float(os.environ.get("NEXUS_PROVIDER_RETRY_DELAY", "2.0") or 2.0)
        self._max_retries = int(os.environ.get("NEXUS_PROVIDER_MAX_RETRIES", "2") or 2)
        self._backoff_multiplier = float(os.environ.get("NEXUS_PROVIDER_BACKOFF_MULTIPLIER", "2.0") or 2.0)
        self._history: List[ProviderAttempt] = []
        self._provider_stats: Dict[str, Dict[str, Any]] = {}

    def _load_chain(self) -> List[str]:
        """Load fallback chain from environment or config."""
        raw = os.environ.get("NEXUS_PROVIDER_FALLBACK_CHAIN", "")
        if raw:
            return [p.strip().lower() for p in raw.split(",") if p.strip()]
        # Default chain: try common providers in order
        return ["openai", "anthropic", "ollama", "lmstudio"]

    def _is_retryable(self, error: str) -> bool:
        """Check if an error is retryable (worth trying same provider again)."""
        error_lower = str(error).lower()
        return any(keyword in error_lower for keyword in self.RETRYABLE_ERRORS)

    def _should_skip_provider(self, error: str) -> bool:
        """Check if we should skip to next provider immediately."""
        error_lower = str(error).lower()
        return any(keyword in error_lower for keyword in self.SKIP_ERRORS)

    def _update_stats(self, provider: str, success: bool, error: str = "") -> None:
        """Update provider statistics."""
        if provider not in self._provider_stats:
            self._provider_stats[provider] = {
                "total": 0, "success": 0, "failure": 0,
                "last_success": 0.0, "last_failure": 0.0,
                "consecutive_failures": 0,
            }
        stats = self._provider_stats[provider]
        stats["total"] += 1
        if success:
            stats["success"] += 1
            stats["last_success"] = time.time()
            stats["consecutive_failures"] = 0
        else:
            stats["failure"] += 1
            stats["last_failure"] = time.time()
            stats["consecutive_failures"] += 1

    async def call_with_fallback(
        self,
        call_fn: Callable,
        *,
        providers: Optional[List[str]] = None,
        context: str = "",
    ) -> Any:
        """Execute a call with automatic provider fallback.

        Args:
            call_fn: Async callable that takes (provider: str) -> result.
                     Should raise on failure.
            providers: List of providers to try (default: loaded chain).
            context: Description of what's being called (for logging).

        Returns:
            The result from the first successful provider.

        Raises:
            RuntimeError: When all providers in the chain have failed.
        """
        chain = providers or self._chain
        last_error = None

        for provider in chain:
            retries = 0
            while retries <= self._max_retries:
                try:
                    start = time.time()
                    result = await call_fn(provider)
                    duration = (time.time() - start) * 1000

                    self._update_stats(provider, True)
                    self._history.append(ProviderAttempt(
                        provider=provider, success=True, duration_ms=duration,
                    ))

                    if retries > 0:
                        logger.info(
                            "provider %s succeeded after %d retries (%s)",
                            provider, retries, context,
                        )
                    return result

                except Exception as exc:
                    error_str = str(exc)
                    duration = (time.time() - start) * 1000 if 'start' in dir() else 0

                    self._update_stats(provider, False, error_str)
                    self._history.append(ProviderAttempt(
                        provider=provider, success=False,
                        error=error_str[:200], duration_ms=duration,
                    ))

                    # Should we skip to next provider?
                    if self._should_skip_provider(error_str):
                        logger.warning(
                            "provider %s has non-retryable error, skipping to next: %s",
                            provider, error_str[:100],
                        )
                        last_error = exc
                        break  # Skip to next provider

                    # Is it retryable?
                    if self._is_retryable(error_str) and retries < self._max_retries:
                        delay = self._retry_delay * (self._backoff_multiplier ** retries)
                        logger.warning(
                            "provider %s retryable error (attempt %d/%d), retrying in %.1fs: %s",
                            provider, retries + 1, self._max_retries, delay, error_str[:100],
                        )
                        retries += 1
                        await asyncio.sleep(delay)
                        continue

                    # Non-retryable or max retries exceeded
                    logger.warning(
                        "provider %s failed (attempt %d/%d): %s",
                        provider, retries + 1, self._max_retries + 1, error_str[:100],
                    )
                    last_error = exc
                    break  # Try next provider

        # All providers failed
        error_msg = f"All providers in chain failed: {chain}"
        if last_error:
            error_msg += f" (last error: {str(last_error)[:200]})"
        raise RuntimeError(error_msg)

    def stats(self) -> Dict[str, Any]:
        """Return provider statistics."""
        return {
            "chain": self._chain,
            "providers": dict(self._provider_stats),
            "recent_attempts": len(self._history),
        }

    def healthy_provider(self) -> Optional[str]:
        """Return the most recently successful provider, or None."""
        best = None
        best_time = 0.0
        for provider, stats in self._provider_stats.items():
            if stats["last_success"] > best_time:
                best = provider
                best_time = stats["last_success"]
        return best
