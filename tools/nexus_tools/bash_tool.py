"""
NEXUS BASH TOOL — Claude Code BashTool + HyperAgents BashSession hybrid.
Supports sync, streaming, and persistent session modes.
"""

import subprocess
import os
import time
from typing import Any, Dict, Optional, List

from core.autonomy.risk import CommandRiskScorer
from tools.nexus_tools.base_tool import BaseTool, ToolResult


class BashSession:
    """Persistent bash session with timeout and sentinel-based output."""

    def __init__(self, root_dir: str = ".", timeout: float = 120.0):
        self.root = os.path.abspath(root_dir)
        self.timeout = timeout
        self._process: Optional[subprocess.Popen] = None
        self._started = False
        self._sentinel = "<<NEXUS_EXIT>>"

    def start(self):
        if self._started:
            return
        shell = ["bash"] if os.name != "nt" else ["cmd.exe"]
        self._process = subprocess.Popen(
            shell,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.root,
        )
        self._started = True

    def run(self, command: str) -> str:
        """Run command in persistent session."""
        if not self._started:
            self.start()
        try:
            full_cmd = f'{command}\necho "{self._sentinel}"\n'
            self._process.stdin.write(full_cmd)
            self._process.stdin.flush()

            output_lines = []
            start_time = time.time()
            while True:
                if time.time() - start_time > self.timeout:
                    return f"[TIMEOUT after {self.timeout}s]"
                line = self._process.stdout.readline()
                if self._sentinel in line:
                    break
                output_lines.append(line.rstrip())
            return "\n".join(output_lines).strip()
        except Exception as e:
            return f"[SESSION_ERROR]: {str(e)}"

    def stop(self):
        if self._started and self._process:
            self._process.terminate()
            self._started = False


class BashTool(BaseTool):
    """Claude Code BashTool — execute shell commands with session support."""

    name = "bash"
    description = (
        "Execute shell commands. Supports persistent sessions, timeouts, and streaming."
    )
    aliases = ["shell", "exec", "run"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self._session: Optional[BashSession] = None
        self.risk_scorer = CommandRiskScorer()

    def call(
        self, command: str = "", session: bool = False, timeout: int = 60, sandbox: bool = False, **kwargs
    ) -> ToolResult:
        command = command or kwargs.get("cmd", "")
        if not command:
            return ToolResult(error="No command provided")

        if os.environ.get("NEXUS_ALLOW_DANGEROUS_SHELL", "false").lower() != "true":
            assessment = self.risk_scorer.assess(command)
            if assessment.blocked:
                return ToolResult(error=f"Command blocked by risk policy: {assessment.summary()}")

        if sandbox:
            # 🛡️ SOVEREIGN SANDBOX MODE
            from utils.sandbox import NexusSandbox
            sb = NexusSandbox(self.root)
            # Mount critical context for the command
            files = kwargs.get("mount", [])
            ret, out, err = sb.execute(command, files_to_mount=files)
            if ret != 0:
                return ToolResult(data=out, error=f"[SANDBOX_FAIL] {ret}: {err}")
            return ToolResult(data=out if out else "[SANDBOX_OK]")

        if session:
            if not self._session:
                self._session = BashSession(self.root, timeout=float(timeout))
            output = self._session.run(command)
            return ToolResult(data=output)

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.root,
                timeout=timeout,
            )
            output = proc.stdout.strip()
            if proc.returncode != 0:
                err = proc.stderr.strip()
                return ToolResult(
                    data=output,
                    error=f"Exit {proc.returncode}: {err}"
                    if err
                    else f"Exit {proc.returncode}",
                )
            return ToolResult(data=output if output else "[OK]")
        except subprocess.TimeoutExpired:
            return ToolResult(error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(error=str(e))

    def is_concurrency_safe(self, input_data=None):
        return False  # Bash commands may have side effects

    def is_read_only(self, input_data=None):
        if input_data:
            cmd = (input_data.get("command") or input_data.get("cmd") or "").lower().strip()
            safe_prefixes = [
                "ls",
                "cat",
                "head",
                "tail",
                "wc",
                "grep",
                "find",
                "echo",
                "pwd",
                "date",
            ]
            return any(cmd.startswith(p) for p in safe_prefixes)
        return False
