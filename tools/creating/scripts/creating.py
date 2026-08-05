from __future__ import annotations

__version__ = "2.0.0"
import os

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class CreatingTool(BaseTool):
    name = "creating"
    description = "Create a new file with content"

    async def execute(self, path: str, content: str = "", **kwargs) -> ToolResult:
        try:
            full = os.path.normpath(os.path.join(self.root_dir, path)) if self.root_dir and not os.path.isabs(path) else os.path.normpath(path)
            if self.root_dir and os.path.commonpath([os.path.abspath(self.root_dir), full]) != os.path.abspath(self.root_dir):
                return ToolResult(success=False, error=f"Path traversal blocked: {path}")
            parent = os.path.dirname(full)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(full):
                return ToolResult(success=False, error=f"File already exists: {path}")
            with open(full, "w", encoding="utf-8") as f:
                f.write(content or "")
            return ToolResult(success=True, output=f"Created: {path}", metadata={"path": full, "bytes": len(content or "")})
        except Exception as e:
            return ToolResult(success=False, error=str(e))
