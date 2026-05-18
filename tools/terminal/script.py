import subprocess
import os
import time
from typing import Optional, List, Any
from core.nexus_compat import s, islice, itail  # type: ignore


class TerminalTool:
    """
    NEXUS TERMINAL DRIVER 2.0
    - Sync execute with timeout (stdin=DEVNULL, no hangs)
    - Background spawn/poll/kill
    - Interactive mode (sends stdin inputs for y/n prompts)
    - Streaming live output mode
    - Windows + Unix compatible
    """
    def __init__(self, root_dir: Optional[str] = None) -> None:
        if root_dir is None:
            _proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            root_dir = os.path.join(_proj, "workspace")
        self.root = os.path.abspath(root_dir)
        os.makedirs(self.root, exist_ok=True)
        self.background_procs: dict = {}
        self.env_info: dict = {} # Lazy load on demand

    def get_env_info(self) -> dict:
        """Collect hardware and system metadata."""
        import platform
        return {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cwd": self.root,
            "shell": os.environ.get("SHELL", "cmd.exe" if os.name == "nt" else "bash")
        }

    # ── Background spawn / poll / kill ─────────────────────────────────────────
    def spawn(self, cmd: str, pid: str) -> str:
        try:
            proc = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True, cwd=self.root
            )
            self.background_procs[pid] = proc
            return f"[SPAWN_SUCCESS]: PID '{pid}' started (OS PID={proc.pid})."
        except Exception as e:
            return f"[SPAWN_ERROR]: {str(e)}"

    def poll(self, pid: str) -> str:
        if pid not in self.background_procs:
            return f"[POLL_ERROR]: PID '{pid}' not found."
        proc = self.background_procs[pid]
        ret = proc.poll()
        if ret is None:
            try:
                out_lines: List[str] = []
                while True:
                    raw_line: Any = proc.stdout.readline()  # type: ignore[union-attr]
                    line = str(raw_line)
                    if not line:
                        break
                    out_lines.append(line.rstrip())
                n = len(out_lines)
                start = n - 20 if n > 20 else 0
                recent_lines = islice(out_lines, start, n)
                partial = "\n".join(recent_lines)
                if partial:
                    return f"[POLL_RUNNING]: PID '{pid}' active.\n{partial}"
                return f"[POLL_RUNNING]: PID '{pid}' active, no new output."
            except Exception:
                return f"[POLL_RUNNING]: PID '{pid}' is still active."
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = "", ""
        self.background_procs.pop(pid, None)
        out_str: str = s(str(out).strip(), 3000)
        err_str: str = s(str(err).strip(), 500)
        combined = out_str + ("\nSTDERR: " + err_str if err_str else "")
        return f"[POLL_DONE (code={ret})]: {combined}"

    def kill(self, pid: str) -> str:
        if pid not in self.background_procs:
            return f"[KILL_ERROR]: PID '{pid}' not found."
        proc = self.background_procs.pop(pid)
        proc.kill()
        return f"[KILL_OK]: PID '{pid}' terminated."

    # ── Sync execute ────────────────────────────────────────────────────────────
    def execute(self, cmd: str, timeout: int = 60) -> str:
        try:
            process = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True, cwd=self.root
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                partial: str = s(str(stdout), 1000)
                return f"[TIMEOUT after {timeout}s]: Partial output:\n{partial}"

            output: str = str(stdout).strip()
            err: str = str(stderr).strip()

            if process.returncode != 0:
                out_s: str = s(output, 3000)
                err_s: str = s(err, 500)
                combined = out_s + ("\n[STDERR]: " + err_s if err_s else "")
                return f"[ERROR code={process.returncode}]: {combined}"

            if output:
                return s(output, 5000)
            if err:
                return "[OK, stderr]: " + s(err, 500)
            return "[OK]"
        except Exception as e:
            # Smart retry for transient path issues
            if "not found" in str(e).lower() and "/" in cmd:
                new_cmd = cmd.replace("/", "\\") if os.name == "nt" else cmd.replace("\\", "/")
                return self.execute(new_cmd, timeout)
            return f"[FAILURE]: {str(e)}"

    # ── Interactive mode ─────────────────────────────────────────────────────────
    def execute_interactive(self, cmd: str, inputs: List[str], timeout: int = 30) -> str:
        try:
            stdin_data = "\n".join(inputs) + "\n"
            process = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True, cwd=self.root
            )
            try:
                stdout, stderr = process.communicate(input=stdin_data, timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                partial: str = s(str(stdout), 1000)
                return f"[INTERACTIVE_TIMEOUT]: Partial output:\n{partial}"

            output: str = s(str(stdout).strip(), 5000)
            err: str = str(stderr).strip()
            return output + ("\n[STDERR]: " + s(err, 500) if err else "")
        except Exception as e:
            return f"[INTERACTIVE_FAILURE]: {str(e)}"

    # ── Streaming mode ─────────────────────────────────────────────────────────
    def execute_stream(self, cmd: str, timeout: int = 120) -> str:
        try:
            process = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True, cwd=self.root, bufsize=1
            )
            lines: List[str] = []
            start = time.time()
            for raw in iter(process.stdout.readline, ""):  # type: ignore[union-attr]
                line = str(raw)
                print(f"\033[0;36m[TERM] {line}\033[0m", end="", flush=True)
                lines.append(line)
                if time.time() - start > timeout:
                    process.kill()
                    tail_lines = itail(lines, 20)
                    captured = "".join(tail_lines)
                    return f"[STREAM_TIMEOUT]: {s(captured, 3000)}"
            process.wait()
            all_output: Any = lines
            return s("".join(all_output), 5000)
        except Exception as e:
            return f"[STREAM_FAILURE]: {str(e)}"
