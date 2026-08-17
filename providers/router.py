import logging
import os
import inspect
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from providers.reliability import (
    CircuitBreakerRegistry,
    CircuitOpenError,
    Classification,
    FailureClass,
    ProviderCallError,
    RetryPolicy,
    Strategy,
    call_with_reliability,
    classify_failure,
    redact_secrets,
)
from providers.model_capabilities import ModelCapabilityRegistry
from providers.attempts import ProviderAttemptRecorder

logger = logging.getLogger("NEXUS_ROUTER")

class ModelRouter:
    """
    NEXUS BRAIN ROUTER 3.0
    Supports LOCAL, CLOUD, HYBRID, and AUTO intelligence modes.
    """
    def __init__(self, kernel=None):
        if kernel:
            self.kernel = kernel
        else:
            from kernel import get_nexus_kernel
            self.kernel = get_nexus_kernel()
            
        self.total_local_calls = 0
        self.total_cloud_calls = 0
        self.mode = os.environ.get("NEXUS_BRAIN_MODE", "AUTO").upper() # LOCAL, CLOUD, HYBRID, AUTO
        
        from providers.factory import NexusProviderFactory
        self.factory = NexusProviderFactory()
        self.provider = self.factory.get_provider()
        from providers.health import ProviderHealthRegistry
        health_root = getattr(self.kernel, "root", None) or getattr(self.kernel, "root_dir", None)
        health_path = os.path.join(str(health_root), ".nexus", "provider_health.sqlite3") if health_root else None
        self.health = ProviderHealthRegistry(store_path=health_path)
        from providers.health import ProviderCapabilityRegistry
        self.capabilities = ProviderCapabilityRegistry()

        # Reliability layer: retry policy + per-provider circuit breakers.
        reliability_cfg = {}
        try:
            provider_cfg = self.factory.loader.get("provider", {}) or {}
            if isinstance(provider_cfg, dict):
                reliability_cfg = provider_cfg.get("reliability", {}) or {}
        except Exception:
            logger.debug("router: reliability config unavailable, using defaults", exc_info=True)
        self.retry_policy = RetryPolicy.from_config(reliability_cfg.get("retry"))
        self._breakers = CircuitBreakerRegistry.from_config(reliability_cfg.get("circuit_breaker"))
        self._model_capabilities = ModelCapabilityRegistry.from_loader(getattr(self.factory, "loader", None))
        self.last_failure: Optional[Classification] = None
        self.attempts = ProviderAttemptRecorder()

        from cognition.intent_engine import IntentEngine
        self.intent_engine = IntentEngine(self)

    @property
    def breakers(self) -> "CircuitBreakerRegistry":
        """Per-provider circuit breakers, created on demand.

        Lazy so that a ModelRouter built without ``__init__`` (tests, partial
        restores, deserialized instances) still has a working reliability layer
        instead of raising AttributeError mid-stream.
        """
        registry = getattr(self, "_breakers", None)
        if registry is None:
            registry = CircuitBreakerRegistry.from_config(None)
            self._breakers = registry
        return registry

    @breakers.setter
    def breakers(self, value: "CircuitBreakerRegistry") -> None:
        self._breakers = value

    @property
    def model_capabilities(self) -> "ModelCapabilityRegistry":
        registry = getattr(self, "_model_capabilities", None)
        if registry is None:
            registry = ModelCapabilityRegistry.from_loader(getattr(getattr(self, "factory", None), "loader", None))
            self._model_capabilities = registry
        return registry

    @model_capabilities.setter
    def model_capabilities(self, value: "ModelCapabilityRegistry") -> None:
        self._model_capabilities = value

    def set_mode(self, mode: str):
        """Sets the intelligence mode: LOCAL (Trainable), CLOUD (Fixed), HYBRID, AUTO."""
        self.mode = mode.upper()
        logger.info(f"🧠 [BRAIN_MODE]: Intelligence shifted to {self.mode}")
        if self.mode == "LOCAL":
            logger.info("📡 [SOVEREIGN_STATUS]: Neural training path active. Interaction data being collected.")
        else:
            logger.info("🌐 [GLOBAL_STATUS]: High-fidelity cloud mesh active. No training required.")

    def set_override(self, provider_id: str, profile: Optional[str] = None):
        """Forces the router to use a specific provider."""
        new_provider = self.factory.get_provider_by_name(
            "cloud", provider_id, profile=profile or None
        )
        if new_provider:
            self.provider = new_provider
            logger.info("🧠 [ROUTER_OVERRIDE]: Brain switched to %s", provider_id)

    def _request_provider(self, provider_id: Optional[str], profile: Optional[str] = None):
        """Resolve a request-local provider without mutating shared router state."""
        requested = str(provider_id or "").strip()
        if not requested:
            return self.provider
        try:
            return self.factory.get_provider_by_name(
                "cloud", requested, profile=str(profile or "").strip() or None
            ) or self.provider
        except Exception:
            logger.warning("Request provider resolution failed for %s", requested, exc_info=True)
            return self.provider

    def _get_required_tier(self, messages: List[Dict[str, str]]) -> str:
        """Classifies the task into an intelligence tier (1M to 1T+)."""
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        if not user_msgs: return "NANO"
        
        last_input = user_msgs[-1].lower()
        
        # Use the IntentEngine for high-fidelity classification
        from cognition.intent_engine import NexusIntent
        classified = self.intent_engine.classify(last_input)
        # IntentEngine historically returned a mapping; accept enum/string
        # values too so partial restores and custom engines remain compatible.
        if isinstance(classified, dict):
            intent = classified.get("intent", NexusIntent.CHAT.value)
        else:
            intent = classified
        if isinstance(intent, str):
            try:
                intent = NexusIntent(intent.lower())
            except ValueError:
                intent = NexusIntent.CHAT

        if intent in [NexusIntent.MISSION, NexusIntent.VISION]:
            return "EXTREME"
        if intent in [NexusIntent.DIAGNOSTIC, NexusIntent.COGNITION]:
            return "MEDIUM"
        return "NANO"


    def _should_use_heavy_brain(self, messages: List[Dict[str, str]]) -> bool:
        if self.mode == "CLOUD": return True
        if self.mode == "LOCAL": return False
        
        # Optional heavy-mode override.
        if os.environ.get("NEXUS_HEAVY_MODE") == "false":
            return False
            
        force_heavy = os.environ.get("NEXUS_FORCE_HEAVY", "false").lower() in ("true", "1")
        if force_heavy:
            tier = self._get_required_tier(messages)
            if tier in ["EXTREME", "MEDIUM"]:
                return True
            return False

        # ⚡ [SCALE_ELASTIC_ROUTING]
        tier = self._get_required_tier(messages)
        if tier in ["EXTREME", "MEDIUM"]:
            return True
            
        return False

    def _local_brain_enabled(self) -> bool:
        """Return whether the expensive lazy local-brain runtime may be loaded."""
        return self.mode == "LOCAL" or os.environ.get("NEXUS_ENABLE_LOCAL_BRAIN", "false").lower() in ("true", "1", "yes")

    def generate(self, messages: Optional[List[Dict[str, str]]] = None, prompt: str = "", system_prompt: str = "", **kwargs) -> str:
        if messages is None:
            messages = []
            if system_prompt: messages.append({"role": "system", "content": system_prompt})
            if prompt: messages.append({"role": "user", "content": prompt})

        requested_provider = kwargs.pop("provider", None)
        requested_profile = kwargs.pop("profile", None)
        routing_prefs = self._pop_routing_prefs(kwargs)
        request_provider = self._request_provider(requested_provider, requested_profile)

        # 🏎️ [HYBRID_MODE]: Use MOA for maximum reasoning
        if self.mode == "HYBRID":
            logger.info("⚡ [HYBRID]: Activating MOA Intelligence Mesh...")
            return self.kernel.moa.aggregate(messages=messages, **kwargs)

        use_heavy = self._should_use_heavy_brain(messages)
        
        # An explicit provider/model selection is authoritative. The local
        # brain is an automatic optimization only; allowing it to run first
        # silently reroutes cloud requests (for example DeepSeek) to LM Studio
        # and makes the selected provider appear unavailable.
        if not requested_provider and not use_heavy and self._local_brain_enabled():
            try:
                self.total_local_calls += 1
                # [SOVEREIGN_FIX]: Preserve system context for local brain
                system_content = next((m["content"] for m in messages if m["role"] == "system"), "")
                master_prompt = (
                    "### System: You are NEXUS, a local-first autonomous engineering agent. "
                    "Be concise, helpful, and technically honest. "
                    f"Context: {system_content[:500]}\n"
                    "For actions, use ONLY this JSON format: ```json\n{\"action\": \"...\", \"params\": {...}}\n```. "
                    "When finished, say 'TASK_COMPLETE'.\n"
                )
                repair_messages = [{"role": "system", "content": master_prompt}] + [m for m in messages if m["role"] != "system"][-8:]
                return self.kernel.local_brain.generate(messages=repair_messages)
            except Exception as e:
                logger.warning(f"Local fail: {e}")

        # Cloud/local mesh with capability-aware fallback.
        fallback_mesh = self._fallback_mesh(messages=messages, active_provider=request_provider, prefs=routing_prefs)

        if request_provider:
            provider_id = self._provider_id(request_provider)
            try:
                self.total_cloud_calls += 1
                return self._invoke(request_provider, provider_id, messages, **kwargs)
            except Exception as primary_error:
                error = primary_error
                classification = (
                    primary_error.classification
                    if isinstance(primary_error, ProviderCallError)
                    else classify_failure(primary_error)
                )
                # A pre-request context failure is safe to retry once with a
                # call/result-safe compacted transcript. This prevents the
                # fallback mesh from repeating the same oversized request.
                if classification.failure_class is FailureClass.CONTEXT_OVERFLOW:
                    compacted = self._compact_after_context_overflow(
                        messages, request_provider, kwargs
                    )
                    if compacted != messages:
                        try:
                            return self._invoke(request_provider, provider_id, compacted, **kwargs)
                        except Exception as compact_error:
                            error = compact_error
                logger.warning(
                    "Primary brain (%s) failed: %s",
                    type(self.provider).__name__, redact_secrets(error),
                )
                # An explicit provider selection is authoritative. Falling
                # through to an unrelated local provider hides the real
                # credential/configuration problem from the user.
                if requested_provider:
                    raise error
                return self._generate_with_fallbacks(messages, fallback_mesh, **kwargs)

        return self._generate_with_fallbacks(messages, fallback_mesh, **kwargs)

    # ------------------------------------------------------------------
    # Reliability-aware invocation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _provider_id(provider: Any) -> str:
        return str(
            getattr(provider, "_provider_id", "")
            or getattr(provider, "provider_name", "")
            or type(provider).__name__
        )

    @staticmethod
    def _provider_credentials_usable(provider: Any, provider_id: str = "") -> bool:
        """Allow keyless loopback providers while keeping remote auth fail-closed."""
        endpoint = str(getattr(provider, "endpoint", "") or "")
        try:
            hostname = urlparse(endpoint).hostname
        except ValueError:
            hostname = None
        local = hostname in {"localhost", "127.0.0.1", "::1"} or str(provider_id).lower() in {"ollama", "lm_studio", "lm-studio"}
        if local:
            return True
        validator = getattr(provider, "validate_api_key", None)
        if not callable(validator):
            return True
        try:
            return bool(validator())
        except Exception:
            return False

    @staticmethod
    def _pop_routing_prefs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Extract optional latency/cost preference kwargs for task-aware
        routing. Cleanly removed so providers never receive routing hints."""
        prefs: Dict[str, Any] = {}
        for _key in ("preferred", "latency_tier", "cost_tier"):
            value = kwargs.pop(_key, None)
            if value:
                prefs[_key] = value
        return prefs

    @staticmethod
    def _preference_tier(prefs: Optional[Dict[str, Any]] = None) -> str:
        """Map routing-preference kwargs (+ env policy) to a tier name."""
        from providers import model_bench
        return model_bench.resolve_tier(
            preferred=(prefs or {}).get("preferred"),
            latency_tier=(prefs or {}).get("latency_tier"),
            cost_tier=(prefs or {}).get("cost_tier"),
        )

    def _apply_model_limits(self, provider: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Clamp caller kwargs to the *specific model's* documented limits."""
        provider_id = self._provider_id(provider)
        model = str(kwargs.get("model") or getattr(provider, "model", "") or "")
        capability = self.model_capabilities.get(provider_id, model)
        adjusted = dict(kwargs)
        adjusted["max_tokens"] = capability.clamp_max_tokens(kwargs.get("max_tokens"))
        if kwargs.get("tools") and not capability.tools:
            adjusted.pop("tools", None)
            adjusted.pop("tool_choice", None)
            logger.info("model '%s' has no tool support; tools stripped from request", model)
        return adjusted

    @staticmethod
    def _supported_provider_kwargs(provider: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Filter kwargs before reliability wraps Python argument errors.

        ``call_with_reliability`` converts adapter exceptions into
        ``ProviderCallError``, so an outer ``except TypeError`` cannot recover
        from an unsupported keyword. Adapters declaring ``**kwargs`` are left
        untouched; uninspectable third-party callables use the normal failure
        path.
        """
        try:
            signature = inspect.signature(provider.generate)
        except (TypeError, ValueError):
            return dict(kwargs)
        parameters = signature.parameters.values()
        if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
            return dict(kwargs)
        accepted = {
            parameter.name
            for parameter in parameters
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        return {key: value for key, value in kwargs.items() if key in accepted}

    @staticmethod
    def _release_profile_lease(provider: Any) -> None:
        """Release a factory-acquired profile lease after a request attempt.

        Providers are often cached by the factory/router, so relying on object
        destruction would retain an exclusive profile claim long after the
        request finished.  Clear the attached token even when release itself
        fails, allowing the next request to resolve a fresh lease safely.
        """
        lease = getattr(provider, "_profile_lease", None)
        store = getattr(provider, "_profile_store", None)
        if lease is None or store is None:
            return
        try:
            store.release_lease(lease)
        except Exception:
            logger.debug("provider profile lease release failed", exc_info=True)
        finally:
            try:
                delattr(provider, "_profile_lease")
            except AttributeError:
                pass
            try:
                delattr(provider, "_profile_store")
            except AttributeError:
                pass

    @staticmethod
    def _renew_profile_lease(provider: Any, *, renew_before_seconds: float = 30.0) -> bool:
        """Keep an attached profile lease alive while a stream is producing.

        Profile leases are intentionally expiring for crash recovery.  A long
        response must nevertheless renew its ownership before expiry, or a
        second worker can claim the same credential while the first request is
        still using it.  Providers without a real lease (including test/local
        adapters) remain unaffected.
        """
        lease = getattr(provider, "_profile_lease", None)
        store = getattr(provider, "_profile_store", None)
        renew = getattr(store, "renew_lease", None)
        if lease is None or store is None or not callable(renew):
            return True
        try:
            expires_at = float(getattr(lease, "expires_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            expires_at = 0.0
        if expires_at and expires_at - time.time() > float(renew_before_seconds):
            return True
        try:
            renewed = renew(lease, ttl_seconds=60.0)
        except Exception:
            logger.warning("provider profile lease renewal failed", exc_info=True)
            return False
        if renewed is None:
            logger.warning("provider profile lease was lost during streaming")
            return False
        try:
            provider._profile_lease = renewed
        except Exception:
            logger.debug("provider profile lease token could not be updated", exc_info=True)
            return False
        return True

    def _leased_stream(self, provider: Any, iterator: Any):
        """Forward a provider iterator while releasing its lease on close.

        ``stream_generate`` is a generator API, so callers may stop after a
        partial response and close it without reaching the router's normal
        terminal branch.  The ``finally`` here covers completion, provider
        exceptions, and explicit generator finalization.
        """
        try:
            for chunk in iterator:
                if not self._renew_profile_lease(provider):
                    raise RuntimeError("provider profile lease lost during streaming")
                yield chunk
        finally:
            self._release_profile_lease(provider)

    def _invoke(self, provider: Any, provider_id: str, messages: List[Dict[str, str]],
                streaming: bool = False, **kwargs) -> str:
        """Single provider call guarded by retry/backoff + circuit breaker."""
        self._last_usage = None
        attempt_started = time.time()
        self.attempts.record(
            provider_id,
            credential_id=getattr(provider, "_credential_id", ""),
            profile=kwargs.get("profile", ""),
            model=kwargs.get("model") or getattr(provider, "model", ""),
            status="started",
        )
        if not self._provider_credentials_usable(provider, provider_id):
            classification = classify_failure(body="missing or invalid api key")
            self.last_failure = classification
            self.health.mark_failure(provider_id, classification.failure_class.value)
            self.attempts.record(provider_id, credential_id=getattr(provider, "_credential_id", ""), status="failed", classification=classification,
                                 reason=classification.message,
                                 duration_ms=(time.time() - attempt_started) * 1000)
            # Credential validation happens before the retry wrapper, so this
            # early terminal path must release a factory-acquired profile lease
            # explicitly rather than waiting for its TTL to expire.
            self._release_profile_lease(provider)
            raise ProviderCallError(classification, provider_id)

        call_kwargs = self._supported_provider_kwargs(
            provider, self._apply_model_limits(provider, kwargs)
        )
        start = time.time()

        def _on_failure(classification: Classification, attempt: int) -> None:
            self.last_failure = classification
            self.health.mark_failure(provider_id, classification.failure_class.value)
            self.attempts.record(
                provider_id,
                credential_id=getattr(provider, "_credential_id", ""),
                profile=kwargs.get("profile", ""),
                model=kwargs.get("model") or getattr(provider, "model", ""),
                attempt=attempt,
                status="failed",
                classification=classification,
                reason=classification.message,
            )

        try:
            result = call_with_reliability(
                provider_id,
                provider.generate,
                messages=messages,
                policy=self.retry_policy,
                breakers=self.breakers,
                on_attempt_failure=_on_failure,
                **call_kwargs,
            )
        finally:
            self._release_profile_lease(provider)
        self.health.mark_success(provider_id, (time.time() - start) * 1000)
        provider_usage = getattr(provider, "_last_usage", None)
        self._last_usage = dict(provider_usage) if isinstance(provider_usage, dict) else None
        self.attempts.record(
            provider_id,
            credential_id=getattr(provider, "_credential_id", ""),
            profile=kwargs.get("profile", ""),
            model=kwargs.get("model") or getattr(provider, "model", ""),
            status="success",
            duration_ms=(time.time() - attempt_started) * 1000,
        )
        return result

    def _fallback_mesh(self, messages: Optional[List[Dict[str, str]]] = None, *, streaming: bool = False, active_provider: Any = None, prefs: Optional[Dict[str, Any]] = None) -> List[str]:
        """Return provider IDs ordered by task quality, capability and health.

        When the prompt classifies into a known task, the viable providers are
        ranked by per-task benchmark score with latency/cost hard filters
        (providers/model_bench.py). Any failure in that path keeps the legacy
        capability + recent-health ordering exactly as before.
        """
        try:
            cfg = self.kernel.config.get("task_routing_auto", {})
            candidates = list(cfg.keys()) if isinstance(cfg, dict) else []
        except Exception:
            candidates = []
        if not candidates:
            candidates = ["openrouter", "gemini", "groq", "openai", "ollama", "lm_studio"]
        active = getattr(active_provider or self.provider, "provider_name", "")
        ordered = [c for c in candidates if c != active]
        text = "\n".join(m.get("content", "") for m in messages or [])
        needs_vision = any(k in text.lower() for k in ["image", "screenshot", "vision", "multimodal", "os_", "ui_automation", "browser", "desktop"])
        prefer_local = self.mode == "LOCAL"

        # Task-aware quality ordering with latency/cost hard filters; skipped in
        # LOCAL mode where the local-first policy must win.
        ranked: List[str] = []
        try:
            from providers import model_bench
            task = model_bench.classify_task(text)
            if task and not prefer_local:
                viable = [
                    c for c in ordered
                    if self.capabilities.supports(c, streaming=streaming, vision=needs_vision)
                    and not self.health.is_degraded(c)
                ]
                if viable:
                    ranked = model_bench.rank_models(
                        task,
                        viable,
                        caps=self.model_capabilities,
                        health=self.health,
                        tier=self._preference_tier(prefs),
                    )
        except Exception:
            logger.debug("ROUTER: task-aware mesh ranking skipped; using legacy ordering", exc_info=True)

        if ranked:
            mesh = ranked
        else:
            selected = self.capabilities.choose(
                ordered,
                self.health,
                streaming=streaming,
                vision=needs_vision,
                prefer_local=prefer_local,
            )
            mesh = selected or ordered
        # Never dispatch to a provider whose breaker is open.
        allowed = [c for c in mesh if self.breakers.allows(c)]
        return allowed or [c for c in ordered if self.breakers.allows(c)]

    @staticmethod
    def _looks_like_provider_error(result: Any) -> bool:
        if not isinstance(result, str):
            return False
        lowered = result.strip().lower()
        return lowered.startswith("error:") or lowered.startswith("error in ") or lowered.startswith("[provider_error]")

    @staticmethod
    def _compact_after_context_overflow(
        messages: List[Dict[str, str]], provider: Any, kwargs: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Compact one overflow retry without splitting tool call/result pairs."""
        try:
            from context import compact_messages, inspect

            current_tokens = int(inspect(messages).get("est_tokens", 0) or 0)
            advertised = (
                getattr(provider, "max_context", 0)
                or getattr(provider, "context_window", 0)
                or getattr(provider, "max_context_tokens", 0)
            )
            output_tokens = int(kwargs.get("max_tokens", 0) or 0)
            if advertised:
                target = int(advertised) - max(0, output_tokens)
            else:
                # An overflow response without metadata still gets a bounded
                # reduction; avoid an unbounded retry or a same-size replay.
                target = int(current_tokens * 0.70)
            target = max(256, target)
            compacted, dropped = compact_messages(
                messages, budget_tokens=target, keep_recent=4
            )
            if dropped and inspect(compacted).get("est_tokens", 0) < current_tokens:
                return compacted
        except Exception:
            logger.debug("context-overflow compaction retry unavailable", exc_info=True)
        return messages

    def _generate_with_fallbacks(self, messages: List[Dict[str, str]], fallback_mesh: List[str], **kwargs) -> str:
        """Try every provider in the mesh once (bounded by the mesh itself).

        Every failure contributes a redacted per-provider diagnostic —
        provider id, model, failure class, reason, elapsed — to the final
        ``Error: ...`` string so callers can see what was tried and why.
        """
        diagnostics: List[str] = []
        for fallback_id in fallback_mesh:
            if not self.breakers.allows(fallback_id):
                logger.info("⛔ [MESH_SKIP]: circuit open for %s", fallback_id)
                self.attempts.record(fallback_id, status="skipped", reason="circuit open")
                diagnostics.append(f"{fallback_id}: skipped (circuit open)")
                continue
            started = time.time()
            model = kwargs.get("model") or ""
            try:
                logger.info("🔄 [MESH_RECOVERY]: Attempting fallback to %s...", fallback_id)
                self.attempts.record(fallback_id, status="fallback", reason="mesh recovery")
                fallback_provider = self.factory.get_provider_by_id(fallback_id)
                if not fallback_provider:
                    self.attempts.record(fallback_id, status="skipped", reason="provider construction failed")
                    diagnostics.append(f"{fallback_id}: unavailable (provider construction failed)")
                    continue
                res = self._invoke(fallback_provider, fallback_id, messages, **kwargs)
                logger.info("✅ [MESH_RECOVERY]: Success via %s", fallback_id)
                return res
            except CircuitOpenError:
                diagnostics.append(f"{fallback_id}: skipped (circuit open)")
            except ProviderCallError as exc:
                diagnostics.append(
                    self._failure_diagnostic(fallback_id, model, exc.classification, time.time() - started)
                )
                if exc.classification.failure_class is FailureClass.AUTH_ERROR:
                    # Credentials are broken for this provider: no point retrying
                    # it, move straight on to the next provider in the mesh.
                    logger.info("🔑 [MESH_SKIP]: %s rejected credentials", fallback_id)
            except Exception as fallback_error:  # noqa: BLE001
                classification = classify_failure(fallback_error)
                self.last_failure = classification
                self.health.mark_failure(fallback_id, classification.failure_class.value)
                diagnostics.append(
                    self._failure_diagnostic(fallback_id, model, classification, time.time() - started)
                )
        if not diagnostics:
            return "Error: No responsive brain found in mesh."
        return f"Error: {'; '.join(diagnostics)}"

    @staticmethod
    def _failure_diagnostic(provider_id: str, model: str, classification: Classification, elapsed: float) -> str:
        """One redacted per-provider failure entry for fallback diagnostics."""
        reason = redact_secrets(classification.message)[:160] or classification.failure_class.value
        return f"{provider_id}({model or '?'}): {classification.failure_class.value}: {reason} ({elapsed:.1f}s)"

    @staticmethod
    def _stream_error_payload(provider_id: str, message: str, classification: Classification, elapsed: float) -> str:
        """``[PROVIDER_ERROR]`` stream marker: redacted reason first, then
        provider id, failure class and elapsed so diagnostics are complete."""
        return f"[PROVIDER_ERROR]: {message} ({provider_id}: {classification.failure_class.value}, {elapsed:.1f}s)"

    def provider_attempts(self) -> List[Dict[str, Any]]:
        """Return bounded, redacted provider-attempt diagnostics."""
        recorder = getattr(self, "attempts", None)
        return recorder.snapshot() if recorder is not None else []

    def breaker_status(self) -> Dict[str, Any]:
        """Circuit breaker snapshot for diagnostics/telemetry."""
        return self.breakers.all()

    def stream_generate(self, messages: Optional[List[Dict[str, str]]] = None, prompt: str = "", system_prompt: str = "", **kwargs):
        if messages is None:
            messages = []
            if system_prompt: messages.append({"role": "system", "content": system_prompt})
            if prompt: messages.append({"role": "user", "content": prompt})

        requested_provider = kwargs.pop("provider", None)
        requested_profile = kwargs.pop("profile", None)
        routing_prefs = self._pop_routing_prefs(kwargs)
        request_provider = self._request_provider(requested_provider, requested_profile)

        if self.mode == "HYBRID":
            # MOA doesn't support streaming well in current impl, fallback to cloud for stream
            use_heavy = True
        else:
            use_heavy = self._should_use_heavy_brain(messages)
        
        if not use_heavy and self._local_brain_enabled():
            self.total_local_calls += 1
            yield from self.kernel.local_brain.stream_generate(messages=messages)
            return

        if request_provider:
            self.total_cloud_calls += 1
            primary_id = self._provider_id(request_provider)
            breaker = self.breakers.get(primary_id)
            stream_kwargs = self._apply_model_limits(request_provider, kwargs)
            retry_policy = getattr(self, "retry_policy", RetryPolicy(max_attempts=1))
            max_attempts = max(1, int(getattr(retry_policy, "max_attempts", 1)))
            emitted_any = False
            last_error = "provider stream failed"
            last_classification = classify_failure(body="provider stream failed")
            last_elapsed = 0.0
            failed_provider_id = primary_id
            stream_messages = messages
            overflow_compacted = False
            # Permit one additional attempt only when the first overflow was
            # actually compacted; normal retry budgets remain unchanged.
            for attempt in range(1, max_attempts + 2):
                if attempt > max_attempts and not overflow_compacted:
                    break
                emitted_any = False
                try:
                    start = time.time()
                    breaker.before_call()
                    if not self._provider_credentials_usable(request_provider, primary_id):
                        raise RuntimeError("provider rejected credentials: missing or invalid api key")
                    if hasattr(request_provider, "stream_generate"):
                        for chunk in self._leased_stream(
                            request_provider,
                            request_provider.stream_generate(messages=stream_messages, **stream_kwargs),
                        ):
                            if self._looks_like_provider_error(chunk):
                                raise RuntimeError(str(chunk))
                            emitted_any = True
                            yield chunk
                    else:
                        # Non-stream adapters have no ``_leased_stream`` guard,
                        # so a consumer closing the generator mid-yield must
                        # still release the profile lease.
                        try:
                            result = request_provider.generate(messages=stream_messages, **stream_kwargs)
                            if self._looks_like_provider_error(result):
                                raise RuntimeError(str(result))
                            emitted_any = True
                            yield result
                        finally:
                            self._release_profile_lease(request_provider)
                    breaker.record_success()
                    self.health.mark_success(primary_id, (time.time() - start) * 1000)
                    self._release_profile_lease(request_provider)
                    return
                except Exception as e:
                    provider_id = primary_id
                    classification = (
                        e.classification if isinstance(e, ProviderCallError) else classify_failure(e)
                    )
                    if not isinstance(e, CircuitOpenError):
                        breaker.record_failure()
                    self.last_failure = classification
                    self.health.mark_failure(provider_id, classification.failure_class.value)
                    last_error = redact_secrets(classification.message) or classification.failure_class.value
                    last_classification = classification
                    last_elapsed = time.time() - start
                    failed_provider_id = provider_id
                    # Once bytes from a provider have reached the caller,
                    # switching providers would splice two unrelated answers
                    # into one stream. Explicit provider selection is also
                    # authoritative and must not silently reroute.
                    if emitted_any or requested_provider:
                        self._release_profile_lease(request_provider)
                        yield self._stream_error_payload(provider_id, last_error, last_classification, last_elapsed)
                        return
                    if classification.failure_class is FailureClass.CONTEXT_OVERFLOW and not overflow_compacted:
                        compacted = self._compact_after_context_overflow(
                            stream_messages, request_provider, kwargs
                        )
                        if compacted != stream_messages:
                            stream_messages = compacted
                            overflow_compacted = True
                            continue
                    if isinstance(e, CircuitOpenError) or not classification.retryable or attempt >= max_attempts:
                        break
                    delay = retry_policy.compute_delay(attempt, classification.retry_after)
                    if delay > 0:
                        time.sleep(delay)

            # No primary output was emitted and the bounded retry policy is
            # exhausted. Continue into the existing provider fallback mesh.
            self._release_profile_lease(request_provider)
            if not requested_provider:
                for fallback_id in self._fallback_mesh(messages=stream_messages, streaming=True, active_provider=request_provider, prefs=routing_prefs):
                    fallback_emitted = False
                    fb_breaker = self.breakers.get(fallback_id)
                    if not fb_breaker.allows():
                        continue
                    fallback_provider = None
                    try:
                        start = time.time()
                        fb_breaker.before_call()
                        fallback_provider = self.factory.get_provider_by_id(fallback_id)
                        if fallback_provider and not self._provider_credentials_usable(
                            fallback_provider, fallback_id
                        ):
                            # Factory resolution may acquire an exclusive
                            # profile lease before credentials are validated.
                            # Skipping this provider must release that lease;
                            # otherwise every failed stream fallback can pin a
                            # credential until its TTL expires.
                            self._release_profile_lease(fallback_provider)
                            continue
                        if fallback_provider:
                            fb_kwargs = self._apply_model_limits(fallback_provider, kwargs)
                            if hasattr(fallback_provider, "stream_generate"):
                                fb_iterator = self._leased_stream(
                                    fallback_provider,
                                    fallback_provider.stream_generate(messages=stream_messages, **fb_kwargs),
                                )
                            else:
                                fb_iterator = iter([fallback_provider.generate(messages=stream_messages, **fb_kwargs)])
                            try:
                                for chunk in fb_iterator:
                                    if self._looks_like_provider_error(chunk):
                                        raise RuntimeError(str(chunk))
                                    fallback_emitted = True
                                    yield chunk
                            finally:
                                self._release_profile_lease(fallback_provider)
                            fb_breaker.record_success()
                            self.health.mark_success(fallback_id, (time.time() - start) * 1000)
                            return
                    except Exception as fallback_error:
                        self._release_profile_lease(fallback_provider)
                        fb_classification = (
                            fallback_error.classification
                            if isinstance(fallback_error, ProviderCallError)
                            else classify_failure(fallback_error)
                        )
                        if not isinstance(fallback_error, CircuitOpenError):
                            fb_breaker.record_failure()
                        self.last_failure = fb_classification
                        self.health.mark_failure(fallback_id, fb_classification.failure_class.value)
                        last_error = redact_secrets(fb_classification.message) or fb_classification.failure_class.value
                        last_classification = fb_classification
                        last_elapsed = time.time() - start
                        failed_provider_id = fallback_id
                        if fallback_emitted:
                            break
                yield self._stream_error_payload(failed_provider_id, last_error, last_classification, last_elapsed)

    def provider_health(self) -> List[Dict[str, Any]]:
        return self.health.all()
