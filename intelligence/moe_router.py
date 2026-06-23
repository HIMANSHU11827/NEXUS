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
            if provider:
                if hasattr(provider, "stream_chat"):
                    for chunk in provider.stream_chat(messages):
                        yield chunk
                    return
                # Try stream_generate (the standard NEXUS provider method)
                for chunk in provider.stream_generate(messages=messages):
                    yield chunk
                return
        except Exception as e:
            logger.error(f"Model call failed: {e}")
            yield f"[Provider '{provider_name}' unavailable: {e}]\n\nTASK_COMPLETE"
            return
        yield "I am NEXUS AI, a local-first autonomous engineering agent. I can help with code, system tasks, research, and automation. What would you like to do?\n\nTASK_COMPLETE"

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Non-streaming chat."""
        parts = list(self.stream_generate(messages, **kwargs))
        return "".join(parts)
