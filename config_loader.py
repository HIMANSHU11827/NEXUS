"""Central configuration loader for NEXUS AI.

Reads config files from config/ directory and caches them.
Supports YAML and JSON formats.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_ROOT = Path(__file__).resolve().parent
_CONFIG_DIR = _ROOT / "config"


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
        except Exception:
            pass

    def _load_json(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                key = path.stem
                self._cache[key] = data
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def get_system(self, key: str, default: Any = None) -> Any:
        system_config = self.get("system")
        if isinstance(system_config, dict):
            return system_config.get(key, default)
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

    @staticmethod
    def get_memory_dir() -> Path:
        return _ROOT / "memory"

    @staticmethod
    def get_knowledge_dir() -> Path:
        return _ROOT / "knowledge"
