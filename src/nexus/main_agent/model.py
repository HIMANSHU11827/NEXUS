"""V5 Model Caller - Real LLM integration for the V5 loop.

Extracted from ``core.py``. All calls go through the kernel MoE
router (``self.brain``) exactly like the unified loop, with a hard timeout,
provider-error filtering, and real-time streaming off the event loop.
"""

from __future__ import annotations

import asyncio
import os
import queue
import random
import re
import threading
from typing import Any, AsyncGenerator, Dict, List, Optional


class V5ModelCaller:
    def _effective_model_timeout(self, default: float) -> float:
        control = None
        registry = getattr(self, "_run_controls", None)
        current = str(getattr(self, "_current_turn_id", "") or "")
        if registry is not None and current:
            control = registry.get(current)
        remaining = getattr(control, "remaining", None) if control is not None else None
        if remaining is not None:
            if remaining <= 0:
                raise asyncio.TimeoutError("V5 run deadline exceeded")
            return min(float(default), remaining)
        return float(default)

    """Mixin providing synchronous, safe, and streaming model calls."""

    _STRONG_PHASES = frozenset({"plan", "verify"})
    _FAST_PHASES = frozenset({"act", "gather", "output"})
    _VALID_PHASES = _STRONG_PHASES | _FAST_PHASES
    _STRONG_MODEL_KEYS = ("model.strong", "models.strong", "model.plan", "models.plan")
    _FAST_MODEL_KEYS = ("model.fast", "models.fast")

    def _is_provider_error_text(self, value: Any) -> bool:
        """Detect provider/router failure text that must never reach the user."""
        text = str(value or "").strip()
        if not text:
            return False
        brain = self.brain
        classifier = getattr(brain, "_looks_like_provider_error", None)
        if callable(classifier):
            try:
                if classifier(text):
                    return True
            except Exception:
                pass
        head = text[:800].lower()
        patterns = (
            "error in stream:", "provider error", "provider_error", "api key is missing",
            "missing authentication", "authentication fails", "authentication error",
            "authentication required", "unauthorized", "invalid api key", "invalid key",
            "connection refused", "failed to connect to provider", "model provider unavailable",
            "all providers unavailable", "mesh_ripple", "returned status ",
            "http 4", "http 5", "status 401", "status 403", "status 404", "status 429",
            "rate limit", "rate limited", "quota exceeded", "billing",
        )
        if any(pattern in head for pattern in patterns):
            return True
        return re.search(r"\b\d{3}\b.*(?:error|failed|unauthorized|invalid)", head) is not None

    # ────────────────────────────────────────────────────────────────────
    # BOUNDED LLM RETRY (DeepSeek Harness llm-retry pattern)
    # Retryable codes: EMPTY_RESPONSE / RATE_LIMIT / SERVER / TIMEOUT /
    # TRANSPORT. Exponential backoff 500ms base, 10s cap, with jitter;
    # total attempt budget bounded by NEXUS_LLM_RETRIES (default 3).
    # ────────────────────────────────────────────────────────────────────

    def _llm_retry_budget(self) -> int:
        """Total LLM attempt budget (env NEXUS_LLM_RETRIES, default 3)."""
        try:
            return max(1, int(os.environ.get("NEXUS_LLM_RETRIES", "3")))
        except (TypeError, ValueError):
            return 3

    @staticmethod
    def _is_retryable_llm_failure(value: Any) -> bool:
        """True when a model call failure is transient and worth a retry.

        Matches rate-limit, server, timeout and transport/connectivity
        failures. Auth, billing/quota and invalid-request failures are
        permanent and never retried.
        """
        text = str(value or "").lower()
        markers = (
            "rate limit", "rate limited", "too many requests", "429",
            "500", "502", "503", "504", "bad gateway", "server error",
            "internal server", "service unavailable", "temporarily",
            "timed out", "timeout", "timedout", "connection", "connect timed",
            "network", "transport", "empty response", "no response",
            "read timed", "eof", "socket", "reset by peer",
        )
        return any(marker in text for marker in markers)

    async def _llm_retry_sleep(self, attempt: int) -> None:
        """Bounded exponential backoff (500ms base, 10s cap) with jitter."""
        delay = min(10.0, 0.5 * (2 ** max(0, attempt - 1)))
        delay = min(10.0, delay * (0.5 + random.random()))
        await asyncio.sleep(delay)

    def _llm_should_retry_empty(self) -> bool:
        """False when no provider is configured, so empty is never retried."""
        brain = getattr(self, "brain", None)
        return bool(brain is not None and hasattr(brain, "generate"))

    def _call_model(
        self,
        messages: List[Dict],
        *,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> str:
        """Synchronous model call through the kernel MoE router.

        Respects NEXUS_PROVIDER and NEXUS_MODEL env vars as fallbacks.
        Passes tool definitions when provided for native function calling.
        """
        brain = self.brain
        if not brain or not hasattr(brain, "generate"):
            self._last_model_error = "no model configured"
            return ""
        # Respect env var overrides
        provider = provider or os.environ.get("NEXUS_PROVIDER", "").strip() or None
        profile = profile or getattr(self, "profile_override", "") or None
        model = model or os.environ.get("NEXUS_MODEL", "").strip() or None
        kwargs: Dict[str, Any] = {"messages": messages}
        if provider:
            kwargs["provider"] = provider
        if profile:
            kwargs["profile"] = profile
        if model:
            kwargs["model"] = model
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            kwargs["timeout"] = max(0.001, float(timeout))
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        try:
            result = str(brain.generate(**kwargs) or "")
            if self._is_provider_error_text(result):
                self._last_model_error = str(result)[:1000]
                self.logger.warning("_call_model: provider error text returned")
                return ""
            self._last_model_error = ""
            return result
        except Exception as e:
            self._last_model_error = str(e)[:1000]
            self.logger.warning(f"_call_model error: {e}")
            return ""

    async def _safe_model_call(
        self,
        messages: List[Dict],
        *,
        timeout: float = 180.0,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> str:
        """Call the model off the event loop with a hard timeout so a slow or
        hanging provider can never freeze the turn indefinitely.

        Transient failures (timeouts, rate limits, server/transport errors
        and empty responses) are retried with bounded exponential backoff
        (500ms base, 10s cap, jitter, ``NEXUS_LLM_RETRIES`` attempts); a
        persistent failure returns "" exactly like before, but records the
        reason on ``self._last_model_error`` so the loop surfaces a truthful
        message instead of a silently empty turn."""
        check_deadline = getattr(self, "_check_deadline", None)
        if callable(check_deadline):
            check_deadline()
        effective_timeout = self._effective_model_timeout(timeout)
        max_attempts = self._llm_retry_budget()
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._call_model,
                        messages,
                        provider=provider,
                        profile=profile,
                        model=model,
                        max_tokens=max_tokens,
                        timeout=effective_timeout,
                        tools=tools,
                        tool_choice=tool_choice,
                    ),
                    timeout=effective_timeout,
                )
                if str(result or "").strip():
                    return result
                # EMPTY_RESPONSE is retryable (unless no provider is
                # configured at all).  Keep the last known error text so the
                # exhausted path can report the real cause; permanent
                # failures (auth/billing) are never retried.
                last_error = str(getattr(self, "_last_model_error", "") or "")
                should_retry = (
                    self._llm_should_retry_empty()
                    and attempt < max_attempts
                    and (not last_error or self._is_retryable_llm_failure(last_error))
                )
                if should_retry:
                    await self._llm_retry_sleep(attempt)
                    continue
                self.logger.error(
                    "Model call returned no usable response after %d attempt(s): %s",
                    attempt, last_error or "empty response",
                )
                self._last_model_error = last_error or "empty model response"
                return ""
            except asyncio.TimeoutError:
                last_error = f"model call timed out after {timeout:.0f}s"
                if attempt < max_attempts:
                    check_deadline = getattr(self, "_check_deadline", None)
                    if callable(check_deadline):
                        check_deadline()
                    await self._llm_retry_sleep(attempt)
                    continue
                check_deadline = getattr(self, "_check_deadline", None)
                if callable(check_deadline):
                    check_deadline()
                self._last_model_error = last_error
                self.logger.error(
                    "Model call timed out after %.0fs (%d attempts)", timeout, attempt
                )
                return ""
            except Exception as e:
                if attempt < max_attempts and self._is_retryable_llm_failure(str(e)):
                    last_error = str(e)[:1000]
                    await self._llm_retry_sleep(attempt)
                    continue
                self._last_model_error = str(e)[:1000]
                self.logger.error(f"Model call failed: {e}")
                return ""
        self._last_model_error = last_error or "empty model response"
        return ""

    def _call_model_raw(self, messages: List[Dict], **kwargs: Any) -> Any:
        """Return a structured provider response without losing tool calls."""
        self._last_model_error = ""
        brain = self.brain
        if not brain or not hasattr(brain, "generate"):
            self._last_model_error = "no model configured"
            return ""
        provider = kwargs.pop("provider", None) or os.environ.get("NEXUS_PROVIDER", "").strip() or None
        profile = kwargs.pop("profile", None) or getattr(self, "profile_override", "") or None
        model = kwargs.pop("model", None) or os.environ.get("NEXUS_MODEL", "").strip() or None
        # Keep optional fields absent when they were not configured. Local
        # OpenAI-compatible servers may reject explicit JSON null values.
        request: Dict[str, Any] = {
            "messages": messages,
            **{key: value for key, value in kwargs.items() if value is not None},
        }
        if provider:
            request["provider"] = provider
        if profile:
            request["profile"] = profile
        if model:
            request["model"] = model
        try:
            result = brain.generate(**request)
            # Provider adapters retain their real API usage on the router
            # side-channel because the public generate() contract remains a
            # text result. Preserve that telemetry alongside the text so the
            # direct loop can forward it to the UI.
            usage = getattr(brain, "_last_usage", None)
            if isinstance(usage, dict) and usage:
                return {"message": {"content": str(result or "")}, "usage": dict(usage)}
            return result
        except Exception as exc:
            self._last_model_error = str(exc)[:1000]
            self.logger.warning("_call_model_raw error: %s", exc)
            return ""

    async def _safe_model_call_raw(self, messages: List[Dict], *, timeout: float = 180.0, **kwargs: Any) -> Any:
        """Async bounded wrapper for the structured model response.

        Retries transient failures (timeouts, rate limits, server/transport
        errors and empty responses) with the same bounded backoff as
        ``_safe_model_call``; on persistent failure returns "" and records
        the reason on ``self._last_model_error`` so the direct loop can
        surface a truthful provider-failure response instead of an empty
        turn."""
        check_deadline = getattr(self, "_check_deadline", None)
        if callable(check_deadline):
            check_deadline()
        hooks = getattr(getattr(self, "runtime", None), "hooks", None)
        trigger = getattr(hooks, "trigger", None)
        if callable(trigger):
            await trigger("pre_llm_call", messages, dict(kwargs))
        effective_timeout = self._effective_model_timeout(timeout)
        kwargs.setdefault("timeout", max(0.001, float(effective_timeout)))
        max_attempts = self._llm_retry_budget()
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._call_model_raw, messages, **kwargs), timeout=effective_timeout
                )
                if result not in ("", None):
                    if callable(trigger):
                        await trigger("post_llm_call", messages, result)
                    return result
                # EMPTY_RESPONSE retry (unless no provider is configured);
                # permanent failures (auth/billing) are never retried.
                last_error = str(getattr(self, "_last_model_error", "") or "")
                should_retry = (
                    self._llm_should_retry_empty()
                    and attempt < max_attempts
                    and (not last_error or self._is_retryable_llm_failure(last_error))
                )
                if should_retry:
                    await self._llm_retry_sleep(attempt)
                    continue
                self._last_model_error = last_error or "empty model response"
                self.logger.error(
                    "Raw model call returned no usable response after %d attempt(s): %s",
                    attempt, last_error or "empty response",
                )
                if callable(trigger):
                    await trigger("post_llm_call", messages, {"error": self._last_model_error})
                return ""
            except asyncio.TimeoutError:
                last_error = f"model call timed out after {timeout:.0f}s"
                if attempt < max_attempts:
                    check_deadline = getattr(self, "_check_deadline", None)
                    if callable(check_deadline):
                        check_deadline()
                    await self._llm_retry_sleep(attempt)
                    continue
                check_deadline = getattr(self, "_check_deadline", None)
                if callable(check_deadline):
                    check_deadline()
                self._last_model_error = last_error
                self.logger.error("Raw model call timed out after %.0fs", timeout)
                if callable(trigger):
                    await trigger("post_llm_call", messages, {"error": "model timeout"})
                return ""
            except Exception as exc:
                if attempt < max_attempts and self._is_retryable_llm_failure(str(exc)):
                    last_error = str(exc)[:1000]
                    await self._llm_retry_sleep(attempt)
                    continue
                self._last_model_error = str(exc)[:1000]
                self.logger.error("Raw model call failed: %s", exc)
                if callable(trigger):
                    await trigger("post_llm_call", messages, {"error": str(exc)[:1000]})
                return ""
        return ""

    def _select_model_for_phase(self, phase: str) -> str:
        """Return the configured model for a turn phase, or "" for default.

        Phases ``plan``/``verify`` route to the strong model, phases ``act``/
        ``gather``/``output`` to the fast model. Resolution order: explicit
        config keys (``model.strong``, ``models.strong``, ``model.plan``,
        ``models.plan`` for strong; ``model.fast``/``models.fast`` for fast,
        plus per-phase keys like ``model.act``), then env vars
        ``NEXUS_MODEL_PLAN``/``NEXUS_MODEL_FAST``. Returns "" (default model)
        when no routing is configured. Never raises.
        """
        phase = str(phase or "").strip().lower()
        if phase not in self._VALID_PHASES:
            self.logger.debug("_select_model_for_phase: unknown phase %r; default model", phase)
            return ""
        try:
            if phase in self._STRONG_PHASES:
                for key in self._STRONG_MODEL_KEYS:
                    value = self._config(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                value = os.environ.get("NEXUS_MODEL_PLAN", "")
                if isinstance(value, str) and value.strip():
                    return value.strip()
                return ""
            keys = self._FAST_MODEL_KEYS + (f"model.{phase}", f"models.{phase}")
            for key in keys:
                value = self._config(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            value = os.environ.get("NEXUS_MODEL_FAST", "")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return ""
        except Exception as e:
            self.logger.debug(f"_select_model_for_phase error: {e}")
            return ""

    async def _safe_model_call_phase(
        self,
        messages: List[Dict],
        phase: str,
        timeout: float = 90.0,
    ) -> str:
        """Model call routed by turn phase (plan/verify strong, act/gather/output fast).

        Delegates to ``_safe_model_call`` passing the routed model as an
        override; when no routing is configured this is behaviorally identical
        to a plain ``_safe_model_call(messages, timeout=timeout)``. Never raises.
        """
        try:
            model = self._select_model_for_phase(phase)
            if not model:
                return await self._safe_model_call(messages, timeout=timeout)
            return await self._safe_model_call(messages, timeout=timeout, model=model)
        except Exception as e:
            self.logger.error(f"Phase model call failed: {e}")
            return ""

    async def _stream_model(
        self,
        messages: List[Dict],
        *,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 90.0,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Yield model chunks in real time off the event loop.

        Respects NEXUS_PROVIDER and NEXUS_MODEL env vars as fallbacks.
        Passes tool definitions when provided for native function calling.
        """
        brain = self.brain
        if not brain or not hasattr(brain, "stream_generate"):
            return
        provider = provider or os.environ.get("NEXUS_PROVIDER", "").strip() or None
        profile = profile or getattr(self, "profile_override", "") or None
        model = model or os.environ.get("NEXUS_MODEL", "").strip() or None

        chunk_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        stop_event = threading.Event()
        self._last_model_error = ""

        def _run_stream() -> None:
            stream = None
            try:
                kwargs: Dict[str, Any] = {"messages": messages}
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                if provider:
                    kwargs["provider"] = provider
                if profile:
                    kwargs["profile"] = profile
                if model:
                    kwargs["model"] = model
                kwargs["timeout"] = max(0.001, self._effective_model_timeout(timeout))
                if tools is not None:
                    kwargs["tools"] = tools
                if tool_choice is not None:
                    kwargs["tool_choice"] = tool_choice
                stream = brain.stream_generate(**kwargs)
                for chunk in stream:
                    if stop_event.is_set():
                        return
                    if self._is_provider_error_text(chunk):
                        chunk_queue.put(("error", str(chunk)))
                        return
                    text = str(chunk or "")
                    if text:
                        chunk_queue.put(("chunk", text))
                chunk_queue.put(("done", ""))
            except Exception as e:
                chunk_queue.put(("error", str(e)))
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        self.logger.debug("Provider stream close failed", exc_info=True)

        threading.Thread(target=_run_stream, daemon=True).start()

        try:
            while True:
                # Model streams can remain inside this loop for the entire
                # turn. Use the canonical abort check here so durable
                # cross-process cancellations are refreshed, not only checked
                # at the surrounding phase boundaries.
                registry = getattr(self, "_run_controls", None)
                current = str(getattr(self, "_current_turn_id", "") or "")
                check_abort = getattr(self, "_check_abort", None)
                if callable(check_abort):
                    check_abort()
                elif registry is not None and current:
                    refresh = getattr(registry, "refresh_cancel", None)
                    if callable(refresh):
                        refresh(current)
                control = None
                if registry is not None and current:
                    control = registry.get(current)
                if control is not None:
                    if control.cancelled:
                        raise asyncio.CancelledError(control.reason or "V5 run cancelled")
                    remaining = control.remaining
                    if remaining is not None and remaining <= 0:
                        check_deadline = getattr(self, "_check_deadline", None)
                        if callable(check_deadline):
                            check_deadline()
                        raise asyncio.TimeoutError("V5 run deadline exceeded")
                    wait_timeout = min(0.2, max(0.01, remaining)) if remaining is not None else 0.2
                else:
                    wait_timeout = 0.2
                try:
                    kind, payload = await asyncio.to_thread(chunk_queue.get, True, wait_timeout)
                except queue.Empty:
                    continue
                if kind == "chunk":
                    yield payload
                    continue
                if kind == "done":
                    break
                if kind == "error":
                    self._last_model_error = str(payload or "")
                    self.logger.error("Model stream failed: %s", payload)
                    raise RuntimeError("Provider stream failed")
        finally:
            stop_event.set()
