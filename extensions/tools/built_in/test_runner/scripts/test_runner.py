from __future__ import annotations

__version__ = "2.0.0"

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from sandbox.sandbox_manager import SovereignSandbox
from extensions.tools.built_in.nexus_tools.base_tool import BaseTool, ToolResult


class TestRunnerTool(BaseTool):
    name = "test_runner"
    description = "Run targeted test commands for Python, Node, or generic project checks"

    def is_read_only(self, params=None) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def _detect_command(self, root: Path, framework: str, target: Optional[str]) -> str:
        chosen = (framework or "auto").lower().strip()
        python_configured = any((root / name).exists() for name in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"))
        if chosen == "pytest" or (chosen == "auto" and python_configured):
            return f"python -m pytest {target}".strip() if target else "python -m pytest"
        if chosen in {"vitest", "jest"}:
            return f"npm test -- {target}".strip() if target else "npm test"
        if chosen == "npm":
            return f"npm test -- {target}".strip() if target else "npm test"
        if chosen == "auto":
            package_json = root / "package.json"
            if package_json.exists():
                try:
                    package = json.loads(package_json.read_text(encoding="utf-8"))
                    scripts = package.get("scripts") or {}
                    if "test" in scripts:
                        return f"npm test -- {target}".strip() if target else "npm test"
                except (OSError, json.JSONDecodeError, TypeError):
                    pass
                return f"npm test -- {target}".strip() if target else "npm test"
            return f"python -m pytest {target}".strip() if target else "python -m pytest"
        return f"python -m pytest {target}".strip() if target else "python -m pytest"

    async def execute(
        self,
        command: Optional[str] = None,
        target: Optional[str] = None,
        framework: str = "auto",
        timeout: int = 120,
        **kwargs,
    ) -> ToolResult:
        root = Path(self.root_dir or os.getcwd())
        cmd = (command or "").strip() or self._detect_command(root, framework, target)
        try:
            sandbox = SovereignSandbox(str(root))
            chunks = []
            async for chunk in sandbox.stream_execute(cmd, str(root), timeout=timeout):
                chunks.append(chunk)
            output = "".join(chunks).strip()
            exit_code = sandbox.last_exit_code
            return ToolResult(
                success=(exit_code == 0) and "[SANDBOX_BLOCK]" not in output and "[SANDBOX_TIMEOUT]" not in output,
                output=output,
                metadata={"exit_code": exit_code, "command": cmd, "workdir": str(root), "timeout": timeout},
            )
        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"Test command timed out after {timeout}s", metadata={"command": cmd})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), metadata={"command": cmd})

    async def stream_execute(
        self,
        command: Optional[str] = None,
        target: Optional[str] = None,
        framework: str = "auto",
        timeout: int = 120,
        **kwargs,
    ):
        root = Path(self.root_dir or os.getcwd())
        cmd = (command or "").strip() or self._detect_command(root, framework, target)
        sandbox = SovereignSandbox(str(root))
        async for chunk in sandbox.stream_execute(cmd, str(root), timeout=timeout):
            yield chunk
        if sandbox.last_exit_code:
            yield ToolResult(success=False, error=f"Test command exited with code {sandbox.last_exit_code}", metadata={"command": cmd})
