import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from providers.factory import NexusProviderFactory

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")

_QUOTA_ERRORS = ("quota", "rate_limit", "429", "insufficient_quota", "exhausted", "billing", "subscription")
_PROVIDER_ERRORS = (
    "error:", "error in ", "[provider_error]", "authentication fails",
    "authentication_error", "invalid api key", "invalid key", "unauthorized",
)
_auto_routing_done = False


class NexusMoERouter:
    def __init__(self):
        global _auto_routing_done
        self.factory = NexusProviderFactory()
        self.base_router = self
        self.mode = "auto"
        self.provider_override = ""
        self.profile_override = ""
        if not _auto_routing_done:
            _auto_routing_done = True
            self._run_auto_detect()

    def _run_auto_detect(self):
        try:
            from providers.auto_detect import ensure_auto_routing
            ensure_auto_routing()
        except Exception as e:
            logger.debug(f"auto_detect skipped: {e}")
        try:
            from providers.auto_heal import start_auto_heal
            start_auto_heal()
        except Exception as e:
            logger.debug(f"auto_heal skipped: {e}")

    def _load_task_routing(self) -> dict:
        manual = {}
        provider_cfg = self.factory.loader.get("provider", {})
        if isinstance(provider_cfg, dict):
            manual = provider_cfg.get("task_routing", {}) or {}

        config_dir = Path(__file__).resolve().parent.parent / "config"
        auto_path = config_dir / "task_routing_auto.yml"
        auto = {}
        if auto_path.exists():
            try:
                import yaml
                data = yaml.safe_load(auto_path.read_text()) or {}
                auto = data.get("task_routing", {}) or {}
            except Exception:
                logger.warning("intelligence/moe_router.py:52 _load_task_routing: suppressed error", exc_info=True)
                pass

        merged = dict(auto)
        merged.update(manual)
        return merged

    def _get_task_config(self, messages: List[Dict[str, str]]) -> dict:
        task_cfg = self._load_task_routing()
        cfg = {}
        for task, c in task_cfg.items():
            cfg.update(c)
            break
        return cfg

    def set_override(self, provider: str, profile: Optional[str] = None):
        self.provider_override = provider
        os.environ["NEXUS_PROVIDER"] = provider
        if profile:
            self.profile_override = profile

    def _get_provider_name(self) -> str:
        if self.provider_override:
            return self.provider_override
        task_cfg = self._load_task_routing()
        for c in task_cfg.values():
            if isinstance(c, dict) and c.get("provider"):
                return c["provider"]
        provider_cfg = self.factory.loader.get("provider", {})
        if isinstance(provider_cfg, dict):
            return provider_cfg.get("default_provider", "openai")
        return "openai"

    def _get_profile_name(self) -> Optional[str]:
        if self.profile_override:
            return self.profile_override
        task_cfg = self._load_task_routing()
        for c in task_cfg.values():
            if isinstance(c, dict) and c.get("profile"):
                return c["profile"]
        return None

    def _is_quota_error(self, error: str) -> bool:
        low = str(error).lower()
        return any(q in low for q in _QUOTA_ERRORS)

    def _is_provider_error(self, value: str) -> bool:
        low = str(value or "").strip().lower()
        return low.startswith("[all providers unavailable") or any(
            low.startswith(marker) for marker in _PROVIDER_ERRORS[:3]
        ) or any(
            marker in low for marker in _PROVIDER_ERRORS[3:]
        )

    def _looks_like_provider_error(self, value: str) -> bool:
        """Shared contract used by NexusLoop to fail runs truthfully."""
        return self._is_provider_error(value)

    def _resolve_with_auto_fallback(self, provider_name: str, profile_name: Optional[str] = None, attempt: int = 0) -> Any:
        if attempt > 3:
            return None
        provider = self.factory.get_provider_by_name("cloud", provider_name, profile=profile_name)
        if hasattr(provider, "_fallback_attempt"):
            provider._fallback_attempt = attempt
        return provider

    def configure_thinking(self, enabled: bool):
        try:
            provider = self._get_provider()
            if provider and hasattr(provider, "configure_thinking"):
                provider.configure_thinking(enabled)
        except Exception as e:
            logger.debug(f"configure_thinking failed: {e}")

    def _apply_task_config(self, provider, messages):
        cfg = self._get_task_config(messages)
        model = cfg.get("model")
        if model:
            provider.model = model
        max_tk = cfg.get("max_tokens")
        if max_tk and hasattr(provider, "max_tokens"):
            provider.max_tokens = max_tk

    def _try_call(self, messages, provider_name: str, profile_name: Optional[str] = None):
        provider = self._resolve_with_auto_fallback(provider_name, profile_name)
        if provider is None:
            return None, None

        self._apply_task_config(provider, messages)

        try:
            if hasattr(provider, "stream_chat"):
                chunks = list(provider.stream_chat(messages))
            else:
                chunks = list(provider.stream_generate(messages=messages))
            result = "".join(chunks)
            if self._is_quota_error(result):
                return None, result[:200]
            return result, None
        except Exception as e:
            return None, str(e)

    def stream_generate(self, messages: List[Dict[str, str]], **kwargs):
        provider_name = str(kwargs.pop("provider", "") or self._get_provider_name())
        profile_name = kwargs.pop("profile", None) or self._get_profile_name()
        model_override = str(kwargs.pop("model", "") or "")
        attempted_providers = set()
        attempted_profiles = set()
        error = None

        for attempt in range(8):
            provider = self._resolve_with_auto_fallback(provider_name, profile_name)
            if provider is None:
                break
            self._apply_task_config(provider, messages)
            if model_override and hasattr(provider, "model"):
                provider.model = model_override

            try:
                chunk_iter = (
                    provider.stream_chat(messages, **kwargs)
                    if hasattr(provider, "stream_chat")
                    else provider.stream_generate(messages=messages, **kwargs)
                )
                saw_chunk = False
                error_probe = ""
                for chunk in chunk_iter:
                    text = str(chunk or "")
                    if not text:
                        continue
                    error_probe = (error_probe + text)[:1000]
                    if self._is_provider_error(error_probe):
                        raise RuntimeError(error_probe)
                    saw_chunk = True
                    yield text
                if saw_chunk:
                    return
                error = None
            except Exception as e:
                error = str(e)
                if saw_chunk:
                    yield f"[PROVIDER_ERROR]: {error}"
                    return

            is_quota = self._is_quota_error(error or "")

            if is_quota:
                if profile_name:
                    from providers.profiles import load_profile_store
                    store = load_profile_store()
                    store.mark_inactive(provider_name, profile_name)
                    next_profile = self.factory.next_profile_fallback(provider_name, profile_name)
                    if next_profile and next_profile not in attempted_profiles:
                        attempted_profiles.add(profile_name)
                        profile_name = next_profile
                        logger.info(f"[AUTO] Quota hit on {provider_name}/{profile_name}, trying next profile")
                        continue

                profile_name = None
                next_prov = self.factory.next_provider_fallback(provider_name)
                if next_prov and next_prov not in attempted_providers:
                    attempted_providers.add(provider_name)
                    provider_name = next_prov
                    logger.info(f"[AUTO] Quota exhausted, falling back to provider: {provider_name}")
                    continue

            if attempt < 7:
                if profile_name:
                    next_profile = self.factory.next_profile_fallback(provider_name, profile_name)
                    if next_profile and next_profile not in attempted_profiles:
                        attempted_profiles.add(profile_name)
                        profile_name = next_profile
                        continue
                profile_name = None
                next_prov = self.factory.next_provider_fallback(provider_name)
                if next_prov and next_prov not in attempted_providers:
                    attempted_providers.add(provider_name)
                    provider_name = next_prov
                    continue

            break

        logger.error(f"[FALLBACK_EXHAUSTED] All providers/profiles failed for: {provider_name}")
        yield f"[PROVIDER_ERROR]: All providers unavailable. Last error: {error}"

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        parts = list(self.stream_generate(messages, **kwargs))
        return "".join(parts)

    def generate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self.chat(messages, **kwargs)
