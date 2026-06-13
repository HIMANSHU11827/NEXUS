import os
import importlib
from typing import Any, List, Dict, Optional
from utils.singleton import ThreadSafeSingleton


# Linter-proof imports
def get_loader() -> Any:
    mod = importlib.import_module("config_loader")
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
            provider_id = str(name or "").strip()
            inst_config = self.loader.get_provider_config(provider_id)
            parent = inst_config.get("parent_provider")
            target_name = str(parent if parent else provider_id).lower()

            # ⚡ 3.1: Explicit Mapping for God-Architect stability
            mappings = {
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
                "vlm": ("providers.vlm", "VLMProvider"),
                "universal": ("providers.universal", "UniversalProvider"),
                "commandcode": ("providers.commandcode", "CommandCodeProvider"),
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
            from providers.openrouter import OpenRouterProvider
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
