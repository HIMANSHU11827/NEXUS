import asyncio
import codecs
import logging
import os
import re
import subprocess
from enum import Enum
from typing import AsyncGenerator, Optional

logger = logging.getLogger("NEXUS_SANDBOX")

class SandboxTier(Enum):
    NO_SANDBOX = "no_sandbox"  # Direct execution (Default)
    NORMAL = "normal"          # Workspace-only shell isolation
    DOCKER = "docker"          # Full container isolation

class SovereignSandbox:
    """
    NEXUS SOVEREIGN SANDBOX 2.0
    Implements sandbox tiering. Permissions decide whether a command may run;
    this layer decides where the command may touch.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        
        tier_env = os.environ.get("NEXUS_SANDBOX_TIER", "no_sandbox").lower()
        try:
            self.tier = SandboxTier(tier_env)
        except ValueError:
            logger.warning("Invalid NEXUS_SANDBOX_TIER=%r; falling back to normal sandbox", tier_env)
            self.tier = SandboxTier.NORMAL
        self.last_exit_code: Optional[int] = None

    @staticmethod
    def _normalize_host_command(command: str) -> str:
        if os.name != "nt":
            return command
        return re.sub(
            r'(?P<quote>["\']?)/(?P<drive>[a-zA-Z])/(?P<rest>[^"\'\r\n]*)',
            lambda match: f'{match.group("quote")}{match.group("drive").upper()}:/{match.group("rest")}',
            command,
        )

    def _is_inside_root(self, path: str) -> bool:
        try:
            return os.path.commonpath([self.root, os.path.abspath(path)]) == self.root
        except ValueError:
            return False

    def _workspace_block(self, reason: str) -> str:
        return f"[SANDBOX_BLOCK]: Simple sandbox is workspace-only: {reason}"

    def _iter_command_paths(self, command: str, base_dir: str):
        """Yield likely filesystem paths mentioned by a shell command."""
        drive_paths = re.findall(r"(?<![\w.-])([a-zA-Z]:[\\/][^\"'\s<>|;&]*)", command)
        unc_paths = re.findall(r"(\\\\[^\"'\s<>|;&]+)", command)
        for path in drive_paths + unc_paths:
            yield path.rstrip(".,)")

        for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'|([^\s<>|;&]+)', command):
            token = next(group for group in match.groups() if group is not None)
            token = token.strip().strip("`").rstrip(".,)")
            if not token or "://" in token:
                continue
            lower = token.lower()
            if lower in {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
                continue
            if token.startswith(("-", "/")) and not re.match(r"^/[a-zA-Z]/", token):
                if not (len(token) > 2 and "/" in token[1:]):
                    continue

            looks_like_path = (
                re.match(r"^[a-zA-Z]:[\\/]", token) is not None
                or token.startswith("\\\\")
                or token.startswith(("~", ".", "..", "/", "\\"))
                or "\\" in token
                or "/" in token
            )
            if looks_like_path:
                yield token

    def _validate_workspace_scope(self, command: str, workdir: str) -> Optional[str]:
        target_dir = os.path.abspath(workdir)
        if not self._is_inside_root(target_dir):
            return self._workspace_block(f"workdir is outside workspace: {target_dir}")

        for raw_path in self._iter_command_paths(command, target_dir):
            # Expand %VAR% / $VAR / ${VAR} before resolving so env-var
            # references cannot smuggle absolute outside paths past the guard.
            raw_path = os.path.expandvars(raw_path)
            if raw_path.startswith("~"):
                resolved = os.path.abspath(os.path.expanduser(raw_path))
            elif os.path.isabs(raw_path):
                resolved = os.path.abspath(raw_path)
            else:
                resolved = os.path.abspath(os.path.join(target_dir, raw_path))

            if not self._is_inside_root(resolved):
                return self._workspace_block(f"path is outside workspace: {raw_path}")
        return None

    def execute(self, command: str, workdir: Optional[str] = None) -> str:
        """
        [SOVEREIGN_EXECUTION]: Routes command through the selected security tier.
        """
        # 1. NO_SANDBOX: Direct execution
        if self.tier == SandboxTier.NO_SANDBOX:
            return self._execute_direct(command, workdir or self.root)

        command = self._normalize_host_command(command)
        target_dir = os.path.abspath(workdir if workdir else self.root)
        
        # 3. NORMAL / DOCKER: validate host workspace scope before execution.
        if self.tier in (SandboxTier.NORMAL, SandboxTier.DOCKER):
            block = self._validate_workspace_scope(command, target_dir)
            if block:
                return block

        if self.tier == SandboxTier.NORMAL:
            return self._execute_restricted(command, target_dir)
            
        # 4. DOCKER: Container Isolation
        if self.tier == SandboxTier.DOCKER:
            return self._execute_docker(command, target_dir)

        return "[SANDBOX_ERROR]: Invalid sandbox configuration."

    async def stream_execute(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """Execute a command and yield Unicode-safe output chunks as they arrive."""
        command = self._normalize_host_command(command)
        target_dir = os.path.abspath(workdir or self.root)
        if self.tier in (SandboxTier.NORMAL, SandboxTier.DOCKER):
            block = self._validate_workspace_scope(command, target_dir)
            if block:
                yield block
                return

        effective_timeout = float(timeout) if timeout is not None else 600.0
        if self.tier == SandboxTier.NORMAL:
            env = {
                "PATH": os.environ.get("PATH", ""),
                "NEXUS_ROOT": self.root,
                "USER": "nexus_worker",
            }
            venv_scripts = os.path.join(self.root, ".venv", "Scripts")
            if os.path.isdir(venv_scripts):
                env["PATH"] = venv_scripts + os.pathsep + env["PATH"]
            effective_timeout = float(timeout) if timeout is not None else 300.0
        else:
            env = os.environ.copy()
            venv_scripts = os.path.join(self.root, ".venv", "Scripts")
            if os.path.isdir(venv_scripts):
                env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")

        if self.tier == SandboxTier.DOCKER:
            # Fail closed: a missing Docker daemon yields a block, never a
            # silent host fallback for a request that asked for isolation.
            if not self._docker_available():
                self.last_exit_code = -1
                yield (
                    "[SANDBOX_BLOCK]: DOCKER tier is active but Docker is not "
                    "available. Failing closed instead of falling back to the host."
                )
                return
            rel_workdir = os.path.relpath(target_dir, self.root).replace("\\", "/")
            container_workdir = f"/workspace/{rel_workdir}" if rel_workdir != "." else "/workspace"
            # Network and image write access are disabled: the container only
            # sees the mounted workspace and cannot mutate its own filesystem.
            process = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm",
                "--network=none",
                "--read-only",
                "-v", f"{self.root}:/workspace",
                "-w", container_workdir,
                "nexus-worker", "sh", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            effective_timeout = float(timeout) if timeout is not None else 300.0
        else:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=target_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

        assert process.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        deadline = asyncio.get_running_loop().time() + effective_timeout
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                raw = await asyncio.wait_for(process.stdout.read(1024), timeout=remaining)
                if not raw:
                    break
                text = decoder.decode(raw)
                if text:
                    yield text
            tail = decoder.decode(b"", final=True)
            if tail:
                yield tail
            return_code = await process.wait()
            self.last_exit_code = return_code
            if return_code:
                yield f"\n[EXIT_CODE]: {return_code}"
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            self.last_exit_code = -1
            yield f"\n[SANDBOX_TIMEOUT]: Execution exceeded {int(effective_timeout)} seconds."

    def _execute_direct(self, command: str, workdir: str) -> str:
        """Direct execution without isolation (Default)."""
        try:
            process = subprocess.run(
                command if os.name == "nt" else ["sh", "-c", command],
                shell=(os.name == "nt"),
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=600
            )
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except Exception as e:
            return f"[EXECUTION_ERROR]: {str(e)}"

    def _execute_restricted(self, command: str, workdir: str) -> str:
        """Workspace-only restricted shell isolation."""
        try:
            command = self._normalize_host_command(command)
            workdir = os.path.abspath(workdir)
            block = self._validate_workspace_scope(command, workdir)
            if block:
                return block
            safe_env = {
                "PATH": os.environ.get("PATH", ""),
                "NEXUS_ROOT": self.root,
                "USER": "nexus_worker"
            }
            process = subprocess.run(
                command if os.name == "nt" else ["sh", "-c", command],
                shell=(os.name == "nt"),
                cwd=workdir,
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=300
            )
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except subprocess.TimeoutExpired:
            return "[SANDBOX_TIMEOUT]: Restricted execution exceeded safety limit."
        except Exception as e:
            return f"[SANDBOX_ERROR]: {str(e)}"

    @staticmethod
    def _docker_available() -> bool:
        """Best-effort probe that the Docker CLI and daemon are reachable.

        Returns False on any probe failure so DOCKER-tier requests can fail
        closed instead of silently degrading to host execution.
        """
        try:
            probe = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return bool(getattr(probe, "returncode", -1) == 0)
        except Exception:
            return False

    def _execute_docker(self, command: str, workdir: str) -> str:
        """Containerized isolation via Docker (fail-closed)."""
        # DOCKER tier must never silently fall back to host execution: an
        # unavailable daemon is a hard block, not an excuse to lower isolation.
        if not self._docker_available():
            return (
                "[SANDBOX_BLOCK]: DOCKER tier is active but Docker is not "
                "available. Failing closed instead of falling back to the host."
            )

        try:
            rel_workdir = os.path.relpath(workdir, self.root).replace("\\", "/")
            container_workdir = f"/workspace/{rel_workdir}" if rel_workdir != "." else "/workspace"

            # Map Windows path format or posix format to container volume mount.
            # Network and write access are disabled by default: the container
            # can only see the mounted workspace and cannot mutate its image.
            docker_cmd = [
                "docker", "run", "--rm",
                "--network=none",
                "--read-only",
                "-v", f"{self.root}:/workspace",
                "-w", container_workdir,
                "nexus-worker",
                "sh", "-c", command
            ]

            process = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=300 # 5 minutes container limit
            )
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except subprocess.TimeoutExpired:
            return "[SANDBOX_TIMEOUT]: Docker execution exceeded container safety limits."
        except Exception as e:
            return f"[SANDBOX_ERROR]: Docker runtime error: {str(e)}"
