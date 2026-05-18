import os
import importlib
from typing import Any, List, Dict, Optional
from utils.singleton import ThreadSafeSingleton


# Linter-proof imports
def get_loader() -> Any:
    mod = importlib.import_module("core.config_loader")
    return getattr(mod, "NexusConfigLoader")()


class NexusProviderFactory(ThreadSafeSingleton):
    """
    NEXUS UNIVERSAL PROVIDER FACTORY 3.1
    True dynamic model mesh implementation.
    """

    _provider = None

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        # ⚡ Load the Master Config
        self.loader = get_loader()

        # Determine Group (local vs cloud)
        self.group = self.loader.get_system("default_provider", "cloud")
        # Determine Name (openrouter, gemini, ollama, etc.)
        self.name = self.loader.get_system("provider_name", "openrouter")

    def get_provider_by_name(self, group: str, name: str) -> Any:
        """Loads and returns a specific provider instance."""
        try:
            # ⚡ 3.2: Instance ID Resolution
            inst_config = self.loader.get_provider_config(name)
            parent = inst_config.get("parent_provider")
            target_name = parent if parent else name

            # ⚡ 3.1: Explicit Mapping for God-Architect stability
            mappings = {
                "openrouter": ("core.providers.openrouter", "OpenRouterProvider"),
                "gemini": ("core.providers.google_gemini", "GoogleGeminiProvider"),
                "google_gemini": ("core.providers.google_gemini", "GoogleGeminiProvider"),
                "anthropic": ("core.providers.anthropic", "AnthropicProvider"),
                "openai": ("core.providers.openai", "OpenAIProvider"),
                "groq": ("core.providers.groq", "GroqProvider"),
                "qwen": ("core.providers.qwen", "QwenProvider"),
                "deepseek": ("core.providers.deepseek", "DeepSeekProvider"),
                "xai": ("core.providers.xai", "XAIProvider"),
                "grok": ("core.providers.xai", "XAIProvider"),
                "cohere": ("core.providers.cohere", "CohereProvider"),
                "mistral": ("core.providers.mistral", "MistralProvider"),
                "perplexity": ("core.providers.perplexity", "PerplexityProvider"),
                "together": ("core.providers.together", "TogetherProvider"),
                "lm_studio": ("core.providers.lm_studio", "LMStudioProvider"),
                "ollama": ("core.providers.ollama", "OllamaProvider"),
                "huggingface": ("core.providers.huggingface", "HuggingFaceProvider"),
                "sambanova": ("core.providers.sambanova", "SambaNovaProvider"),
                "fireworks": ("core.providers.fireworks", "FireworksProvider"),
                "azure_openai": ("core.providers.azure_openai", "AzureOpenAIProvider"),
                "replicate": ("core.providers.replicate", "ReplicateProvider"),
                "llama_cpp": ("core.providers.llama_cpp", "LlamaCPPProvider"),
                "vlm": ("core.providers.vlm", "VLMProvider"),
                "universal": ("core.providers.universal", "UniversalProvider"),
            }

            provider = None
            if target_name in mappings:
                mod_path, cls_name = mappings[target_name]
                mod = importlib.import_module(mod_path)
                provider = getattr(mod, cls_name)()
            else:
                # Fallback to smart-guessing if not in mapping
                mod_name = f"providers.{target_name.replace('-', '_')}"
                cls_name = (
                    "".join([p.capitalize() for p in target_name.replace("-", "_").split("_")])
                    + "Provider"
                )
                mod = importlib.import_module(mod_name)
                provider = getattr(mod, cls_name)()

            # ⚡ Apply Instance Overrides (API Key, Model, Endpoint)
            if parent and provider:
                provider.api_key = inst_config.get("api_key") or provider.api_key
                provider.model = inst_config.get("model") or provider.model
                provider.endpoint = inst_config.get("endpoint") or provider.endpoint
                
                # Special handling for headers if api_key changed
                if hasattr(provider, "headers") and inst_config.get("api_key"):
                    provider.headers["Authorization"] = f"Bearer {provider.api_key}"

            return provider

        except Exception as e:
            print(f"[FACTORY_ERROR]: Falling back from {name} due to: {e}")
            from core.providers.openrouter import OpenRouterProvider
            return OpenRouterProvider()

    def get_provider(self) -> Any:
        """Returns the active provider based on MASTER CONFIG."""
        if not self._provider:
            self._provider = self.get_provider_by_name(self.group, self.name)
        return self._provider

    def get_provider_by_id(self, provider_id: str) -> Any:
        """Loads and returns a specific provider by its ID."""
        return self.get_provider_by_name("", provider_id)


if __name__ == "__main__":
    f = NexusProviderFactory()
    p = f.get_provider()
    print(f"Active NEXUS Brain: [{type(p).__name__}] using [{p.default_model}]")
