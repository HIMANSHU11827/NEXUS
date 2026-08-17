from __future__ import annotations

__version__ = "2.0.0"
import asyncio
import os

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult


class CreatingTool(BaseTool):
    name = "creating"
    description = "Create a new file with content"

    async def execute(self, path: str, content: str = "", **kwargs) -> ToolResult:
        """Create a file without blocking the event loop on filesystem I/O."""
        return await asyncio.to_thread(self._execute_sync, path, content, **kwargs)

    def _execute_sync(self, path: str, content: str = "", **kwargs) -> ToolResult:
        try:
            full = os.path.normpath(os.path.join(self.root_dir, path)) if self.root_dir and not os.path.isabs(path) else os.path.normpath(path)
            full = os.path.realpath(full)
            root = os.path.realpath(self.root_dir) if self.root_dir else None
            if root and os.path.commonpath([root, full]) != root:
                return ToolResult(success=False, error=f"Path traversal blocked: {path}")
            self.assert_execution_active()
            parent = os.path.dirname(full)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(full):
                return ToolResult(success=False, error=f"File already exists: {path}")
            self.assert_execution_active()
            with open(full, "w", encoding="utf-8") as f:
                f.write(content or "")
            return ToolResult(success=True, output=f"Created: {path}", metadata={"path": full, "bytes": len(content or "")})
        except Exception as e:
            return ToolResult(success=False, error=str(e))
