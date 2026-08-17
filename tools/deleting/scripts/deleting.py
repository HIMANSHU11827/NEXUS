from __future__ import annotations

__version__ = "2.0.0"
import asyncio
import os

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class DeletingTool(BaseTool):
    name = "deleting"
    description = "Delete a file"

    async def execute(self, path: str, **kwargs) -> ToolResult:
        """Delete a file without blocking the event loop on filesystem I/O."""
        return await asyncio.to_thread(self._execute_sync, path, **kwargs)

    def _execute_sync(self, path: str, **kwargs) -> ToolResult:
        try:
            full = os.path.normpath(os.path.join(self.root_dir, path)) if self.root_dir and not os.path.isabs(path) else os.path.normpath(path)
            full = os.path.realpath(full)
            root = os.path.realpath(self.root_dir) if self.root_dir else None
            if root and os.path.commonpath([root, full]) != root:
                return ToolResult(success=False, error=f"Path traversal blocked: {path}")
            if not os.path.isfile(full):
                return ToolResult(success=False, error=f"File not found: {path}")
            self.assert_execution_active()
            os.remove(full)
            return ToolResult(success=True, output=f"Deleted: {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
