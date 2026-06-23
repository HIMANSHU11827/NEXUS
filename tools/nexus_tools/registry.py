"""ToolRegistry — discovers and manages NEXUS tools from tools/<name>/."""

import os
import json
import importlib
import inspect
import logging
from typing import Any, Dict, Optional

from tools.nexus_tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("NEXUS_TOOL_REGISTRY")


class ToolEntry:
    """Represents a registered tool with its metadata and handler instance."""

    def __init__(self, name: str, schema: dict, instance: Any, check_fn=None):
        self.name = name
        self.schema = schema
        self.instance = instance
        self.check_fn = check_fn


class ToolRegistry:
    """Discovers tools from tools/<name>/ and provides runtime execution."""

    def __init__(self, root: Optional[str] = None):
        self.root = root or os.getcwd()
        self._tools: Dict[str, ToolEntry] = {}
        self._discover()

    def _discover(self):
        tools_dir = os.path.join(self.root, "tools")
        if not os.path.isdir(tools_dir):
            return
        for name in os.listdir(tools_dir):
            if name.startswith(("_", ".")) or name == "nexus_tools":
                continue
            tool_dir = os.path.join(tools_dir, name)
            if not os.path.isdir(tool_dir):
                continue
            jsnol = os.path.join(tool_dir, f"{name}.jsnol")
            if not os.path.isfile(jsnol):
                continue
            try:
                with open(jsnol, encoding="utf-8") as f:
                    meta = json.load(f)
                scripts_dir = os.path.join(tool_dir, "scripts")
                handler_cls = None
                if os.path.isdir(scripts_dir):
                    for script in sorted(
                        s for s in os.listdir(scripts_dir)
                        if s.endswith(".py") and not s.startswith("_")
                    ):
                        mod_name = script[:-3]
                        try:
                            spec = importlib.util.spec_from_file_location(
                                mod_name, os.path.join(scripts_dir, script)
                            )
                            if spec and spec.loader:
                                mod = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(mod)
                                for _, obj in inspect.getmembers(mod, inspect.isclass):
                                    if issubclass(obj, BaseTool) and obj is not BaseTool:
                                        handler_cls = obj
                                        break
                                if handler_cls:
                                    break
                        except Exception:
                            logger.warning(f"Could not load: {os.path.join(scripts_dir, script)}")
                instance = handler_cls(root_dir=self.root) if handler_cls else None
                entry = ToolEntry(
                    name=name,
                    schema=meta,
                    instance=instance,
                )
                self._tools[name] = entry
                logger.info(f"Registered tool: {name} v{meta.get('version', '?')}")
            except Exception as e:
                logger.error(f"Failed to register tool '{name}': {e}")

    def get(self, name: str) -> Optional[ToolEntry]:
        return self._tools.get(name)

    def list_tools(self) -> Dict[str, Any]:
        return {
            name: {
                "version": entry.schema.get("version", "?"),
                "description": entry.schema.get("description", ""),
            }
            for name, entry in self._tools.items()
        }

    async def execute(self, name: str, **params) -> ToolResult:
        entry = self.get(name)
        if not entry:
            raise ValueError(f"Tool '{name}' not found. Available: {list(self._tools.keys())}")
        if entry.instance is None:
            raise NotImplementedError(f"Tool '{name}' has no executable handler")
        return await entry.instance.execute(**params)
