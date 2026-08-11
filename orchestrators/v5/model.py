"""V5 Model Caller - Real LLM integration for the V5 loop.

Extracted from ``core.py``. All calls go through the kernel MoE
router (``self.brain``) exactly like the unified loop, with a hard timeout,
provider-error filtering, and real-time streaming off the event loop.
"""

from __future__ import annotations

import asyncio
import os
import queue
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
                self.logger.warning("_call_model: provider error text returned")
                return ""
            return result
        except Exception as e:
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
        hanging provider can never freeze the turn indefinitely."""
        check_deadline = getattr(self, "_check_deadline", None)
        if callable(check_deadline):
            check_deadline()
        effective_timeout = self._effective_model_timeout(timeout)
        try:
            return await asyncio.wait_for(
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
        except asyncio.TimeoutError:
            check_deadline = getattr(self, "_check_deadline", None)
            if callable(check_deadline):
                check_deadline()
            self.logger.error("Model call timed out after %.0fs", timeout)
            return ""
        except Exception as e:
            self.logger.error(f"Model call failed: {e}")
            return ""

    def _call_model_raw(self, messages: List[Dict], **kwargs: Any) -> Any:
        """Return a structured provider response without losing tool calls."""
        self._last_model_error = ""
        brain = self.brain
        if not brain or not hasattr(brain, "generate"):
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
            return brain.generate(**request)
        except Exception as exc:
            self._last_model_error = str(exc)[:1000]
            self.logger.warning("_call_model_raw error: %s", exc)
            return ""

    async def _safe_model_call_raw(self, messages: List[Dict], *, timeout: float = 180.0, **kwargs: Any) -> Any:
        """Async bounded wrapper for the structured model response."""
        check_deadline = getattr(self, "_check_deadline", None)
        if callable(check_deadline):
            check_deadline()
        hooks = getattr(getattr(self, "runtime", None), "hooks", None)
        trigger = getattr(hooks, "trigger", None)
        if callable(trigger):
            await trigger("pre_llm_call", messages, dict(kwargs))
        effective_timeout = self._effective_model_timeout(timeout)
        kwargs.setdefault("timeout", max(0.001, float(effective_timeout)))
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._call_model_raw, messages, **kwargs), timeout=effective_timeout
            )
            if callable(trigger):
                await trigger("post_llm_call", messages, result)
            return result
        except asyncio.TimeoutError:
            check_deadline = getattr(self, "_check_deadline", None)
            if callable(check_deadline):
                check_deadline()
            self._last_model_error = f"model call timed out after {timeout:.0f}s"
            self.logger.error("Raw model call timed out after %.0fs", timeout)
            if callable(trigger):
                await trigger("post_llm_call", messages, {"error": "model timeout"})
        except Exception as exc:
            self._last_model_error = str(exc)[:1000]
            self.logger.error("Raw model call failed: %s", exc)
            if callable(trigger):
                await trigger("post_llm_call", messages, {"error": str(exc)[:1000]})
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
