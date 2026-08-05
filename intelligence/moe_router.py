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
        if not task_cfg:
            return {}
        # Classify the task from the latest user message and select that task's
        # config (per-task routing). Fall back to the first entry if no match.
        text = ""
        for m in reversed(messages or []):
            if m.get("role") == "user":
                text = (m.get("content") or "").lower()
                break
        # Keyword classifier first (no embeddings needed): score each routing
        # key by keyword overlap on the prompt (providers/model_bench.py). The
        # legacy substring scan below stays as the true fallback so unannotated
        # routing tables keep their exact behavior.
        try:
            from providers import model_bench
            keyword_task = model_bench.classify_task(text, candidates=list(task_cfg))
            if keyword_task:
                return dict(task_cfg.get(keyword_task, {}))
        except Exception:
            logger.debug("intelligence/moe_router.py: keyword classifier unavailable; using substring match", exc_info=True)
        # Pick the task whose key appears in the prompt (longest/most-specific match)
        matched = None
        for task, c in task_cfg.items():
            if task and task.lower() in text:
                if matched is None or len(task) > len(matched):
                    matched = task
        chosen = matched or next(iter(task_cfg))
        return dict(task_cfg.get(chosen, {}))

    @staticmethod
    def _preference_tier(prefs: Optional[dict] = None) -> str:
        """Map caller preference kwargs (preferred/latency_tier/cost_tier) to
        a routing tier. Optional; defaults to the NEXUS_HEAVY_MODE/env policy."""
        from providers import model_bench
        return model_bench.resolve_tier(
            preferred=(prefs or {}).get("preferred"),
            latency_tier=(prefs or {}).get("latency_tier"),
            cost_tier=(prefs or {}).get("cost_tier"),
        )

    def _ranked_primary(self, messages: List[Dict[str, str]], prefs: Optional[dict] = None) -> str:
        """Task-aware primary provider pick among the configured fallback chain.

        Ranks the chain by per-task benchmark score with latency/cost hard
        filters (providers/model_bench.py). Returns "" when ranking is not
        usable so callers keep their exact legacy default-provider behavior.
        """
        try:
            from providers import model_bench
            text = " ".join(
                str(m.get("content", "")) for m in (messages or [])
                if isinstance(m.get("content"), str)
            )
            task = model_bench.classify_task(text)
            if not task:
                return ""
            loader = getattr(self.factory, "loader", None)
            cfg = loader.get("provider", {}) if loader is not None else {}
            if not isinstance(cfg, dict):
                return ""
            chain = cfg.get("fallback_chain") or []
            if not chain:
                return ""
            ranked = model_bench.rank_models(
                task,
                [self._normalize_provider_id(c) for c in chain],
                tier=self._preference_tier(prefs),
            )
            return self._normalize_provider_id(ranked[0]) if ranked else ""
        except Exception:
            return ""

    @staticmethod
    def _normalize_provider_id(provider: Any) -> str:
        """Canonicalize provider aliases at the routing boundary."""
        value = str(provider or "").strip().lower().replace("-", "_").replace(" ", "_")
        return {"lmstudio": "lm_studio", "lm__studio": "lm_studio"}.get(value, value)

    def set_override(self, provider: str, profile: Optional[str] = None):
        canonical = self._normalize_provider_id(provider)
        self.provider_override = canonical
        os.environ["NEXUS_PROVIDER"] = canonical
        if profile:
            self.profile_override = profile

    def _get_provider_name(self, messages: Optional[List[Dict[str, str]]] = None, prefs: Optional[dict] = None) -> str:
        if self.provider_override:
            return self._normalize_provider_id(self.provider_override)
        matched = self._get_task_config(messages or []) if messages else {}
        if matched.get("provider"):
            return self._normalize_provider_id(matched["provider"])
        # Task-aware selection before the configured default: rank the fallback
        # chain by benchmark quality + latency/cost hard limits. On any failure
        # this returns "" and we keep the legacy default-provider behavior.
        ranked = self._ranked_primary(messages or [], prefs)
        if ranked:
            return self._normalize_provider_id(ranked)
        provider_cfg = self.factory.loader.get("provider", {})
        if isinstance(provider_cfg, dict):
            return self._normalize_provider_id(provider_cfg.get("default_provider", "openai"))
        return "openai"

    def _get_profile_name(self, messages: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
        if self.profile_override:
            return self.profile_override
        matched = self._get_task_config(messages or []) if messages else {}
        if matched.get("profile"):
            return str(matched["profile"])
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
        provider_name = self._normalize_provider_id(provider_name)
        offline = bool(getattr(self.factory, "offline_mode", lambda: False)())
        local_name = getattr(self.factory, "_is_local_provider_name", None)
        is_local = bool(local_name(provider_name)) if callable(local_name) else str(provider_name).lower() in {
            "lm_studio", "lm-studio", "ollama", "local"
        }
        if offline and not is_local:
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
        # Optional routing-preference hints (preferred/latency_tier/cost_tier)
        # tune the task-aware ranking tiers; they never reach the provider.
        routing_prefs = {}
        for _key in ("preferred", "latency_tier", "cost_tier"):
            _value = kwargs.pop(_key, None)
            if _value:
                routing_prefs[_key] = _value
        explicit_provider = str(kwargs.pop("provider", "") or "").strip()
        explicit_profile = kwargs.pop("profile", None)
        provider_name = self._normalize_provider_id(explicit_provider) if explicit_provider else self._get_provider_name(messages, routing_prefs)
        profile_name = explicit_profile or self._get_profile_name(messages)
        model_override = str(kwargs.pop("model", "") or "")
        attempted_providers = set()
        attempted_profiles = set()
        error = None

        for attempt in range(8):
            provider = self._resolve_with_auto_fallback(provider_name, profile_name)
            if provider is None:
                logger.error(
                    "[PROVIDER_RESOLVE_FAILED] provider=%s profile=%s attempt=%s",
                    provider_name,
                    profile_name or "",
                    attempt,
                )
                break
            self._apply_task_config(provider, messages)
            if model_override and hasattr(provider, "model"):
                provider.model = model_override

            saw_chunk = False
            error_probe = ""
            try:
                # Do not serialize unset optional fields (notably
                # ``max_tokens=None``). Some local OpenAI-compatible servers
                # reject or stall on explicit JSON nulls.
                call_kwargs = {key: value for key, value in kwargs.items() if value is not None}
                chunk_iter = (
                    provider.stream_chat(messages, **call_kwargs)
                    if hasattr(provider, "stream_chat")
                    else provider.stream_generate(messages=messages, **call_kwargs)
                )
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

        # Preserve the actual redacted provider failure for diagnosis. The UI
        # should remain concise, but silently collapsing every failure into
        # "provider unavailable" made valid credentials and HTTP errors
        # indistinguishable.
        from providers.reliability import redact_secrets
        logger.error(
            "[FALLBACK_EXHAUSTED] All providers/profiles failed for %s; last_error=%s",
            provider_name,
            redact_secrets(error or "no provider response"),
        )
        offline = bool(getattr(self.factory, "offline_mode", lambda: False)())
        if offline and provider_name in {"lm_studio", "lm-studio", "ollama", "local"}:
            detail = "LM Studio is not reachable. Start the local server and load a model, then retry."
        elif offline:
            detail = "Offline mode is enabled; remote providers are disabled."
        else:
            detail = f"All providers unavailable. Last error: {error}"
        yield f"[PROVIDER_ERROR]: {detail}"

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        parts = list(self.stream_generate(messages, **kwargs))
        return "".join(parts)

    def generate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self.chat(messages, **kwargs)
