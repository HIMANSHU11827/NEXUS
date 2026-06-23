"""PluginForge — creates and refines NEXUS plugins."""
__version__ = "1.0.0"
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from evolution.version.scripts.version import VersionManager
from providers.router import ModelRouter
logger = logging.getLogger(__name__)
_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

PLUGINS_DIR = "plugins"
SCRIPTS_DIR = "scripts"

class PluginForge:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.plugins_dir = os.path.join(self.root, PLUGINS_DIR)
        os.makedirs(self.plugins_dir, exist_ok=True)

    def forge(self, name: str, description: str = "") -> Dict[str, Any]:
        name = name.strip().lower().replace(" ", "_").replace("-", "_")
        if not name:
            return {"created": False, "error": "name is required"}
        plugin_dir = os.path.join(self.plugins_dir, name)
        if os.path.exists(plugin_dir):
            return self.refine(name, {"major": False})
        os.makedirs(plugin_dir, exist_ok=True)
        os.makedirs(os.path.join(plugin_dir, SCRIPTS_DIR), exist_ok=True)
        meta = {"name": name, "version": "1.0.0", "description": description or "Auto-generated plugin", "created_at": time.time()}
        with open(os.path.join(plugin_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        init_path = os.path.join(plugin_dir, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w", encoding="utf-8") as f:
                f.write(f'"""Plugin: {name}"""\n\ndef register(ctx):\n    """Register plugin with context."""\n    pass\n')
        readme = os.path.join(plugin_dir, "read.md")
        if not os.path.exists(readme):
            with open(readme, "w", encoding="utf-8") as f:
                f.write(f"# {name}\n\n{description or 'Auto-generated plugin'}\n")
        logger.info(f"[PLUGIN_FORGE] Created plugin '{name}' v1.0.0")
        return {"created": True, "name": name, "version": "1.0.0", "path": plugin_dir}

    def refine(self, name: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        config = config or {}
        plugin_dir = os.path.join(self.plugins_dir, name)
        if not os.path.exists(plugin_dir):
            return {"created": False, "error": f"plugin '{name}' not found"}
        meta_path = os.path.join(plugin_dir, f"{name}.json")
        if not os.path.exists(meta_path):
            return {"created": False, "error": f"metadata not found for '{name}'"}
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        vm = VersionManager(self.root)
        new_ver = vm.bump(name, "major" if config.get("major", False) else "minor", self.root)
        if not new_ver:
            major = config.get("major", False)
            cur = meta.get("version", "1.0.0")
            parts = cur.split(".")
            new_ver = f"{int(parts[0]) + 1}.0.0" if major else f"{parts[0]}.{int(parts[1]) + 1}.0"
        meta["version"] = new_ver
        if config.get("description"):
            meta["description"] = config["description"]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[PLUGIN_FORGE] Refined plugin '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True}
