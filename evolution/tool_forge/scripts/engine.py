"""ToolForge — creates new NEXUS tools from LLM-generated specifications.

Each tool gets its own folder under tools/<name>/ with:
  - <name>.json     — schema (name, version, description, defaults, permissions)
  - scripts/<name>.py — Python implementation (BaseTool subclass)
  - read.md         — documentation
"""
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

VALID_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$')
TOOLS_DIR = "tools"
SCRIPTS_DIR = "scripts"


class ToolForge:
    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.tools_dir = os.path.join(self.root, TOOLS_DIR)
        os.makedirs(self.tools_dir, exist_ok=True)

    def forge(self, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        name_raw = tool_def.get("name", "").strip().lower().replace(" ", "_").replace("-", "_")
        if not name_raw:
            return {"created": False, "error": "name is required"}
        if not VALID_NAME_RE.match(name_raw):
            return {"created": False, "error": f"invalid tool name: {name_raw}"}

        tool_dir = os.path.join(self.tools_dir, name_raw)
        if os.path.exists(tool_dir):
            return self.refine(name_raw, tool_def)

        os.makedirs(tool_dir, exist_ok=True)
        os.makedirs(os.path.join(tool_dir, SCRIPTS_DIR), exist_ok=True)

        schema = self._get_schema(tool_def)
        with open(os.path.join(tool_dir, f"{name_raw}.json"), "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)

        self._generate_script(name_raw, tool_def.get("description", ""), tool_dir)
        self._generate_readme(name_raw, tool_def.get("description", ""), tool_dir)

        logger.info(f"[TOOL_FORGE] Created tool '{name_raw}' v{schema['version']}")
        return {"created": True, "name": name_raw, "version": schema["version"], "path": tool_dir}

    def refine(self, name: str, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        tool_dir = os.path.join(self.tools_dir, name)
        if not os.path.exists(tool_dir):
            return {"created": False, "error": f"tool '{name}' not found"}

        schema_path = os.path.join(tool_dir, f"{name}.json")
        if not os.path.exists(schema_path):
            return {"created": False, "error": f"schema not found for '{name}'"}

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        vm = VersionManager(self.root)
        new_ver = vm.bump(name, "major" if tool_def.get("major", False) else "minor", self.root)
        if not new_ver:
            major = tool_def.get("major", False)
            cur = schema.get("version", "1.0.0")
            parts = cur.split(".")
            if major:
                new_ver = f"{int(parts[0]) + 1}.0.0"
            else:
                patch = int(parts[2]) + 1 if len(parts) > 2 else 1
                new_ver = f"{parts[0]}.{parts[1] if len(parts) > 1 else 0}.{patch}"

        schema["version"] = new_ver
        if "description" in tool_def:
            schema["description"] = tool_def["description"]
        if "permissions" in tool_def:
            schema["permissions"] = tool_def["permissions"]

        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)

        logger.info(f"[TOOL_FORGE] Refined tool '{name}' to v{new_ver}")
        return {"created": True, "name": name, "version": new_ver, "refined": True}

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
