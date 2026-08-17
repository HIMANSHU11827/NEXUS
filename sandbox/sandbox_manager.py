import asyncio
import base64
import codecs
import logging
import os
import re
import signal
import shutil
import subprocess
from enum import Enum
from typing import AsyncGenerator, Optional

logger = logging.getLogger("NEXUS_SANDBOX")

class SandboxTier(Enum):
    NO_SANDBOX = "no_sandbox"  # Explicit opt-out only
    NORMAL = "normal"          # Workspace-only shell isolation
    DOCKER = "docker"          # Full container isolation

class SovereignSandbox:
    """
    NEXUS SOVEREIGN SANDBOX 2.0
    Implements sandbox tiering. Permissions decide whether a command may run;
    this layer decides where the command may touch.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.realpath(root_dir)
        
        tier_env = os.environ.get("NEXUS_SANDBOX_TIER", "normal").lower()
        try:
            self.tier = SandboxTier(tier_env)
        except ValueError:
            logger.warning("Invalid NEXUS_SANDBOX_TIER=%r; falling back to normal sandbox", tier_env)
            self.tier = SandboxTier.NORMAL
        self.last_exit_code: Optional[int] = None

    @staticmethod
    def _process_group_kwargs(*, detached: bool = False) -> dict:
        """Create child processes with an owned descendant boundary.

        Foreground commands stay in an owned process group so timeout and
        cancellation can reap their descendants.  Detached commands get a
        separate lifetime boundary and must not be reaped by the terminal
        stream that launched them.
        """
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            if detached:
                flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            return {
                "creationflags": flags,
            }
        return {"start_new_session": True}

    @staticmethod
    def should_background_command(command: str) -> bool:
        """Recognize commands that are normally preview/development servers.

        This is deliberately conservative.  Callers can always opt in with
        ``background=True``; automatic detachment is limited to commands
        whose normal contract is to keep serving until explicitly stopped.
        """
        text = str(command or "").strip().lower()
        if not text:
            return False
        patterns = (
            r"\bpython(?:\.exe)?\s+-m\s+http\.server\b",
            r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:dev|start|preview)\b",
            r"\b(?:vite|uvicorn|hypercorn)\b",
            r"\bflask\s+run\b",
            r"\bphp\s+-s\b",
            r"\bhttp\.server\b",
        )
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _normalize_host_command(command: str) -> str:
        if os.name != "nt":
            return command
        # POSIX commands frequently discard output with /dev/null.  On
        # Windows that token is a device name, not a filesystem path.  Map it
        # before workspace validation so a harmless redirect is not rejected
        # as an attempt to access outside the workspace.
        command = re.sub(r"(?<![\w.-])/dev/null(?![\w.-])", "NUL", command, flags=re.IGNORECASE)
        return re.sub(
            r'(?P<quote>["\']?)/(?P<drive>[a-zA-Z])/(?P<rest>[^"\'\r\n]*)',
            lambda match: f'{match.group("quote")}{match.group("drive").upper()}:/{match.group("rest")}',
            command,
        )

    @staticmethod
    def _windows_cmd_compatibility_error(command: str, shell: Optional[str] = None) -> Optional[str]:
        """Return a repairable error for syntax unsupported by Windows cmd.

        The default Windows subprocess shell is ``cmd.exe``.  Silently
        rewriting shell syntax is unsafe because semicolons and pipelines can
        occur inside quoted arguments.  Instead, detect only unquoted syntax
        that is known to be Unix/PowerShell-specific and give the model an
        exact, actionable alternative.  Explicit PowerShell calls bypass
        this check.
        """
        if os.name != "nt" or str(shell or "cmd").strip().lower() != "cmd":
            return None

        masked: list[str] = []
        quote: Optional[str] = None
        top_level_semicolon = False
        for char in str(command or ""):
            if char in {"\"", "'"}:
                if quote is None:
                    quote = char
                elif quote == char:
                    quote = None
                masked.append(" ")
                continue
            if quote is None and char == ";":
                top_level_semicolon = True
            masked.append(" " if quote is not None else char)

        visible = "".join(masked)
        unix_commands = sorted(
            set(
                re.findall(
                    r"(?:^|[|&\s])(cat|grep|sed|awk|head|tail|ls|pwd|which)(?:\.exe)?(?=\s|$)",
                    visible,
                    flags=re.IGNORECASE,
                )
            )
        )
        if not top_level_semicolon and not unix_commands:
            return None

        problems: list[str] = []
        if top_level_semicolon:
            problems.append("unquoted ';' is not a command separator in cmd.exe")
        if unix_commands:
            problems.append(
                "Unix-only command(s) "
                + ", ".join(f"'{command}'" for command in unix_commands)
                + " are not available in cmd.exe"
            )
        return (
            "[EXECUTION_ERROR]: Windows cmd.exe compatibility: " + "; ".join(problems) + ".\n"
            "[NEXUS_RECOVERY_HINT]: Retry with cmd syntax ('&' or '&&' between commands and 'findstr'/'more' for output), "
            "or set shell='powershell' and use PowerShell syntax. Do not repeat the same command."
        )

    @staticmethod
    def _requested_shell(shell: Optional[str]) -> str:
        """Normalize the explicit shell selector without changing defaults."""
        value = str(shell or "cmd").strip().lower()
        if value in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            return "powershell"
        if value in {"bash", "bash.exe"}:
            return "bash"
        if value in {"wsl", "wsl.exe"}:
            return "wsl"
        return "cmd"

    @staticmethod
    def _powershell_executable() -> Optional[str]:
        """Find an installed PowerShell executable for explicit requests."""
        return shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")

    @staticmethod
    def _host_shell_argv(shell: str, command: str) -> Optional[list[str]]:
        """Return an explicit Windows shell argv, or None for cmd.exe."""
        if os.name != "nt":
            return None
        if shell == "powershell":
            executable = SovereignSandbox._powershell_executable()
            return [executable, "-NoProfile", "-NonInteractive", "-Command", command] if executable else []
        if shell == "bash":
            executable = shutil.which("bash") or shutil.which("bash.exe")
            return [executable, "-lc", command] if executable else []
        if shell == "wsl":
            executable = shutil.which("wsl.exe") or shutil.which("wsl")
            return [executable, "--", "bash", "-lc", command] if executable else []
        return None

    def _is_inside_root(self, path: str) -> bool:
        try:
            return os.path.commonpath([self.root, os.path.realpath(path)]) == self.root
        except ValueError:
            return False

    def _workspace_block(self, reason: str) -> str:
        return f"[SANDBOX_BLOCK]: Simple sandbox is workspace-only: {reason}"

    def _iter_command_paths(self, command: str, base_dir: str):
        """Yield likely filesystem paths mentioned by a shell command."""
        # Quoted Windows paths may contain spaces.  The token parser below
        # handles those whole quoted arguments; these fast-path expressions
        # are intentionally limited to unquoted paths so they do not inspect
        # only the prefix before the first space (for example, ``C:\\NEXUS AI``).
        drive_paths = re.findall(r"(?<![\"'\w.-])([a-zA-Z]:[\\/][^\"'\s<>|;&]*)", command)
        unc_paths = re.findall(r"(?<![\"'])(\\\\[^\"'\s<>|;&]+)", command)
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

        scan_commands = [command]
        # Decode PowerShell -EncodedCommand payloads and validate their paths
        # too, so base64 cannot smuggle outside paths past the workspace guard.
        for token in re.findall(r"(?i)(?<![a-z0-9-])-{1,2}enc(?:oded)?command\b\s+(\S+)", command):
            try:
                decoded = base64.b64decode(token, validate=True).decode("utf-8", errors="replace")
            except Exception:
                continue
            scan_commands.append(decoded)

        for scan_command in scan_commands:
            for raw_path in self._iter_command_paths(scan_command, target_dir):
                # Expand %VAR% / $VAR / ${VAR} / $env:VAR before resolving so
                # env-var references cannot smuggle absolute outside paths
                # past the guard. os.path.expandvars does not understand the
                # PowerShell $env:NAME form on Windows.
                raw_path = re.sub(r"(?i)\$env:([A-Za-z_][A-Za-z0-9_]*)", r"%\1%", raw_path)
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

    def execute(self, command: str, workdir: Optional[str] = None, shell: Optional[str] = None) -> str:
        """
        [SOVEREIGN_EXECUTION]: Routes command through the selected security tier.
        """
        # 1. NO_SANDBOX: Direct execution
        raw_command = command
        normalized_command = self._normalize_host_command(command)
        requested_shell = self._requested_shell(shell)
        compatibility_error = (
            self._windows_cmd_compatibility_error(normalized_command, requested_shell)
            if self.tier != SandboxTier.DOCKER else None
        )
        if compatibility_error:
            self.last_exit_code = -1
            return compatibility_error

        if self.tier == SandboxTier.NO_SANDBOX:
            return self._execute_direct(normalized_command, workdir or self.root, requested_shell)

        command = raw_command if self.tier == SandboxTier.DOCKER else normalized_command
        validation_command = normalized_command

        target_dir = os.path.abspath(workdir if workdir else self.root)
        
        # 3. NORMAL / DOCKER: validate host workspace scope before execution.
        if self.tier in (SandboxTier.NORMAL, SandboxTier.DOCKER):
            block = self._validate_workspace_scope(validation_command, target_dir)
            if block:
                self.last_exit_code = -1
                return block

        if self.tier == SandboxTier.NORMAL:
            return self._execute_restricted(command, target_dir, requested_shell)
            
        # 4. DOCKER: Container Isolation
        if self.tier == SandboxTier.DOCKER:
            return self._execute_docker(command, target_dir, requested_shell if shell else None)

        return "[SANDBOX_ERROR]: Invalid sandbox configuration."

    async def stream_execute(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: Optional[float] = None,
        shell: Optional[str] = None,
        background: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Execute a command and yield Unicode-safe output chunks as they arrive.

        With ``background=True`` the command is launched with an independent
        process lifetime and this generator returns immediately.  The caller
        receives a launch acknowledgement instead of waiting for EOF, and
        closing/cancelling the stream does not terminate the detached process.
        """
        raw_command = command
        normalized_command = self._normalize_host_command(command)
        requested_shell = self._requested_shell(shell)
        compatibility_error = (
            self._windows_cmd_compatibility_error(normalized_command, requested_shell)
            if self.tier != SandboxTier.DOCKER else None
        )
        if compatibility_error:
            self.last_exit_code = -1
            yield compatibility_error
            return
        command = raw_command if self.tier == SandboxTier.DOCKER else normalized_command
        validation_command = normalized_command
        target_dir = os.path.abspath(workdir or self.root)
        if self.tier in (SandboxTier.NORMAL, SandboxTier.DOCKER):
            block = self._validate_workspace_scope(validation_command, target_dir)
            if block:
                self.last_exit_code = -1
                yield block
                return

        effective_timeout = float(timeout) if timeout is not None else 600.0
        if self.tier == SandboxTier.NORMAL:
            env = {
                "PATH": os.environ.get("PATH", ""),
                "NEXUS_ROOT": self.root,
                "USER": "nexus_worker",
            }
            # cmd.exe and the Python launcher require these Windows runtime
            # variables.  Omitting them produces UTF-16-looking output and
            # unsigned failure codes even for successful commands.
            for key in ("SystemRoot", "WINDIR", "SystemDrive", "ComSpec", "COMSPEC", "PATHEXT"):
                if os.environ.get(key):
                    env[key] = os.environ[key]
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
            if shell and requested_shell in {"cmd", "powershell", "wsl"}:
                self.last_exit_code = -1
                yield f"[EXECUTION_ERROR]: Requested shell '{requested_shell}' is not available inside the Linux Docker worker; use shell='bash' or omit shell."
                return
            docker_shell = "bash" if requested_shell == "bash" else "sh"
            docker_args = ["docker", "run", "--rm"]
            if background:
                docker_args.append("-d")
            docker_args.extend([
                "--network=none",
                "--read-only",
                "-v", f"{self.root}:/workspace",
                "-w", container_workdir,
                "nexus-worker", docker_shell, "-c", command,
            ])
            process = await asyncio.create_subprocess_exec(
                *docker_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            effective_timeout = float(timeout) if timeout is not None else 300.0
        else:
            if os.name == "nt" and requested_shell != "cmd":
                args = self._host_shell_argv(requested_shell, command)
                if not args:
                    self.last_exit_code = -1
                    yield f"[EXECUTION_ERROR]: Requested shell '{requested_shell}' is not installed."
                    return
                process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=target_dir,
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL if background else asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL if background else asyncio.subprocess.STDOUT,
                    **self._process_group_kwargs(detached=background),
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    cwd=target_dir,
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL if background else asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL if background else asyncio.subprocess.STDOUT,
                    **self._process_group_kwargs(detached=background),
                )

        if background:
            # Docker's detached mode prints the container id and exits; host
            # processes return immediately with their OS pid.  In both cases
            # this stream owns no foreground child and therefore must not
            # enter the normal timeout/cleanup path below.
            if self.tier == SandboxTier.DOCKER:
                launch_output = await process.stdout.read() if process.stdout is not None else b""
                launch_code = await process.wait()
                self.last_exit_code = 0 if launch_code == 0 else launch_code
                if launch_code:
                    text = launch_output.decode("utf-8", errors="replace") if launch_output else ""
                    yield f"[EXECUTION_ERROR]: Background launch failed with code {launch_code}. {text}".strip()
                else:
                    identifier = launch_output.decode("utf-8", errors="replace").strip()
                    self.last_exit_code = None
                    yield f"[BACKGROUND_STARTED]: Container detached successfully (id={identifier})."
            else:
                self.last_exit_code = None
                identifier = str(getattr(process, "pid", "unknown"))
                yield f"[BACKGROUND_STARTED]: Process detached successfully (id={identifier})."
            return

        assert process.stdout is not None

        async def _stop_process() -> None:
            """Best-effort kill and reap for timeout/cancellation cleanup."""
            if process.returncode is None:
                tree_stopped = False
                pid = getattr(process, "pid", None)
                if pid:
                    try:
                        if os.name == "nt":
                            killer = await asyncio.create_subprocess_exec(
                                "taskkill", "/PID", str(pid), "/T", "/F",
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                            )
                            await asyncio.wait_for(killer.wait(), timeout=5.0)
                            tree_stopped = killer.returncode == 0
                        else:
                            os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
                            tree_stopped = True
                    except (asyncio.TimeoutError, OSError, ProcessLookupError):
                        logger.debug("Sandbox process-tree termination unavailable", exc_info=True)
                if not tree_stopped:
                    try:
                        process.kill()
                    except (ProcessLookupError, OSError):
                        pass
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except (asyncio.TimeoutError, ProcessLookupError, OSError):
                    logger.warning("Sandbox child did not exit after termination request")

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
            await _stop_process()
            self.last_exit_code = -1
            yield f"\n[SANDBOX_TIMEOUT]: Execution exceeded {int(effective_timeout)} seconds."
        finally:
            # ``aclose()`` injects GeneratorExit and ``_run_tool`` also closes
            # this generator on cooperative cancellation.  The old code only
            # reaped timeout paths, leaving a child alive when the consumer
            # cancelled during ``stdout.read``.
            if process.returncode is None:
                await _stop_process()

    def _execute_direct(self, command: str, workdir: str, shell: str = "cmd") -> str:
        """Direct execution without isolation (Default)."""
        try:
            if os.name == "nt" and shell != "cmd":
                args = self._host_shell_argv(shell, command)
                if not args:
                    return f"[EXECUTION_ERROR]: Requested shell '{shell}' is not installed."
                use_shell = False
            else:
                args = command if os.name == "nt" else ["sh", "-c", command]
                use_shell = os.name == "nt"
            process = subprocess.run(
                args,
                shell=use_shell,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=600
            )
            self.last_exit_code = process.returncode
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except subprocess.TimeoutExpired:
            self.last_exit_code = -1
            return "[SANDBOX_TIMEOUT]: Direct execution exceeded safety limit."
        except Exception as e:
            self.last_exit_code = -1
            return f"[EXECUTION_ERROR]: {str(e)}"

    def _execute_restricted(self, command: str, workdir: str, shell: str = "cmd") -> str:
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
            if os.name == "nt" and shell != "cmd":
                args = self._host_shell_argv(shell, command)
                if not args:
                    return f"[EXECUTION_ERROR]: Requested shell '{shell}' is not installed."
                use_shell = False
            else:
                args = command if os.name == "nt" else ["sh", "-c", command]
                use_shell = os.name == "nt"
            process = subprocess.run(
                args,
                shell=use_shell,
                cwd=workdir,
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=300
            )
            self.last_exit_code = process.returncode
            output = process.stdout
            if process.stderr:
                output += f"\n[STDERR]: {process.stderr}"
            return output
        except subprocess.TimeoutExpired:
            self.last_exit_code = -1
            return "[SANDBOX_TIMEOUT]: Restricted execution exceeded safety limit."
        except Exception as e:
            self.last_exit_code = -1
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

    def _execute_docker(self, command: str, workdir: str, shell: Optional[str] = None) -> str:
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
            if shell in {"cmd", "powershell", "wsl"}:
                return f"[EXECUTION_ERROR]: Requested shell '{shell}' is not available inside the Linux Docker worker; use shell='bash' or omit shell."
            docker_shell = "bash" if shell == "bash" else "sh"
            docker_cmd = [
                "docker", "run", "--rm",
                "--network=none",
                "--read-only",
                "-v", f"{self.root}:/workspace",
                "-w", container_workdir,
                "nexus-worker",
                docker_shell, "-c", command
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
