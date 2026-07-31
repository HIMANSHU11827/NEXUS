import logging
import os
import time
from typing import Any, Dict, List, Optional

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
        self.health = ProviderHealthRegistry()
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

    def set_override(self, provider_id: str):
        """Forces the router to use a specific provider."""
        new_provider = self.factory.get_provider_by_id(provider_id)
        if new_provider:
            self.provider = new_provider
            logger.info(f"🧠 [ROUTER_OVERRIDE]: Brain switched to {provider_id}")

    def _get_required_tier(self, messages: List[Dict[str, str]]) -> str:
        """Classifies the task into an intelligence tier (1M to 1T+)."""
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        if not user_msgs: return "NANO"
        
        last_input = user_msgs[-1].lower()
        
        # Use the IntentEngine for high-fidelity classification
        from cognition.intent_engine import NexusIntent
        intent = self.intent_engine.classify(last_input)
        
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

        # 🏎️ [HYBRID_MODE]: Use MOA for maximum reasoning
        if self.mode == "HYBRID":
            logger.info("⚡ [HYBRID]: Activating MOA Intelligence Mesh...")
            return self.kernel.moa.aggregate(messages=messages, **kwargs)

        use_heavy = self._should_use_heavy_brain(messages)
        
        if not use_heavy and self._local_brain_enabled():
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
        fallback_mesh = self._fallback_mesh(messages=messages)

        if self.provider:
            provider_id = self._provider_id(self.provider)
            try:
                self.total_cloud_calls += 1
                return self._invoke(self.provider, provider_id, messages, **kwargs)
            except Exception as e:
                logger.warning(
                    "Primary brain (%s) failed: %s",
                    type(self.provider).__name__, redact_secrets(e),
                )
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

    def _invoke(self, provider: Any, provider_id: str, messages: List[Dict[str, str]],
                streaming: bool = False, **kwargs) -> str:
        """Single provider call guarded by retry/backoff + circuit breaker."""
        if hasattr(provider, "validate_api_key") and not provider.validate_api_key():
            classification = classify_failure(body="missing or invalid api key")
            self.last_failure = classification
            self.health.mark_failure(provider_id, classification.failure_class.value)
            raise ProviderCallError(classification, provider_id)

        call_kwargs = self._apply_model_limits(provider, kwargs)
        start = time.time()

        def _on_failure(classification: Classification, attempt: int) -> None:
            self.last_failure = classification
            self.health.mark_failure(provider_id, classification.failure_class.value)

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
        except TypeError:
            # Provider does not accept the clamped kwargs (e.g. no max_tokens
            # parameter) — retry once with the caller's original kwargs.
            result = call_with_reliability(
                provider_id,
                provider.generate,
                messages=messages,
                policy=self.retry_policy,
                breakers=self.breakers,
                on_attempt_failure=_on_failure,
                **kwargs,
            )
        self.health.mark_success(provider_id, (time.time() - start) * 1000)
        return result

    def _fallback_mesh(self, messages: Optional[List[Dict[str, str]]] = None, *, streaming: bool = False) -> List[str]:
        """Return provider IDs ordered by capability and recent health."""
        try:
            cfg = self.kernel.config.get("task_routing_auto", {})
            candidates = list(cfg.keys()) if isinstance(cfg, dict) else []
        except Exception:
            candidates = []
        if not candidates:
            candidates = ["openrouter", "gemini", "groq", "openai", "ollama", "lm_studio"]
        active = getattr(self.provider, "provider_name", "")
        ordered = [c for c in candidates if c != active]
        text = "\n".join(m.get("content", "") for m in messages or [])
        needs_vision = any(k in text.lower() for k in ["image", "screenshot", "vision", "multimodal", "os_", "ui_automation", "browser", "desktop"])
        prefer_local = self.mode == "LOCAL"
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

    def _generate_with_fallbacks(self, messages: List[Dict[str, str]], fallback_mesh: List[str], **kwargs) -> str:
        last_error = "No responsive brain found in mesh."
        for fallback_id in fallback_mesh:
            if not self.breakers.allows(fallback_id):
                logger.info("⛔ [MESH_SKIP]: circuit open for %s", fallback_id)
                continue
            try:
                logger.info("🔄 [MESH_RECOVERY]: Attempting fallback to %s...", fallback_id)
                fallback_provider = self.factory.get_provider_by_id(fallback_id)
                if not fallback_provider:
                    continue
                res = self._invoke(fallback_provider, fallback_id, messages, **kwargs)
                logger.info("✅ [MESH_RECOVERY]: Success via %s", fallback_id)
                return res
            except CircuitOpenError as exc:
                last_error = redact_secrets(exc)
            except ProviderCallError as exc:
                last_error = redact_secrets(exc)
                if exc.classification.failure_class is FailureClass.AUTH_ERROR:
                    # Credentials are broken for this provider: no point retrying
                    # it, move straight on to the next provider in the mesh.
                    logger.info("🔑 [MESH_SKIP]: %s rejected credentials", fallback_id)
            except Exception as fallback_error:  # noqa: BLE001
                classification = classify_failure(fallback_error)
                self.last_failure = classification
                self.health.mark_failure(fallback_id, classification.failure_class.value)
                last_error = redact_secrets(classification.message) or classification.failure_class.value
        return f"Error: {last_error}"

    def breaker_status(self) -> Dict[str, Any]:
        """Circuit breaker snapshot for diagnostics/telemetry."""
        return self.breakers.all()

    def stream_generate(self, messages: Optional[List[Dict[str, str]]] = None, prompt: str = "", system_prompt: str = "", **kwargs):
        if messages is None:
            messages = []
            if system_prompt: messages.append({"role": "system", "content": system_prompt})
            if prompt: messages.append({"role": "user", "content": prompt})

        if self.mode == "HYBRID":
            # MOA doesn't support streaming well in current impl, fallback to cloud for stream
            use_heavy = True
        else:
            use_heavy = self._should_use_heavy_brain(messages)
        
        if not use_heavy and self._local_brain_enabled():
            self.total_local_calls += 1
            yield from self.kernel.local_brain.stream_generate(messages=messages)
            return

        if self.provider:
            self.total_cloud_calls += 1
            emitted_any = False
            primary_id = self._provider_id(self.provider)
            breaker = self.breakers.get(primary_id)
            try:
                start = time.time()
                breaker.before_call()
                if hasattr(self.provider, "validate_api_key") and not self.provider.validate_api_key():
                    raise RuntimeError("provider rejected credentials: missing or invalid api key")
                stream_kwargs = self._apply_model_limits(self.provider, kwargs)
                if hasattr(self.provider, "stream_generate"):
                    for chunk in self.provider.stream_generate(messages=messages, **stream_kwargs):
                        if self._looks_like_provider_error(chunk):
                            raise RuntimeError(str(chunk))
                        emitted_any = True
                        yield chunk
                else:
                    result = self.provider.generate(messages=messages, **stream_kwargs)
                    if self._looks_like_provider_error(result):
                        raise RuntimeError(str(result))
                    emitted_any = True
                    yield result
                breaker.record_success()
                self.health.mark_success(primary_id, (time.time() - start) * 1000)
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
                # Once bytes from a provider have reached the caller, switching
                # providers would splice two unrelated answers into one stream.
                if emitted_any:
                    yield f"[PROVIDER_ERROR]: {last_error}"
                    return
                for fallback_id in self._fallback_mesh(messages=messages, streaming=True):
                    fallback_emitted = False
                    fb_breaker = self.breakers.get(fallback_id)
                    if not fb_breaker.allows():
                        continue
                    try:
                        fb_breaker.before_call()
                        fallback_provider = self.factory.get_provider_by_id(fallback_id)
                        if fallback_provider and fallback_provider.validate_api_key():
                            start = time.time()
                            fb_kwargs = self._apply_model_limits(fallback_provider, kwargs)
                            if hasattr(fallback_provider, "stream_generate"):
                                for chunk in fallback_provider.stream_generate(messages=messages, **fb_kwargs):
                                    if self._looks_like_provider_error(chunk):
                                        raise RuntimeError(str(chunk))
                                    fallback_emitted = True
                                    yield chunk
                            else:
                                result = fallback_provider.generate(messages=messages, **fb_kwargs)
                                if self._looks_like_provider_error(result):
                                    raise RuntimeError(str(result))
                                fallback_emitted = True
                                yield result
                            fb_breaker.record_success()
                            self.health.mark_success(fallback_id, (time.time() - start) * 1000)
                            return
                    except Exception as fallback_error:
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
                        if fallback_emitted:
                            break
                yield f"[PROVIDER_ERROR]: {last_error}"

    def provider_health(self) -> List[Dict[str, Any]]:
        return self.health.all()
