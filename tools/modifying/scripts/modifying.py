from __future__ import annotations

__version__ = "2.0.0"
import os

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ModifyingTool(BaseTool):
    name = "modifying"
    description = "Edit text in an existing file"

    async def execute(self, path: str, old_string: str, new_string: str = "", **kwargs) -> ToolResult:
        try:
            full = os.path.normpath(os.path.join(self.root_dir, path)) if self.root_dir and not os.path.isabs(path) else os.path.normpath(path)
            if self.root_dir and not full.startswith(os.path.normpath(self.root_dir)):
                return ToolResult(success=False, error=f"Path traversal blocked: {path}")
            if not os.path.isfile(full):
                return ToolResult(success=False, error=f"File not found: {path}")
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            if old_string not in content:
                return ToolResult(success=False, error=f"old_string not found in: {path}")
            new_content = content.replace(old_string, new_string, 1)
            with open(full, "w", encoding="utf-8") as f:
                f.write(new_content)
            return ToolResult(success=True, output=f"Modified: {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
