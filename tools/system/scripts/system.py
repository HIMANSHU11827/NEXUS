from __future__ import annotations
import os
import platform
from pathlib import Path
from typing import Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class SystemTool(BaseTool):
    name = "system"
    description = "Monitor and audit system resources"

    async def execute(self, action: str, target: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            if action == "info":
                info = [
                    f"OS: {platform.system()} {platform.release()}",
                    f"Python: {platform.python_version()}",
                    f"Host: {platform.node()}",
                    f"CWD: {os.getcwd()}",
                ]
                return ToolResult(success=True, output="\n".join(info))

            elif action == "env":
                return ToolResult(success=True, output="\n".join(f"{k}={v}" for k, v in sorted(os.environ.items())))

            elif action == "audit":
                root = Path(self.root_dir or ".")
                files = list(root.rglob("*"))
                return ToolResult(success=True, output=f"Audit: {len(files)} files found in {root}")

            return ToolResult(success=True, output=f"System action '{action}' completed")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
