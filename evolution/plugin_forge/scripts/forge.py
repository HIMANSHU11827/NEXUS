"""PluginForge — creates and refines NEXUS plugins.

Redesigned (2026-08-05):
- Versioning goes through ONE path: ``VersionManager`` (``ensure``/``bump``).
- Output is validated before promotion; rejected results are not written.
- Public forge/refine are fault-isolated by ``forge_guard``.
"""
__version__ = "2.1.0"
import json
import logging
import os
import time
from typing import Any, Dict, Optional

from evolution.ledger.scripts.ledger import EvolutionLedger
from evolution.quality import (
    forge_guard,
    rejected_result,
    validate_forge_output,
)
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

    @forge_guard("plugin")
    def forge(self, name: str, description: str = "") -> Dict[str, Any]:
        name = name.strip().lower().replace(" ", "_").replace("-", "_")
        if not name:
            return {"created": False, "error": "name is required"}
        plugin_dir = os.path.join(self.plugins_dir, name)
        if os.path.exists(plugin_dir):
            return self.refine(name, {"major": False})
        vm = VersionManager(self.root)
        version = vm.ensure(name)
        desc = description or "Auto-generated plugin"
        meta = {"name": name, "version": version, "description": desc, "created_at": time.time()}
        meta_path = os.path.join(plugin_dir, f"{name}.json")
        check = validate_forge_output("plugin", meta, root=self.root, write_path=meta_path)
        if not check["valid"]:
            return self._rejected(name, check["reason"], action="forge")
        os.makedirs(plugin_dir, exist_ok=True)
        os.makedirs(os.path.join(plugin_dir, SCRIPTS_DIR), exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        init_path = os.path.join(plugin_dir, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w", encoding="utf-8") as f:
                f.write(f'"""Plugin: {name}"""\n\ndef register(ctx):\n    """Register plugin with context."""\n    pass\n')
        readme = os.path.join(plugin_dir, "read.md")
        if not os.path.exists(readme):
            with open(readme, "w", encoding="utf-8") as f:
                f.write(f"# {name}\n\n{desc}\n")
        logger.info(f"[PLUGIN_FORGE] Created plugin '{name}' v{version}")
        self._audit(name, "forge", old_version=None, new_version=version,
                    rollback_info={"kind": "plugin", "path": meta_path, "dir": plugin_dir},
                    evidence=f"created plugin '{name}'")
        return {"created": True, "name": name, "version": version, "path": plugin_dir,
                "status": "ok", "promoted": True}

    @forge_guard("plugin")
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
        cur = str(meta.get("version") or "1.0.0")
        vm = VersionManager(self.root)
        part = "major" if config.get("major", False) else "minor"
        new_ver = vm.bump(name, part, self.root, current=cur) or cur
        old_version = cur
        meta["version"] = new_ver
        if config.get("description"):
            meta["description"] = config["description"]
        check = validate_forge_output("plugin", meta, root=self.root, write_path=meta_path)
        if not check["valid"]:
            return self._rejected(name, check["reason"], action="refine")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        logger.info(f"[PLUGIN_FORGE] Refined plugin '{name}' to v{new_ver}")
        self._audit(name, "refine", old_version=old_version, new_version=new_ver,
                    rollback_info={"kind": "plugin", "path": meta_path, "dir": plugin_dir},
                    evidence=f"refined plugin '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True,
                "status": "ok", "promoted": True}

    # ── shared helpers ───────────────────────────────────────────────────

    def _rejected(self, name: str, reason: str, action: str = "forge") -> Dict[str, Any]:
        self._audit(name, action, old_version=None, new_version=None,
                    promoted=False, evidence=reason)
        return rejected_result("plugin", name, reason, action=action)

    def _audit(self, name: str, action: str, *, old_version, new_version,
               promoted: bool = True, evidence: str = "",
               rollback_info: Optional[Dict] = None) -> None:
        try:
            EvolutionLedger(self.root).log_forge(
                "plugin", name, action,
                old_version=old_version, new_version=new_version,
                evidence=evidence, tests_passed=None,
                promoted=promoted, rollback_info=rollback_info,
            )
        except Exception:
            logger.warning("evolution/plugin_forge/scripts/forge.py: _audit suppressed error", exc_info=True)
