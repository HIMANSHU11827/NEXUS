import os
import json
import logging
import requests
import time
from typing import Dict, Any, Optional, List, Iterator
from abc import ABC, abstractmethod

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
        
        # ⚡ Load from Config
        try:
            from core.config_loader import NexusConfigLoader
            loader = NexusConfigLoader()
            config = loader.get_provider_config(provider_name)
            
            self.api_key = config.get("api_key") or os.getenv(f"{provider_name.upper()}_API_KEY", "")
            self.model = config.get("model") or ""
            self.endpoint = config.get("endpoint") or self.endpoint
            
            # Sanitize key
            if self.api_key and "YOUR_" in self.api_key:
                self.api_key = os.getenv(f"{provider_name.upper()}_API_KEY", "")
                
        except Exception as e:
            logger.warning(f"[{provider_name.upper()}_INIT]: Failed to load config: {e}")

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
