import asyncio
import importlib
import logging
import os
from typing import Any, Optional

from utils.singleton import ThreadSafeSingleton
from providers.reliability import redact_secrets

logger = logging.getLogger(__name__)


def get_loader() -> Any:
    mod = importlib.import_module("config.config_loader")
    return getattr(mod, "NexusConfigLoader")()


def _configured_api_key(value: Any) -> Optional[str]:
    key = str(value or "").strip()
    if not key or "YOUR_" in key:
        return None
    if key.startswith("${") and key.endswith("}"):
        return os.environ.get(key[2:-1], "").strip() or None
    return key


def _resolve_api_key(provider_id: str, profile_name: Optional[str] = None) -> Optional[str]:
    try:
        from providers.profiles import resolve_api_key
        key = resolve_api_key(provider_id, profile_name)
        if key:
            return key
    except Exception:
        logger.warning("providers/factory.py:29 _resolve_api_key: suppressed error", exc_info=True)
        pass
    try:
        from providers.oauth.providers.autoregister import register_all_oauth_providers
        from providers.oauth.registry import get_oauth_provider
        from providers.oauth.storage import load_oauth_token_store
        register_all_oauth_providers()
        store = load_oauth_token_store()
        credentials = store.get(provider_id)
        if credentials is not None:
            oauth_provider = get_oauth_provider(provider_id)
            import time
            if time.time() * 1000 >= credentials.expires and oauth_provider is not None:
                try:
                    credentials = asyncio.run(oauth_provider.refresh_token(credentials))
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
        self._initialized = True
        self.loader = get_loader()
        provider_config = self.loader.get("provider", {})
        provider_name = ""
        if isinstance(provider_config, dict):
            provider_name = str(provider_config.get("default_provider") or "").strip()
        self.group = self.loader.get_system("provider_group", "cloud")
        self.name = provider_name or self.loader.get_system("provider_name", "openrouter")
        self._consecutive_errors = 0

    def _load_provider_instance(self, target_name: str) -> Any:
        if target_name in MAPPINGS:
            mod_path, cls_name = MAPPINGS[target_name]
            mod = importlib.import_module(mod_path)
            return getattr(mod, cls_name)()
        mod_name = f"providers.{target_name.replace('-', '_')}"
        cls_name = "".join(p.capitalize() for p in target_name.replace("-", "_").split("_")) + "Provider"
        mod = importlib.import_module(mod_name)
        return getattr(mod, cls_name)()

    def get_provider_by_name(self, group: str, name: str, profile: Optional[str] = None) -> Any:
        try:
            provider_id = str(name or "").strip()
            inst_config = self.loader.get_provider_config(provider_id)
            # NexusConfigLoader.get_provider_config() *pops* parent_provider while
            # merging, so it is never present in inst_config. Read the raw
            # provider block to recover the parent implementation name.
            parent = inst_config.get("parent_provider") or self._raw_parent(provider_id)
            target_name = str(parent if parent else provider_id).lower()

            provider = self._load_provider_instance(target_name)
            provider.model = inst_config.get("model") or provider.model
            provider.endpoint = inst_config.get("endpoint") or provider.endpoint

            config_key = _configured_api_key(inst_config.get("api_key"))
            env_key = (
                os.environ.get(f"{provider_id.upper()}_API_KEY", "").strip()
                or os.environ.get(f"{target_name.upper()}_API_KEY", "").strip()
            )
            key = config_key or _resolve_api_key(provider_id, profile) or env_key
            if key:
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
                    provider.api_key = parent_key
                    if hasattr(provider, "headers"):
                        provider.headers["Authorization"] = f"Bearer {provider.api_key}"

            provider._provider_id = provider_id
            provider._profile_name = profile
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
            from providers.profiles import load_profile_store
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

    def get_provider(self) -> Any:
        """Returns the active provider, iterating the fallback chain.

        Tries each provider in ``fallback_chain`` (starting at the configured
        default) and returns the first one that constructs with a usable API key.
        This makes the system resilient: a dead/expired key on the default provider
        automatically falls through to the next configured provider instead of
        silently emitting empty output.
        """
        if self._provider and self._consecutive_errors < 3:
            return self._provider
        try:
            cfg = self.loader.get("provider", {})
            chain = cfg.get("fallback_chain", []) if isinstance(cfg, dict) else []
            default = str(cfg.get("default_provider") or "").strip()
            candidates = []
            if default:
                candidates.append(default)
            for n in chain:
                if n not in candidates:
                    candidates.append(n)
            for name in candidates:
                provider = self.get_provider_by_name(self.group, name)
                if provider is not None and getattr(provider, "api_key", None):
                    self._provider = provider
                    self._consecutive_errors = 0
                    return provider
        except Exception:
            logger.warning("providers/factory.py: get_provider fallback failed", exc_info=True)
        self._provider = self.get_provider_by_name(self.group, self.name)
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
