from __future__ import annotations

__version__ = "2.0.0"

import asyncio
import os
from pathlib import Path
from typing import List, Optional

from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult


class GitOpsTool(BaseTool):
    name = "git_ops"
    description = "Inspect repository state, branches, diffs, logs, and tracked files"

    def is_read_only(self, params=None) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True

    async def _run(self, args: List[str], cwd: Path) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            if err:
                output = f"{output}\n[stderr]\n{err}".strip()
            return ToolResult(success=proc.returncode == 0, output=output, metadata={"exit_code": proc.returncode})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    async def execute(
        self,
        action: str,
        ref: Optional[str] = None,
        path: Optional[str] = None,
        name_only: bool = False,
        limit: int = 20,
        **kwargs,
    ) -> ToolResult:
        root = Path(self.root_dir or os.getcwd())
        limit = max(1, min(int(limit or 20), 200))
        base = ["git"]

        if action == "status":
            args = base + ["status", "--short", "--branch"]
        elif action == "diff":
            args = base + ["diff"]
            if name_only:
                args.append("--name-only")
            if ref:
                args.append(ref)
            if path:
                args.extend(["--", path])
        elif action == "log":
            args = base + ["log", f"-n{limit}", "--oneline", "--decorate"]
            if ref:
                args.append(ref)
        elif action == "branch":
            args = base + ["branch", "--all", "--verbose"]
        elif action == "show":
            args = base + ["show", "--stat", ref or "HEAD"]
        elif action == "files":
            args = base + ["ls-files"]
            if path:
                args.append(path)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return await self._run(args, root)
