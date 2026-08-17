"""ToolForge — creates new NEXUS tools from LLM-generated specifications.

Each tool gets its own folder under tools/<name>/ with:
  - <name>.json     — schema (name, version, description, defaults, permissions)
  - scripts/<name>.py — Python implementation (BaseTool subclass)
  - read.md         — documentation

Redesigned (2026-08-05):
- Versioning goes through ONE path: ``VersionManager`` (``ensure``/``bump``).
- Output is validated before promotion; rejected results are not written.
- Provider-error / empty descriptions are rejected (V5 honesty).
- Public forge/refine are fault-isolated by ``forge_guard``.
"""
__version__ = "2.1.0"

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional

from evolution.ledger.scripts.ledger import EvolutionLedger
from evolution.quality import (
    forge_guard,
    looks_like_provider_error,
    rejected_result,
    validate_forge_output,
)
from evolution.version.scripts.version import VersionManager
from models.providers.core.router import ModelRouter

logger = logging.getLogger(__name__)

_ROUTER: Optional[ModelRouter] = None

def _get_router() -> ModelRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ModelRouter()
    return _ROUTER

VALID_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$')
TOOLS_DIR = "tools"
SCRIPTS_DIR = "scripts"


class ToolForge:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.tools_dir = os.path.join(self.root, TOOLS_DIR)
        os.makedirs(self.tools_dir, exist_ok=True)

    @forge_guard("tool")
    def forge(self, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        name_raw = (tool_def.get("name") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if not name_raw:
            return {"created": False, "error": "name is required"}
        if not VALID_NAME_RE.match(name_raw):
            return {"created": False, "error": f"invalid tool name: {name_raw}"}

        description = str(tool_def.get("description") or "")
        if not description.strip() or looks_like_provider_error(description):
            return self._rejected(name_raw, "evidence rejected: empty or provider/error-shaped description is never crystallized", action="forge")

        tool_dir = os.path.join(self.tools_dir, name_raw)
        if os.path.exists(tool_dir):
            return self.refine(name_raw, tool_def)

        vm = VersionManager(self.root)
        version = vm.ensure(name_raw)

        schema = {
            "name": name_raw,
            "version": version,
            "description": description,
            "defaults": tool_def.get("defaults", {}),
            "permissions": tool_def.get("permissions", {"auto_approve": False}),
            "created_at": time.time(),
        }
        schema_path = os.path.join(tool_dir, f"{name_raw}.json")
        check = validate_forge_output("tool", schema, root=self.root, write_path=schema_path)
        if not check["valid"]:
            return self._rejected(name_raw, check["reason"], action="forge")

        os.makedirs(tool_dir, exist_ok=True)
        os.makedirs(os.path.join(tool_dir, SCRIPTS_DIR), exist_ok=True)
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
        self._generate_script(name_raw, description, tool_dir)
        self._generate_readme(name_raw, description, tool_dir)

        logger.info(f"[TOOL_FORGE] Created tool '{name_raw}' v{schema['version']}")
        self._audit(name_raw, "forge", old_version=None, new_version=version,
                    rollback_info={"kind": "tool", "path": schema_path, "dir": tool_dir},
                    evidence=f"created tool '{name_raw}'")
        return {"created": True, "name": name_raw, "version": schema["version"], "path": tool_dir,
                "status": "ok", "promoted": True}

    @forge_guard("tool")
    def refine(self, name: str, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        tool_dir = os.path.join(self.tools_dir, name)
        if not os.path.exists(tool_dir):
            return {"created": False, "error": f"tool '{name}' not found"}

        schema_path = os.path.join(tool_dir, f"{name}.json")
        if not os.path.exists(schema_path):
            return {"created": False, "error": f"schema not found for '{name}'"}

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        description = str(tool_def.get("description") or schema.get("description") or "")
        if not description.strip() or looks_like_provider_error(description):
            return self._rejected(name, "evidence rejected: empty or provider/error-shaped description is never crystallized", action="refine")

        cur = str(schema.get("version") or "1.0.0")
        vm = VersionManager(self.root)
        part = "major" if tool_def.get("major", False) else "minor"
        new_ver = vm.bump(name, part, self.root, current=cur) or cur
        old_version = cur

        schema["version"] = new_ver
        if "description" in tool_def:
            schema["description"] = description
        if "permissions" in tool_def:
            schema["permissions"] = tool_def["permissions"]

        check = validate_forge_output("tool", schema, root=self.root, write_path=schema_path)
        if not check["valid"]:
            return self._rejected(name, check["reason"], action="refine")

        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)

        logger.info(f"[TOOL_FORGE] Refined tool '{name}' to v{new_ver}")
        self._audit(name, "refine", old_version=old_version, new_version=new_ver,
                    rollback_info={"kind": "tool", "path": schema_path, "dir": tool_dir},
                    evidence=f"refined tool '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True,
                "status": "ok", "promoted": True}

    # ── shared helpers ───────────────────────────────────────────────────

    def _rejected(self, name: str, reason: str, action: str = "forge") -> Dict[str, Any]:
        self._audit(name, action, old_version=None, new_version=None,
                    promoted=False, evidence=reason)
        return rejected_result("tool", name, reason, action=action)

    def _audit(self, name: str, action: str, *, old_version, new_version,
               promoted: bool = True, evidence: str = "",
               rollback_info: Optional[Dict] = None) -> None:
        try:
            EvolutionLedger(self.root).log_forge(
                "tool", name, action,
                old_version=old_version, new_version=new_version,
                evidence=evidence, tests_passed=None,
                promoted=promoted, rollback_info=rollback_info,
            )
        except Exception:
            logger.warning("evolution/tool_forge/scripts/engine.py: _audit suppressed error", exc_info=True)

    def _get_schema(self, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": tool_def.get("name", "unnamed"),
            "version": tool_def.get("version", "1.0.0"),
            "description": tool_def.get("description", ""),
            "defaults": tool_def.get("defaults", {}),
            "permissions": tool_def.get("permissions", {"auto_approve": False}),
            "created_at": time.time(),
        }

    def _generate_script(self, name: str, description: str, tool_dir: str):
        script_path = os.path.join(tool_dir, SCRIPTS_DIR, f"{name}.py")
        if os.path.exists(script_path):
            return
        content = f'''"""Tool: {name} — {description}"""

import json
from typing import Any, Dict


def execute(params: Dict[str, Any]) -> str:
    """Execute the tool with the given parameters."""
    return json.dumps({{"status": "ok", "tool": "{name}", "result": "not yet implemented"}})
'''
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _generate_readme(self, name: str, description: str, tool_dir: str):
        readme = os.path.join(tool_dir, "read.md")
        if os.path.exists(readme):
            return
        content = f"# {name}\n\n{description}\n\n## Usage\n\nDescribe how to use this tool.\n"
        with open(readme, "w", encoding="utf-8") as f:
            f.write(content)
