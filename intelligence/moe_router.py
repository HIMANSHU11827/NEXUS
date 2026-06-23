"""NexusMoERouter — minimal stub for LLM routing."""

import logging
import json
import os
from typing import Any, Dict, List, Optional
from providers.factory import NexusProviderFactory

logger = logging.getLogger("NEXUS_LOCAL_BRAIN")


class NexusMoERouter:
    """Minimal MoE router that delegates to the provider factory."""

    def __init__(self):
        self.factory = NexusProviderFactory()
        self.base_router = self
        self.mode = "auto"

    def stream_generate(self, messages: List[Dict[str, str]], **kwargs):
        """Stream response from the configured provider."""
        provider_name = os.environ.get("NEXUS_PROVIDER", "openai")
        try:
            provider = self.factory.get_provider_by_name("cloud", provider_name)
            if provider and hasattr(provider, "stream_chat"):
                for chunk in provider.stream_chat(messages):
                    yield chunk
            else:
                yield 'I am NEXUS AI, a local-first autonomous engineering agent. I can help with code, system tasks, research, and automation. What would you like to do?\n\nTASK_COMPLETE'
        except Exception as e:
            logger.error(f"Model call failed: {e}")
            yield f"I'm running in minimal mode. The provider '{provider_name}' could not be loaded ({e}). Please configure a provider key in your environment."

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Non-streaming chat."""
        parts = list(self.stream_generate(messages, **kwargs))
        return "".join(parts)
