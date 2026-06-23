from __future__ import annotations
import asyncio
import os
from typing import Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class BashTool(BaseTool):
    name = "bash"
    description = "Execute shell commands safely"

    async def execute(self, command: str, timeout: int = 30, workdir: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            cwd = workdir or self.root_dir or os.getcwd()
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace")
            if stderr:
                output += f"\n[stderr]\n{stderr.decode(errors='replace')}"
            return ToolResult(success=proc.returncode == 0, output=output, metadata={"exit_code": proc.returncode})
        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
