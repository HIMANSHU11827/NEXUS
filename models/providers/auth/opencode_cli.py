import os
import re
import shutil
import subprocess
from typing import Dict, Iterator, List, Optional

from models.providers.core.base import NexusBaseProvider

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _find_opencode() -> Optional[str]:
    explicit = os.environ.get("OPENCODE_CLI_PATH", "").strip()
    candidates = [
        explicit,
        os.path.expandvars(r"%APPDATA%\npm\opencode.cmd"),
        shutil.which("opencode.cmd"),
        shutil.which("opencode"),
    ]
    return next((path for path in candidates if path and os.path.isfile(path)), None)


class OpenCodeCLIProvider(NexusBaseProvider):
    """Authenticated local OpenCode CLI fallback, isolated in read-only plan mode."""

    def __init__(self):
        super().__init__("opencode", "")
        self._cli_path = _find_opencode()
        self.model = self.model or "opencode/free"

    def validate_api_key(self) -> bool:
        return self._cli_path is not None

    @staticmethod
    def _build_prompt(prompt: str, system_prompt: str,
                      messages: Optional[List[Dict[str, str]]]) -> str:
        parts = []
        if system_prompt:
            parts.append(f"[SYSTEM]\n{system_prompt[:6000]}")
        if messages:
            for message in messages[-8:]:
                role = str(message.get("role", "user")).upper()
                content = str(message.get("content", ""))
                parts.append(f"[{role}]\n{content[:6000]}")
        elif prompt:
            parts.append(f"[USER]\n{prompt[:12000]}")
        return "\n\n".join(parts)[-24000:]

    @staticmethod
    def _clean_output(output: str) -> str:
        clean = _ANSI_RE.sub("", output or "").strip()
        # OpenCode has emitted both a correctly decoded middle dot and the
        # historical mojibake form in its terminal footer. Match the stable
        # footer prefix instead of depending on the separator encoding.
        lines = [line for line in clean.splitlines() if not line.strip().startswith("> plan ")]
        return "\n".join(lines).strip()

    def generate(self, prompt: str = "", system_prompt: str = "",
                 messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        if not self._cli_path:
            return "Error: OpenCode CLI is not installed."
        full_prompt = self._build_prompt(prompt, system_prompt, messages)
        timeout = self.request_timeout(
            kwargs, float(os.environ.get("NEXUS_OPENCODE_TIMEOUT", "180"))
        )
        process = None
        try:
            process = subprocess.Popen(
                [self._cli_path, "run", "--agent", "plan", "--pure", full_prompt],
                cwd=os.getcwd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=os.environ.copy(),
                **self.process_group_kwargs(),
            )
            stdout, stderr = process.communicate(timeout=timeout)
            output = self._clean_output(stdout)
            if process.returncode != 0:
                error = self._clean_output(stderr) or f"exit code {process.returncode}"
                return f"Error: OpenCode CLI failed: {error}"
            return output or "Error: OpenCode CLI returned an empty response."
        except subprocess.TimeoutExpired:
            self.terminate_process_tree(process)
            return f"Error: OpenCode CLI timed out after {timeout:g}s."
        except Exception as exc:
            return f"Error: OpenCode CLI failed: {exc}"
        finally:
            if process is not None and process.poll() is None:
                self.terminate_process_tree(process)

    def stream_generate(self, prompt: str = "", system_prompt: str = "",
                        messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        result = self.generate(prompt, system_prompt, messages, **kwargs)
        for index in range(0, len(result), 64):
            yield result[index:index + 64]
