import logging
import os
import time
from typing import List, Dict, Any, Optional

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
        from cognition.intent_engine import IntentEngine
        self.intent_engine = IntentEngine(self)

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
            try:
                start = time.time()
                self.total_cloud_calls += 1
                if hasattr(self.provider, "validate_api_key") and not self.provider.validate_api_key():
                    raise RuntimeError("provider has no valid credentials or local backend")
                result = self.provider.generate(messages=messages, **kwargs)
                if self._looks_like_provider_error(result):
                    raise RuntimeError(result)
                self.health.mark_success(getattr(self.provider, "provider_name", type(self.provider).__name__), (time.time() - start) * 1000)
                return result
            except Exception as e:
                self.health.mark_failure(getattr(self.provider, "provider_name", type(self.provider).__name__), e)
                logger.warning(f"Primary brain ({type(self.provider).__name__}) failed: {e}")
                return self._generate_with_fallbacks(messages, fallback_mesh, **kwargs)
        
        return self._generate_with_fallbacks(messages, fallback_mesh, **kwargs)

    def _fallback_mesh(self, messages: Optional[List[Dict[str, str]]] = None, *, streaming: bool = False) -> List[str]:
        """Return provider IDs ordered by capability and recent health."""
        candidates = self.kernel.config.get_active_providers()
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
        return selected or ordered

    @staticmethod
    def _looks_like_provider_error(result: Any) -> bool:
        if not isinstance(result, str):
            return False
        lowered = result.strip().lower()
        return lowered.startswith("error:") or lowered.startswith("error in ") or lowered.startswith("[provider_error]")

    def _generate_with_fallbacks(self, messages: List[Dict[str, str]], fallback_mesh: List[str], **kwargs) -> str:
        last_error = "No responsive brain found in mesh."
        for fallback_id in fallback_mesh:
            try:
                logger.info(f"🔄 [MESH_RECOVERY]: Attempting fallback to {fallback_id}...")
                fallback_provider = self.factory.get_provider_by_id(fallback_id)
                if fallback_provider and fallback_provider.validate_api_key():
                    start = time.time()
                    res = fallback_provider.generate(messages=messages, **kwargs)
                    if self._looks_like_provider_error(res):
                        raise RuntimeError(res)
                    self.health.mark_success(fallback_id, (time.time() - start) * 1000)
                    logger.info(f"✅ [MESH_RECOVERY]: Success via {fallback_id}")
                    return res
            except Exception as fallback_error:
                self.health.mark_failure(fallback_id, fallback_error)
                last_error = self.health.normalize_error(fallback_error)
        return f"Error: {last_error}"

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
            try:
                start = time.time()
                if hasattr(self.provider, "validate_api_key") and not self.provider.validate_api_key():
                    raise RuntimeError("provider has no valid credentials or local backend")
                if hasattr(self.provider, "stream_generate"):
                    for chunk in self.provider.stream_generate(messages=messages, **kwargs):
                        yield chunk
                else:
                    yield self.provider.generate(messages=messages, **kwargs)
                self.health.mark_success(getattr(self.provider, "provider_name", type(self.provider).__name__), (time.time() - start) * 1000)
            except Exception as e:
                provider_id = getattr(self.provider, "provider_name", type(self.provider).__name__)
                self.health.mark_failure(provider_id, e)
                last_error = self.health.normalize_error(e)
                for fallback_id in self._fallback_mesh(messages=messages, streaming=True):
                    try:
                        fallback_provider = self.factory.get_provider_by_id(fallback_id)
                        if fallback_provider and fallback_provider.validate_api_key():
                            start = time.time()
                            if hasattr(fallback_provider, "stream_generate"):
                                for chunk in fallback_provider.stream_generate(messages=messages, **kwargs):
                                    yield chunk
                            else:
                                yield fallback_provider.generate(messages=messages, **kwargs)
                            self.health.mark_success(fallback_id, (time.time() - start) * 1000)
                            return
                    except Exception as fallback_error:
                        self.health.mark_failure(fallback_id, fallback_error)
                        last_error = self.health.normalize_error(fallback_error)
                yield f"[PROVIDER_ERROR]: {last_error}"

    def provider_health(self) -> List[Dict[str, Any]]:
        return self.health.all()
