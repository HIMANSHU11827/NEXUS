"""Central configuration loader for NEXUS AI.

Reads config files from config/ directory and caches them.
Supports YAML and JSON formats.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
_CONFIG_DIR = _ROOT  # YAML/JSON config files live alongside config_loader.py


class NexusConfigLoader:
    """Loads and caches configuration from config/ directory."""

    _instance = None
    _cache: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._load_all()

    def _load_all(self):
        if not _CONFIG_DIR.exists():
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            return
        for file in sorted(_CONFIG_DIR.iterdir()):
            if file.suffix in (".yml", ".yaml"):
                self._load_yaml(file)
            elif file.suffix == ".json":
                self._load_json(file)

    def _load_yaml(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                key = path.stem
                self._cache[key] = data
        except Exception as e:
            logger.warning("Failed to load YAML %s: %s", path, e)

    def _load_json(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                key = path.stem
                self._cache[key] = data
        except Exception as e:
            logger.warning("Failed to load JSON %s: %s", path, e)

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def get_system(self, key: str, default: Any = None) -> Any:
        settings_config = self.get("settings")
        if isinstance(settings_config, dict) and key in settings_config:
            return settings_config.get(key, default)

        system_config = self.get("system")
        if isinstance(system_config, dict):
            if key in system_config:
                return system_config.get(key, default)
            nested_system = system_config.get("system")
            if isinstance(nested_system, dict) and key in nested_system:
                return nested_system.get(key, default)

        provider_config = self.get("provider")
        if isinstance(provider_config, dict) and key == "default_provider":
            return provider_config.get("default_provider", default)
        return default

    @property
    def data(self) -> Dict[str, Any]:
        return dict(self._cache)

    def reload(self):
        self._cache.clear()
        self._load_all()

    @staticmethod
    def get_config_dir() -> Path:
        return _CONFIG_DIR

    @staticmethod
    def get_root() -> Path:
        return _ROOT

    def get_provider_config(self, name: str) -> dict:
        provider_cfg = self._cache.get("provider", {})
        providers = provider_cfg.get("providers", {}) if isinstance(provider_cfg, dict) else {}
        raw = providers.get(name, {})
        if not raw:
            return {}
        result = dict(raw)
        parent = result.pop("parent_provider", None)
        if parent:
            parent_config = self.get_provider_config(parent)
            parent_config.update(result)
            result = parent_config
        return result

    @staticmethod
    def get_memory_dir() -> str:
        return os.path.join(_ROOT.parent, "memory")

    @staticmethod
    def get_knowledge_dir() -> str:
        return os.path.join(_ROOT.parent, "knowledge")
