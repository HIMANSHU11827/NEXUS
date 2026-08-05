from __future__ import annotations

__version__ = "2.0.0"
import os

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ReadingTool(BaseTool):
    name = "reading"
    description = "Read file contents"

    async def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            full = os.path.normpath(os.path.join(self.root_dir, path)) if self.root_dir and not os.path.isabs(path) else os.path.normpath(path)
            if self.root_dir and os.path.commonpath([os.path.abspath(self.root_dir), full]) != os.path.abspath(self.root_dir):
                return ToolResult(success=False, error=f"Path traversal blocked: {path}")
            if not os.path.isfile(full):
                return ToolResult(success=False, error=f"File not found: {path}")
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
