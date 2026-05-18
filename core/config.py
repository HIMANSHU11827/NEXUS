import os
import yaml
import logging
from typing import Any, Dict, Optional
from utils.singleton import ThreadSafeSingleton

logger = logging.getLogger("NEXUS_CONFIG")

class NexusConfig(ThreadSafeSingleton):
    """
    Configuration manager.
    Loads and validates the NEXUS ecosystem settings.
    """
    _initialized = False

    def __init__(self, root_dir: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True
        self.root = root_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_path = os.path.join(self.root, "configs", "nexus_config.yaml")
        self.settings: Dict[str, Any] = {}
        self.load()

    def load(self):
        """Loads configuration from YAML."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Config missing at {self.config_path}. Using defaults.")
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.settings = yaml.safe_load(f) or {}
            logger.info("[+] Configuration Mesh Synchronized.")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

    def get(self, key_path: str, default: Any = None) -> Any:
        """Retrieves a value from nested keys (e.g., 'providers.openrouter.model')."""
        keys = key_path.split(".")
        val = self.settings
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            return default

    def set_override(self, key_path: str, value: Any):
        """Dynamic runtime override (volatile)."""
        keys = key_path.split(".")
        target = self.settings
        for k in keys[:-1]:
            target = target.setdefault(k, {})
        target[keys[-1]] = value

_config = None

def get_config() -> NexusConfig:
    global _config
    if _config is None:
        _config = NexusConfig()
    return _config
