from __future__ import annotations

__version__ = "2.0.0"
import asyncio
import os
from typing import Optional

from sandbox.sandbox_manager import SovereignSandbox
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class BashTool(BaseTool):
    name = "bash"
    description = "Execute shell commands safely"

    async def execute(self, command: str, timeout: int = 30, workdir: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            cwd = workdir or self.root_dir or os.getcwd()
            sandbox = SovereignSandbox(self.root_dir or os.getcwd())
            chunks = []
            async for chunk in sandbox.stream_execute(command, cwd, timeout=timeout):
                chunks.append(chunk)
            output = "".join(chunks)
            exit_code = sandbox.last_exit_code
            return ToolResult(
                success=(exit_code in (None, 0)) and "[SANDBOX_BLOCK]" not in output and "[SANDBOX_TIMEOUT]" not in output,
                output=output,
                metadata={"exit_code": exit_code},
            )
        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
