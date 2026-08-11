from __future__ import annotations

__version__ = "2.0.0"
import asyncio
import os
from typing import Optional

from sandbox.sandbox_manager import SovereignSandbox
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class TerminalTool(BaseTool):
    name = "terminal"
    description = "Run shell commands, including local build, preview, and development-server commands"

    async def execute(
        self,
        command: str,
        timeout: int = 30,
        workdir: Optional[str] = None,
        shell: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            cwd = workdir or self.root_dir or os.getcwd()
            sandbox = SovereignSandbox(self.root_dir or os.getcwd())
            chunks = []
            try:
                stream = sandbox.stream_execute(command, cwd, timeout=timeout, shell=shell)
                async for chunk in stream:
                    chunks.append(chunk)
            except TypeError as exc:
                # Keep compatibility with injected/test sandboxes and older
                # plugin implementations that predate the shell selector.
                if "unexpected keyword argument 'shell'" not in str(exc):
                    raise
                async for chunk in sandbox.stream_execute(command, cwd, timeout=timeout):
                    chunks.append(chunk)
            output = "".join(chunks)
            exit_code = sandbox.last_exit_code
            return ToolResult(
                success=(exit_code == 0) and "[SANDBOX_BLOCK]" not in output and "[SANDBOX_TIMEOUT]" not in output,
                output=output,
                metadata={
                    "exit_code": exit_code,
                    "command": command,
                    "workdir": os.path.abspath(cwd),
                    "timeout": timeout,
                    "shell": shell or "cmd",
                },
            )
        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
