"""SkillForge — creates procedural skill memories in skills/."""
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

    def forge(self, name: str, description: str = "") -> Dict[str, Any]:
        name = name.strip().lower().replace(" ", "-").replace("_", "-")
        if not name:
            return {"created": False, "error": "name is required"}
        skill_path = os.path.join(self.skills_dir, name)
        if os.path.exists(skill_path):
            return self.refine(name)
        os.makedirs(skill_path, exist_ok=True)
        skill_md = os.path.join(skill_path, "SKILL.md")
        content = f"""---
name: {name}
description: {description or "Auto-generated skill"}
version: 1.0.0
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
        logger.info(f"[SKILL_FORGE] Created skill '{name}' v1.0.0")
        return {"created": True, "name": name, "version": "1.0.0", "path": skill_path}

    def refine(self, name: str, description: str = "") -> Dict[str, Any]:
        skill_path = os.path.join(self.skills_dir, name)
        if not os.path.exists(skill_path):
            return {"created": False, "error": f"skill '{name}' not found"}
        skill_md = os.path.join(skill_path, "SKILL.md")
        if not os.path.exists(skill_md):
            return {"created": False, "error": f"SKILL.md not found for '{name}'"}
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()
        vm = VersionManager(self.root)
        new_ver = vm.bump(name, "minor", self.root)
        if not new_ver:
            m = re.search(r"version:\s*([\d.]+)", content)
            if m:
                parts = m.group(1).split(".")
                new_ver = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}" if len(parts) >= 3 else f"{parts[0]}.{parts[1]}.1"
            else:
                new_ver = "1.0.1"
        content = re.sub(r"version:\s*[\d.]+", f"version: {new_ver}", content)
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[SKILL_FORGE] Refined skill '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True}
