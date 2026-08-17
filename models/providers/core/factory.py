import asyncio
import importlib
import logging
import os
import threading
from typing import Any, List, Optional

from nexus.common.singleton import ThreadSafeSingleton
from models.providers.core.reliability import redact_secrets

logger = logging.getLogger(__name__)
_oauth_refresh_locks: dict[str, threading.Lock] = {}
_oauth_refresh_locks_guard = threading.Lock()


def _oauth_refresh_lock(provider_id: str) -> threading.Lock:
    key = str(provider_id or "")
    with _oauth_refresh_locks_guard:
        return _oauth_refresh_locks.setdefault(key, threading.Lock())


def _run_coro_safely(coro):
    """Run an async coroutine whether or not an event loop is already running.

    ``asyncio.run`` raises ``RuntimeError`` when called inside an already-running
    loop (GUI/TUI/API request contexts). Using a per-thread loop via
    ``asyncio.run`` is only safe at the top level, so detect the running loop and
    fall back to ``run_until_complete`` on the current thread's loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread — safe to drive our own.
        return asyncio.run(coro)
    # A loop is already running; run_until_complete is forbidden on a running
    # loop, so drive a fresh loop on a background thread and return its result.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _environment_value(name: str) -> str:
    """Read a provider secret without requiring detached Windows processes to
    inherit a refreshed environment block.

    Process environment remains the primary source. The Windows user profile
    fallback is only used when a launcher (for example WMI/Task Scheduler)
    starts the API with an older process environment.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value or "").strip()
        except (FileNotFoundError, OSError, TypeError):
            pass
    return ""


def get_loader() -> Any:
    mod = importlib.import_module("configure.config_loader")
    return getattr(mod, "NexusConfigLoader")()


def _configured_api_key(value: Any) -> Optional[str]:
    key = str(value or "").strip()
    if not key or "YOUR_" in key:
        return None
    if key.startswith("${") and key.endswith("}"):
        return _environment_value(key[2:-1]) or None
    return key


def _resolve_api_key(provider_id: str, profile_name: Optional[str] = None) -> Optional[str]:
    try:
        from models.providers.core.profiles import resolve_api_key
        key = resolve_api_key(provider_id, profile_name)
        if key:
            return key
    except Exception:
        logger.warning("providers/factory.py:29 _resolve_api_key: suppressed error", exc_info=True)
        pass
    try:
        from models.providers.auth.oauth.providers.autoregister import register_all_oauth_providers
        from models.providers.auth.oauth.registry import get_oauth_provider
        from models.providers.auth.oauth.storage import load_oauth_token_store
        register_all_oauth_providers()
        store = load_oauth_token_store()
        credentials = store.get(provider_id)
        if credentials is not None:
            oauth_provider = get_oauth_provider(provider_id)
            import time
            if time.time() * 1000 >= credentials.expires and oauth_provider is not None:
                try:
                    with _oauth_refresh_lock(provider_id):
                        current = store.get(provider_id)
                        if current is not None and time.time() * 1000 < current.expires:
                            credentials = current
                        else:
                            credentials = _run_coro_safely(
                                oauth_provider.refresh_token(current or credentials)
                            )
                            store.set(provider_id, credentials)
                except Exception:
                    logger.warning("OAuth token refresh failed for provider %s; refusing expired credentials", provider_id, exc_info=True)
                    return None
            if oauth_provider is not None:
                return oauth_provider.get_api_key(credentials)
            if time.time() * 1000 >= credentials.expires:
                logger.warning("OAuth token for provider %s is expired and no OAuth provider is registered", provider_id)
                return None
            return credentials.access
    except Exception:
        logger.warning("providers/factory.py:48 : suppressed error", exc_info=True)
        pass
    return None


MAPPINGS = {
    "openrouter": ("providers.openrouter", "OpenRouterProvider"),
    "nvidia": ("providers.nvidia", "NvidiaProvider"),
    "gemini": ("providers.google_gemini", "GoogleGeminiProvider"),
    "google_gemini": ("providers.google_gemini", "GoogleGeminiProvider"),
    "anthropic": ("providers.anthropic", "AnthropicProvider"),
    "openai": ("providers.openai", "OpenAIProvider"),
    "groq": ("providers.groq", "GroqProvider"),
    "qwen": ("providers.qwen", "QwenProvider"),
    "deepseek": ("providers.deepseek", "DeepSeekProvider"),
    "xai": ("providers.xai", "XAIProvider"),
    "grok": ("providers.xai", "XAIProvider"),
    "cohere": ("providers.cohere", "CohereProvider"),
    "mistral": ("providers.mistral", "MistralProvider"),
    "perplexity": ("providers.perplexity", "PerplexityProvider"),
    "together": ("providers.together", "TogetherProvider"),
    "lm_studio": ("providers.lm_studio", "LMStudioProvider"),
    "ollama": ("providers.ollama", "OllamaProvider"),
    "huggingface": ("providers.huggingface", "HuggingFaceProvider"),
    "sambanova": ("providers.sambanova", "SambaNovaProvider"),
    "fireworks": ("providers.fireworks", "FireworksProvider"),
    "azure_openai": ("providers.azure_openai", "AzureOpenAIProvider"),
    "replicate": ("providers.replicate", "ReplicateProvider"),
    "llama_cpp": ("providers.llama_cpp", "LlamaCPPProvider"),
    "zupra": ("providers.zupra", "ZupraProvider"),
    "vlm": ("providers.vlm", "VLMProvider"),
    "universal": ("providers.universal", "UniversalProvider"),
    "commandcode": ("providers.commandcode", "CommandCodeProvider"),
    # OpenAI-compatible API-key providers route through universal
    "deepinfra": ("providers.universal", "UniversalProvider"),
    "cerebras": ("providers.universal", "UniversalProvider"),
    "moonshot": ("providers.universal", "UniversalProvider"),
    "kimi": ("providers.universal", "UniversalProvider"),
    "stepfun": ("providers.universal", "UniversalProvider"),
    "zai": ("providers.universal", "UniversalProvider"),
    "venice": ("providers.universal", "UniversalProvider"),
    "novita": ("providers.universal", "UniversalProvider"),
    "byteplus": ("providers.universal", "UniversalProvider"),
    "volcengine": ("providers.universal", "UniversalProvider"),
    "arcee": ("providers.universal", "UniversalProvider"),
    "cloudflare_ai_gateway": ("providers.universal", "UniversalProvider"),
    "vercel_ai_gateway": ("providers.universal", "UniversalProvider"),
    "tencent_tokenhub": ("providers.universal", "UniversalProvider"),
    "qianfan": ("providers.universal", "UniversalProvider"),
    "litellm": ("providers.universal", "UniversalProvider"),
    "opencode": ("providers.opencode_cli", "OpenCodeCLIProvider"),
    "fal": ("providers.universal", "UniversalProvider"),
    "vydra": ("providers.universal", "UniversalProvider"),
    "synthetic": ("providers.universal", "UniversalProvider"),
    "gmi": ("providers.universal", "UniversalProvider"),
    "copilot_proxy": ("providers.universal", "UniversalProvider"),
    "vllm": ("providers.universal", "UniversalProvider"),
    "sglang": ("providers.universal", "UniversalProvider"),
    # OAuth-compatible providers
    "codex": ("providers.universal", "UniversalProvider"),
    "claude": ("providers.universal", "UniversalProvider"),
    "github_copilot": ("providers.universal", "UniversalProvider"),
    "minimax": ("providers.universal", "UniversalProvider"),
    "chutes": ("providers.universal", "UniversalProvider"),
}


class NexusProviderFactory(ThreadSafeSingleton):
    _provider = None

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        # Singleton-init race (found via real multi-agent hive run):
        # ``ThreadSafeSingleton.__new__`` publishes the instance before
        # ``__init__`` runs, so a concurrent caller can observe the instance
        # mid-initialization. ``self.loader``/``self.name`` were assigned only
        # *after* ``_initialized`` was set to True, so racing threads crashed
        # with ``AttributeError: 'NexusProviderFactory' object has no
        # attribute 'loader'`` (or 'name'). Hold the class lock for the whole
        # init block and publish ``_initialized`` LAST so the flag is only
        # ever observed when the instance is fully usable.
        with type(self)._lock:
            if getattr(self, "_initialized", False):
                return
            self.loader = get_loader()
            provider_config = self.loader.get("provider", {})
            provider_name = ""
            if isinstance(provider_config, dict):
                provider_name = str(provider_config.get("default_provider") or "").strip()
            self.group = self.loader.get_system("provider_group", "cloud")
            self.name = provider_name or self.loader.get_system("provider_name", "openrouter")
            self._consecutive_errors = 0
            self._initialized = True
            logger.info("ProviderFactory init: default=%r group=%r name=%r", provider_name, self.group, self.name)

    @staticmethod
    def offline_mode() -> bool:
        """Return whether remote provider access is explicitly disabled.

        Offline mode still permits local OpenAI-compatible servers such as LM
        Studio.  It is intentionally opt-in so existing cloud deployments do
        not change behavior unexpectedly.
        """
        return os.environ.get("NEXUS_OFFLINE_MODE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }

    @staticmethod
    def _is_local_provider(provider_id: str, provider: Any) -> bool:
        name = str(provider_id or "").strip().lower()
        endpoint = str(getattr(provider, "endpoint", "") or "").lower()
        return NexusProviderFactory._is_local_provider_name(name) or any(
            host in endpoint for host in ("127.0.0.1", "localhost", "::1")
        )

    @staticmethod
    def _is_local_provider_name(provider_id: str) -> bool:
        return str(provider_id or "").strip().lower() in {
            "lm_studio", "lm-studio", "ollama", "local"
        }

    def _load_provider_instance(self, target_name: str) -> Any:
        if target_name in MAPPINGS:
            mod_path, cls_name = MAPPINGS[target_name]
            mod = importlib.import_module(mod_path)
            return getattr(mod, cls_name)()
        target = target_name.replace('-', '_')
        mod_name = None
        for _cat in ("local", "api", "auth", "core"):
            cand = f"models.providers.{_cat}.{target}"
            try:
                importlib.import_module(cand)
                mod_name = cand
                break
            except ModuleNotFoundError:
                continue
        if mod_name is None:
            mod_name = f"providers.{target}"
        cls_name = "".join(p.capitalize() for p in target_name.replace("-", "_").split("_")) + "Provider"
        mod = importlib.import_module(mod_name)
        return getattr(mod, cls_name)()

    def get_provider_by_name(self, group: str, name: str, profile: Optional[str] = None) -> Any:
        try:
            provider_id = str(name or "").strip()
            profile_store = None
            selected_profile = None
            inst_config = self.loader.get_provider_config(provider_id)
            # NexusConfigLoader.get_provider_config() *pops* parent_provider while
            # merging, so it is never present in inst_config. Read the raw
            # provider block to recover the parent implementation name.
            parent = inst_config.get("parent_provider") or self._raw_parent(provider_id)
            target_name = str(parent if parent else provider_id).lower()

            provider = self._load_provider_instance(target_name)
            provider.model = inst_config.get("model") or provider.model
            provider.endpoint = inst_config.get("endpoint") or provider.endpoint

            # A named profile is the selected runtime connection, not only a
            # credential lookup. Apply its native model and endpoint as well so
            # GUI model/profile selection reaches local OpenAI-compatible
            # servers such as LM Studio.
            if profile:
                try:
                    from models.providers.core.profiles import load_profile_store
                    profile_store = load_profile_store()
                    selected_profile = profile_store.get_profile(provider_id, profile)
                    if selected_profile is not None:
                        profile_model = str(getattr(selected_profile, "model_id", "") or getattr(selected_profile, "model", "") or "").strip()
                        profile_endpoint = str(getattr(selected_profile, "endpoint", "") or "").strip()
                        if profile_model:
                            provider.model = profile_model
                        if profile_endpoint:
                            provider.endpoint = profile_endpoint
                except Exception:
                    logger.debug("factory: selected profile settings unavailable for %s/%s", provider_id, profile, exc_info=True)

            config_key = _configured_api_key(inst_config.get("api_key"))
            env_key = (
                _environment_value(f"{provider_id.upper()}_API_KEY")
                or _environment_value(f"{target_name.upper()}_API_KEY")
            )
            profile_key = _resolve_api_key(provider_id, profile) if profile else None
            oauth_key = None
            # OAuth credentials are profile-independent for the normal auth
            # path. Resolve them when config/env credentials did not already
            # provide a concrete key; previously this lookup happened only
            # when a named profile was supplied, silently dropping valid
            # tokens for providers such as Grok and OpenRouter.
            if not config_key and not env_key and not profile_key:
                oauth_key = _resolve_api_key(provider_id)
            key = config_key or profile_key or env_key or oauth_key
            credential_id = ""
            credential_source = ""
            if config_key:
                configured_value = str(inst_config.get("api_key") or "")
                if configured_value.strip().startswith("${"):
                    credential_id = f"env:{provider_id}"
                    credential_source = "environment"
                else:
                    credential_id = f"config:{provider_id}"
                    credential_source = "config"
            elif profile_key:
                credential_id = f"profile:{provider_id}:{profile}"
                credential_source = "profile"
            elif env_key:
                credential_id = f"env:{provider_id}"
                credential_source = "environment"
            elif oauth_key:
                credential_id = f"oauth:{provider_id}"
                credential_source = "oauth"
            if key:
                # Live credential refresh: reload_credentials() bakes the newly
                # resolved key into every auth header (raw + Authorization)
                # instead of assuming every provider uses a Bearer header.
                if hasattr(provider, "reload_credentials"):
                    provider.reload_credentials(key)
                else:
                    provider.api_key = key
                    if hasattr(provider, "headers"):
                        provider.headers["Authorization"] = f"Bearer {key}"
            elif parent and provider:
                # Read the PARENT provider's configured key (the intent of this
                # branch) — not the same child value that already evaluated falsy.
                try:
                    parent_cfg = self.loader.get_provider_config(target_name) or {}
                    parent_key = _configured_api_key(parent_cfg.get("api_key")) or _resolve_api_key(target_name)
                except Exception:
                    parent_key = None
                if parent_key:
                    credential_id = f"config:{target_name}"
                    credential_source = "parent_config"
                    if hasattr(provider, "reload_credentials"):
                        provider.reload_credentials(parent_key)
                    else:
                        provider.api_key = parent_key
                        if hasattr(provider, "headers"):
                            provider.headers["Authorization"] = f"Bearer {provider.api_key}"

            provider._provider_id = provider_id
            provider._profile_name = profile
            provider._credential_id = credential_id
            provider._credential_source = credential_source
            if profile_store is not None and selected_profile is not None:
                lease = profile_store.acquire_lease(provider_id, profile, ttl_seconds=120.0)
                if lease is None:
                    logger.info("provider profile is leased by another worker: %s/%s", provider_id, profile)
                    return None
                provider._profile_lease = lease
                provider._profile_store = profile_store
            return provider

        except Exception as e:
            logger.error("Failed to initialize requested provider %s: %s", name, redact_secrets(e))
            return None

    def _raw_parent(self, provider_id: str) -> Optional[str]:
        """Return providers.<id>.parent_provider straight from the raw config."""
        try:
            cfg = self.loader.get("provider", {}) or {}
            providers = cfg.get("providers", {}) if isinstance(cfg, dict) else {}
            entry = providers.get(provider_id) if isinstance(providers, dict) else None
            if isinstance(entry, dict):
                parent = entry.get("parent_provider")
                return str(parent) if parent else None
        except Exception:
            logger.debug("factory: could not read parent_provider for %s", provider_id, exc_info=True)
        return None

    def resolve_with_fallback(self, name: str, profile: Optional[str] = None, attempt: int = 0) -> Any:
        provider = self.get_provider_by_name("cloud", name, profile)
        if provider is not None and attempt > 0:
            provider._fallback_attempt = attempt
        return provider

    def next_profile_fallback(self, provider_id: str, current_profile: str) -> Optional[str]:
        try:
            from models.providers.core.profiles import load_profile_store
            store = load_profile_store()
            next_p = store.next_profile(provider_id, current_profile)
            if next_p:
                return next_p.name
        except Exception:
            logger.warning("providers/factory.py:182 next_profile_fallback: suppressed error", exc_info=True)
            pass
        return None

    def next_provider_fallback(self, current: str) -> Optional[str]:
        try:
            if self.offline_mode():
                return None
            cfg = self.loader.get("provider", {})
            chain = cfg.get("fallback_chain", []) if isinstance(cfg, dict) else []
            if current in chain:
                idx = chain.index(current)
                if idx + 1 < len(chain):
                    return chain[idx + 1]
        except Exception:
            logger.warning("providers/factory.py:194 next_provider_fallback: suppressed error", exc_info=True)
            pass
        return None

    def _auto_health(self) -> Any:
        """Best-effort persisted health registry for auto resolution.

        Only consulted when a health DB already exists on disk (the router
        writes one under ``<root>/.nexus/provider_health.sqlite3``); a missing
        DB means no signal yet, so every detected provider stays eligible.
        """
        try:
            from models.providers.core.health import ProviderHealthRegistry
            path = os.path.join(os.getcwd(), ".nexus", "provider_health.sqlite3")
            if os.path.exists(path):
                return ProviderHealthRegistry(store_path=path)
        except Exception:
            logger.debug("providers/factory.py: auto health registry unavailable", exc_info=True)
        return None

    def _resolve_auto_default(self) -> Optional[Any]:
        """Resolve ``default_provider: auto`` to the first working provider.

        Ordering is deliberately local-first: keyless local OpenAI-compatible
        servers that are actually running (LM Studio, Ollama, llama.cpp, VLM)
        beat keyed cloud providers. Each candidate is constructed and its
        credentials validated before selection; degraded providers (from the
        persisted health DB) are skipped. When nothing works, a diagnostic
        listing every candidate and why it was skipped is logged and None is
        returned so callers can surface the problem.
        """
        tried: List[str] = []
        try:
            from models.providers.core.auto_detect import detect_available_providers
            available = detect_available_providers() or {}
        except Exception:
            logger.debug("providers/factory.py: auto-detect unavailable", exc_info=True)
            available = {}
        if not available:
            logger.warning(
                "ProviderFactory: default_provider=auto resolved to nothing — "
                "no API keys, OAuth tokens, or running local servers detected"
            )
            return None

        ordered: List[str] = []
        for local_id in ("lm_studio", "ollama", "llama_cpp", "vlm"):
            if local_id in available and local_id not in ordered:
                ordered.append(local_id)
        for name in sorted(available.keys()):
            if name not in ordered:
                ordered.append(name)

        health = self._auto_health()
        for name in ordered:
            provider = self.get_provider_by_name(self.group, name)
            if provider is None:
                tried.append(f"{name}: failed to construct")
                continue
            is_local = self._is_local_provider(name, provider)
            if self.offline_mode() and not is_local:
                tried.append(f"{name}: skipped (offline mode blocks remote providers)")
                continue
            if health is not None:
                try:
                    if health.is_degraded(name):
                        tried.append(f"{name}: skipped (degraded per recent health)")
                        continue
                except Exception:
                    pass
            if is_local:
                logger.info("ProviderFactory: auto resolved local provider %r", name)
                return provider
            validator = getattr(provider, "validate_api_key", None)
            has_key = bool(validator()) if callable(validator) else bool(getattr(provider, "api_key", None))
            if not has_key:
                tried.append(f"{name}: no usable credential")
                continue
            logger.info("ProviderFactory: auto resolved keyed provider %r", name)
            return provider
        logger.warning("ProviderFactory: default_provider=auto found no working provider — tried: %s", "; ".join(tried))
        return None

    @staticmethod
    def _apply_env_model(provider: Any) -> None:
        """Apply the global ``NEXUS_MODEL`` override to a resolved provider.

        Mirrors the orchestrator contract where ``NEXUS_MODEL`` wins over the
        provider.yml model default when no explicit model kwarg is supplied.
        """
        if provider is None:
            return
        model = os.environ.get("NEXUS_MODEL", "").strip()
        if model:
            provider.model = model

    def get_provider(self) -> Any:
        """Returns the active provider, iterating the fallback chain.

        Tries each provider in ``fallback_chain`` (starting at the configured
        default) and returns the first one that constructs with a usable API key.
        This makes the system resilient: a dead/expired key on the default provider
        automatically falls through to the next configured provider instead of
        silently emitting empty output.

        ``default_provider: auto`` resolves through :meth:`_resolve_auto_default`
        (running keyless locals first, then keyed providers, health-aware).
        ``NEXUS_PROVIDER`` overrides the configured default on every entry path
        and ``NEXUS_MODEL`` is applied to the resolved provider.
        """
        if self._provider and self._consecutive_errors < 3 and not (
            self.offline_mode() and not self._is_local_provider(
                getattr(self._provider, "_provider_id", ""), self._provider
            )
        ):
            return self._provider
        try:
            cfg = self.loader.get("provider", {})
            chain = cfg.get("fallback_chain", []) if isinstance(cfg, dict) else []
            default = str(cfg.get("default_provider") or "").strip()
            env_provider = os.environ.get("NEXUS_PROVIDER", "").strip()
            if env_provider:
                default = env_provider
            candidates = []
            if default:
                candidates.append(default)
            for n in chain:
                if n not in candidates:
                    candidates.append(n)
            for name in candidates:
                if str(name).strip().lower() == "auto":
                    provider = self._resolve_auto_default()
                    if provider is not None:
                        self._provider = provider
                        self._consecutive_errors = 0
                        self._apply_env_model(provider)
                        return provider
                    logger.warning(
                        "ProviderFactory: default_provider=auto resolved to no working provider; falling back to fallback_chain"
                    )
                    continue
                provider = self.get_provider_by_name(self.group, name)
                is_local = self._is_local_provider(name, provider)
                if self.offline_mode() and not is_local:
                    logger.info("ProviderFactory: skipping remote provider %r in offline mode", name)
                    continue
                # Local servers commonly authenticate by loopback and therefore
                # legitimately have no API key.  Requiring a key here caused
                # LM Studio to be skipped before its connection was attempted.
                has_key = bool(provider is not None and (
                    getattr(provider, "api_key", None) or is_local
                ))
                logger.info("ProviderFactory: trying %r -> provider=%s has_key=%s", name, type(provider).__name__ if provider else None, has_key)
                if has_key:
                    self._provider = provider
                    self._consecutive_errors = 0
                    self._apply_env_model(provider)
                    return provider
        except Exception:
            logger.warning("providers/factory.py: get_provider fallback failed", exc_info=True)
        if self.offline_mode() and not self._is_local_provider_name(self.name):
            return None
        if str(self.name).strip().lower() == "auto":
            self._provider = self._resolve_auto_default()
            self._apply_env_model(self._provider)
            return self._provider
        self._provider = self.get_provider_by_name(self.group, self.name)
        self._apply_env_model(self._provider)
        return self._provider

    def reset(self) -> None:
        """Drop any cached provider so the next ``get_provider`` re-resolves
        (used after a key refresh or persistent provider failure)."""
        self._provider = None
        self._consecutive_errors = 0

    def mark_provider_error(self) -> None:
        """Record a failed provider call; after a few consecutive failures the
        cached provider is invalidated so a fallback/refresh can take effect."""
        self._consecutive_errors = getattr(self, "_consecutive_errors", 0) + 1
        if self._consecutive_errors >= 3:
            self._provider = None

    def get_provider_by_id(self, provider_id: str) -> Any:
        """Loads and returns a specific provider by its ID."""
        return self.get_provider_by_name("", provider_id)


if __name__ == "__main__":
    f = NexusProviderFactory()
    p = f.get_provider()
    model = getattr(p, "model", getattr(p, "default_model", "unknown"))
    logger.info("Active NEXUS Brain: [%s] using [%s]", type(p).__name__, model)
