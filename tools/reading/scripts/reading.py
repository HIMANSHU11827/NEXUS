from __future__ import annotations

__version__ = "2.0.0"
import asyncio
import os

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class ReadingTool(BaseTool):
    name = "reading"
    description = "Read file contents"

    async def execute(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        **kwargs,
    ) -> ToolResult:
        """Read file contents without blocking the event loop."""
        return await asyncio.to_thread(
            self._execute_sync,
            path,
            start_line=start_line,
            end_line=end_line,
            **kwargs,
        )

    def _execute_sync(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        **kwargs,
    ) -> ToolResult:
        try:
            if start_line is not None and start_line < 1:
                return ToolResult(success=False, error="start_line must be >= 1")
            if end_line is not None and end_line < 1:
                return ToolResult(success=False, error="end_line must be >= 1")
            if start_line is not None and end_line is not None and end_line < start_line:
                return ToolResult(success=False, error="end_line must be >= start_line")
            full = os.path.normpath(os.path.join(self.root_dir, path)) if self.root_dir and not os.path.isabs(path) else os.path.normpath(path)
            full = os.path.realpath(full)
            root = os.path.realpath(self.root_dir) if self.root_dir else None
            if root and os.path.commonpath([root, full]) != root:
                return ToolResult(success=False, error=f"Path traversal blocked: {path}")
            if not os.path.isfile(full):
                return ToolResult(success=False, error=f"File not found: {path}")
            with open(full, "r", encoding="utf-8") as f:
                if start_line is None and end_line is None:
                    content = f.read()
                else:
                    lines = f.readlines()
                    first = (start_line or 1) - 1
                    last = end_line if end_line is not None else len(lines)
                    content = "".join(lines[first:last])
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
