"""SkillForge — creates procedural skill memories in skills/.

Redesigned (2026-08-05):
- Versioning goes through ONE path: ``VersionManager`` (``ensure``/``bump``).
- Output is validated before promotion; rejected results are not written.
- Public forge/refine are fault-isolated by ``forge_guard``.
"""
__version__ = "2.1.0"
import logging
import os
import re
import time
from typing import Any, Dict, Optional

from evolution.ledger.scripts.ledger import EvolutionLedger
from evolution.quality import (
    forge_guard,
    rejected_result,
    validate_forge_output,
)
from evolution.version.scripts.version import VersionManager
from models.providers.core.router import ModelRouter

logger = logging.getLogger(__name__)
SKILL_DIR = "skills"
VALID_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

class SkillForge:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.skills_dir = os.path.join(self.root, SKILL_DIR)
        os.makedirs(self.skills_dir, exist_ok=True)

    @forge_guard("skill")
    def forge(self, name: str, description: str = "") -> Dict[str, Any]:
        name = name.strip().lower().replace(" ", "-").replace("_", "-")
        if not name:
            return {"created": False, "error": "name is required"}
        skill_path = os.path.join(self.skills_dir, name)
        if os.path.exists(skill_path):
            return self.refine(name)
        vm = VersionManager(self.root)
        version = vm.ensure(name)
        skill_md = os.path.join(skill_path, "SKILL.md")
        payload = {"name": name, "version": version,
                   "description": description or "Auto-generated skill"}
        check = validate_forge_output("skill", payload, root=self.root, write_path=skill_md)
        if not check["valid"]:
            return self._rejected(name, check["reason"], action="forge")
        os.makedirs(skill_path, exist_ok=True)
        content = f"""---
name: {name}
description: {description or "Auto-generated skill"}
version: {version}
created_at: {time.time()}
---

# {name}

{description or "Auto-generated skill"}

## Instructions

1. Step one
2. Step two
"""
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[SKILL_FORGE] Created skill '{name}' v{version}")
        self._audit(name, "forge", old_version=None, new_version=version,
                    rollback_info={"kind": "skill", "path": skill_md, "dir": skill_path},
                    evidence=f"created skill '{name}'")
        return {"created": True, "name": name, "version": version, "path": skill_path,
                "status": "ok", "promoted": True}

    @forge_guard("skill")
    def refine(self, name: str, description: str = "") -> Dict[str, Any]:
        skill_path = os.path.join(self.skills_dir, name)
        if not os.path.exists(skill_path):
            return {"created": False, "error": f"skill '{name}' not found"}
        skill_md = os.path.join(skill_path, "SKILL.md")
        if not os.path.exists(skill_md):
            return {"created": False, "error": f"SKILL.md not found for '{name}'"}
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"version:\s*([\d.]+)", content)
        cur = m.group(1) if m else "1.0.0"
        vm = VersionManager(self.root)
        new_ver = vm.bump(name, "minor", self.root, current=cur) or cur
        old_version = cur
        new_content = re.sub(r"version:\s*[\d.]+", f"version: {new_ver}", content, count=1)
        if description:
            new_content = re.sub(r"(?m)^description:\s*.*$", f"description: {description}", new_content, count=1)
        dm = re.search(r"(?m)^description:\s*(.*)$", new_content)
        payload = {"name": name, "version": new_ver,
                   "description": (description or (dm.group(1).strip() if dm else "Auto-generated skill"))}
        check = validate_forge_output("skill", payload, root=self.root, write_path=skill_md)
        if not check["valid"]:
            return self._rejected(name, check["reason"], action="refine")
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"[SKILL_FORGE] Refined skill '{name}' to v{new_ver}")
        self._audit(name, "refine", old_version=old_version, new_version=new_ver,
                    rollback_info={"kind": "skill", "path": skill_md, "dir": skill_path},
                    evidence=f"refined skill '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True,
                "status": "ok", "promoted": True}

    # ── shared helpers ───────────────────────────────────────────────────

    def _rejected(self, name: str, reason: str, action: str = "forge") -> Dict[str, Any]:
        self._audit(name, action, old_version=None, new_version=None,
                    promoted=False, evidence=reason)
        return rejected_result("skill", name, reason, action=action)

    def _audit(self, name: str, action: str, *, old_version, new_version,
               promoted: bool = True, evidence: str = "",
               rollback_info: Optional[Dict] = None) -> None:
        try:
            EvolutionLedger(self.root).log_forge(
                "skill", name, action,
                old_version=old_version, new_version=new_version,
                evidence=evidence, tests_passed=None,
                promoted=promoted, rollback_info=rollback_info,
            )
        except Exception:
            logger.warning("evolution/skill_forge/scripts/forge.py: _audit suppressed error", exc_info=True)