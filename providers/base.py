import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional

import requests

logger = logging.getLogger("NEXUS_PROVIDER")

class NexusBaseProvider(ABC):
    """
    NEXUS BASE PROVIDER SCHEMATIC 1.0
    Universal interface for all cloud and local model engines.
    """
    
    def __init__(self, provider_name: str, endpoint: str):
        self.provider_name = provider_name
        self.endpoint = endpoint
        self.model = ""
        self.api_key = ""
        self.headers = {}
        self.session = requests.Session()
        self.thinking = False
        
        # ⚡ Load from Config
        try:
            from config.config_loader import NexusConfigLoader
            loader = NexusConfigLoader()
            config = loader.get_provider_config(provider_name)
            
            # provider.yml stores provider metadata and may reference secrets as ${VAR}.
            # Raw secrets should stay in environment variables or local encrypted/profile storage.
            raw_key = config.get("api_key", "")
            if isinstance(raw_key, str) and raw_key.startswith("${") and raw_key.endswith("}"):
                env_name = raw_key[2:-1]
                raw_key = os.getenv(env_name, "")
            if not raw_key:
                raw_key = os.getenv(f"{provider_name.upper()}_API_KEY", "")
            self.api_key = raw_key
            self.model = config.get("model") or ""
            self.endpoint = config.get("endpoint") or self.endpoint
            
            # Sanitize key
            if self.api_key and "YOUR_" in self.api_key:
                self.api_key = ""
                
        except Exception as e:
            logger.warning(f"[{provider_name.upper()}_INIT]: Failed to load config: {e}")

    def configure_thinking(self, enabled: bool):
        self.thinking = enabled

    def reload_credentials(self, api_key: Optional[str] = None) -> bool:
        """Re-resolve the provider credential and rebuild auth headers.

        Reads the freshest key from the same env var / provider.yml reference
        used at construction, then swaps it into every auth header. Callers
        that already hold a fresher key (profile/OAuth resolution) can pass it
        explicitly to skip the config lookup. Never touches model/endpoint and
        never starts timers/threads — this is a pure, cheap re-read.
        """
        old_key = str(self.api_key or "")
        new_key = api_key
        if new_key is None:
            try:
                from config.config_loader import NexusConfigLoader
                loader = NexusConfigLoader()
                config = loader.get_provider_config(self.provider_name)
                raw_key = str(config.get("api_key", "") or "")
                if raw_key.startswith("${") and raw_key.endswith("}"):
                    raw_key = os.getenv(raw_key[2:-1], "")
                if not raw_key:
                    raw_key = os.getenv(f"{self.provider_name.upper()}_API_KEY", "")
                new_key = raw_key
            except Exception as e:
                logger.warning(f"[{self.provider_name.upper()}_RELOAD]: failed to re-read config: {e}")
                new_key = old_key
        new_key = str(new_key or "").strip()
        if "YOUR_" in new_key:
            new_key = ""
        if new_key == old_key:
            return False
        self.api_key = new_key
        self._refresh_auth_headers(old_key)
        return True

    def _refresh_auth_headers(self, previous_key: str) -> None:
        """Swap the previous credential for the new one in every auth header.

        Handles both raw headers (``x-api-key``, ``x-goog-api-key``) and the
        common ``Authorization: Bearer ...`` form without knowing which header
        a concrete provider uses.
        """
        if not isinstance(self.headers, dict):
            return
        for name, value in list(self.headers.items()):
            if not isinstance(value, str):
                continue
            if value == f"Bearer {previous_key}":
                self.headers[name] = f"Bearer {self.api_key}"
            elif value == previous_key:
                self.headers[name] = str(self.api_key or "")


    @abstractmethod
    def generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        pass

    @abstractmethod
    def stream_generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        pass

    def _prepare_messages(self, prompt: str, system_prompt: str, messages: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        if messages:
            return messages
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

    def validate_api_key(self) -> bool:
        """Cheap credential presence check; network health is handled by router."""
        if self.provider_name in {"ollama", "lm_studio", "llama_cpp"}:
            return True
        key = (self.api_key or "").strip()
        return bool(key and "YOUR_" not in key and not key.startswith("sk-test"))

    def health_check(self, timeout: float = 8.0) -> Dict[str, Any]:
        """Non-invasive provider health metadata."""
        start = time.time()
        valid_key = self.validate_api_key()
        return {
            "provider": self.provider_name,
            "model": self.model,
            "endpoint": self.endpoint,
            "has_valid_key": valid_key,
            "latency_ms": round((time.time() - start) * 1000, 2),
            "healthy": valid_key,
        }
