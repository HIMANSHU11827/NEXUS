import json
import logging
import os
import shutil
import subprocess
import time
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider

logger = logging.getLogger("NEXUS_COMMANDCODE")

DEFAULT_ENDPOINT = "https://api.commandcode.ai/provider/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("NEXUS_PROVIDER_COMMANDCODE_MODEL", "deepseek/deepseek-v4-flash")


def _find_cmd() -> Optional[str]:
    explicit = os.environ.get("COMMANDCODE_CLI_PATH", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    for candidate in [
        os.path.expandvars(r"%APPDATA%\npm\cmd.cmd"),
        os.path.expandvars(r"%APPDATA%\npm\cmd"),
    ]:
        if candidate and os.path.isfile(candidate):
            return candidate
    for candidate in [shutil.which("cmd.cmd"), shutil.which("cmd")]:
        if candidate and os.path.isfile(candidate) and (
            "npm" in candidate.lower() or "roaming" in candidate.lower()
        ):
            return candidate
    return None


class CommandCodeProvider(NexusBaseProvider):
    """Command Code cloud API (OpenAI-compatible) with optional local CLI fallback."""

    def __init__(self):
        super().__init__("commandcode", DEFAULT_ENDPOINT)
        if not self.model:
            self.model = DEFAULT_MODEL
        if not self.endpoint:
            self.endpoint = DEFAULT_ENDPOINT
        self._cmd_path = _find_cmd()
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _use_http_api(self) -> bool:
        return self.validate_api_key() and bool(self.endpoint)

    @staticmethod
    def _tool_envelope(tool_calls) -> str:
        """Convert OpenAI-compatible native calls to the V5 parser format."""
        envelopes = []
        for call in tool_calls or []:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            envelopes.append(f"<function={name}>{json.dumps(arguments, ensure_ascii=False)}")
        return "\n".join(envelopes)

    @staticmethod
    def _add_tool_payload(payload: dict, kwargs: dict) -> None:
        """Preserve model-selected native tool calling when requested."""
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            payload["tool_choice"] = kwargs["tool_choice"]

    def _build_prompt(self, prompt: str, system_prompt: str,
                      messages: Optional[List[Dict[str, str]]] = None) -> str:
        parts: List[str] = []
        if system_prompt:
            parts.append(f"[SYSTEM]\n{system_prompt}\n[/SYSTEM]")
        if messages:
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                parts.append(f"[{role.upper()}]\n{content}\n[/{role.upper()}]")
        elif prompt:
            parts.append(prompt)
        return "\n\n".join(parts)

    def _invoke_cmd(self, prompt: str, **kwargs) -> str:
        if not self._cmd_path:
            return "Error: Command Code CLI not found. Install with `npm i -g command-code`."
        timeout = int(kwargs.get("timeout", 120))
        try:
            result = subprocess.run(
                [self._cmd_path, "-p", "--skip-onboarding"],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env={**os.environ, "PYTHONHOME": ""},
            )
            output = (result.stdout or "").strip()
            if result.returncode != 0:
                err = (result.stderr or "").strip() or f"exit code {result.returncode}"
                logger.error("Command Code CLI error: %s", err)
                return f"Error: Command Code CLI failed: {err}"
            return output or "Error: Command Code returned empty response."
        except subprocess.TimeoutExpired:
            return f"Error: Command Code CLI timed out after {timeout}s."
        except FileNotFoundError:
            return "Error: Command Code CLI executable not found."
        except Exception as e:
            return f"Error: Failed to invoke Command Code CLI: {str(e)}"

    def validate_api_key(self) -> bool:
        key = (self.api_key or os.environ.get("COMMANDCODE_API_KEY", "")).strip()
        if key and "YOUR_" not in key and not key.startswith("sk-test"):
            return True
        return self._cmd_path is not None

    def generate(self, prompt: str = '', system_prompt: str = "",
                 messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        if self._use_http_api():
            msgs = self._prepare_messages(prompt, system_prompt, messages)
            model_name = kwargs.get("model") or self.model or DEFAULT_MODEL
            timeout = int(kwargs.get("timeout") or os.getenv("NEXUS_PROVIDER_TIMEOUT", "120"))
            payload = {"model": model_name, "messages": msgs}
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            self._add_tool_payload(payload, kwargs)
            try:
                response = self.session.post(
                    self.endpoint, json=payload, headers=self.headers, timeout=timeout
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("choices"):
                        message = data["choices"][0].get("message", {})
                        native_tools = message.get("tool_calls") or []
                        if native_tools:
                            return self._tool_envelope(native_tools)
                        return message.get("content") or ""
                    return f"Error: Command Code API returned unexpected payload: {data}"
                return (
                    f"Error: Command Code API returned {response.status_code}. "
                    f"{response.text[:500]}"
                )
            except Exception as e:
                return f"Error: Failed to reach Command Code API. {str(e)}"

        full = self._build_prompt(prompt, system_prompt, messages)
        return self._invoke_cmd(full, **kwargs)

    def stream_generate(self, prompt: str = '', system_prompt: str = "",
                        messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        if self._use_http_api():
            msgs = self._prepare_messages(prompt, system_prompt, messages)
            model_name = kwargs.get("model") or self.model or DEFAULT_MODEL
            timeout = int(kwargs.get("timeout") or os.getenv("NEXUS_PROVIDER_TIMEOUT", "120"))
            deadline = time.time() + int(os.getenv("NEXUS_STREAM_DEADLINE", "120"))
            payload = {"model": model_name, "messages": msgs, "stream": True}
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            self._add_tool_payload(payload, kwargs)
            try:
                response = self.session.post(
                    self.endpoint,
                    json=payload,
                    headers=self.headers,
                    stream=True,
                    timeout=timeout,
                )
                if response.status_code != 200:
                    yield (
                        f"Error: Command Code API returned {response.status_code}. "
                        f"{response.text[:500]}"
                    )
                    return
                streamed_tool_calls = {}
                for line in response.iter_lines():
                    if time.time() >= deadline:
                        yield "\nError in stream: Command Code stream deadline exceeded"
                        return
                    if not line:
                        continue
                    decoded = line.decode("utf-8").strip()
                    if not decoded.startswith("data: "):
                        continue
                    data_str = decoded[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            for tool_call in delta.get("tool_calls", []) or []:
                                index = tool_call.get("index", 0)
                                current = streamed_tool_calls.setdefault(index, {
                                    "function": {"name": "", "arguments": ""}
                                })
                                function = tool_call.get("function", {}) or {}
                                current["function"]["name"] += str(function.get("name") or "")
                                current["function"]["arguments"] += str(function.get("arguments") or "")
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                if streamed_tool_calls:
                    yield self._tool_envelope(list(streamed_tool_calls.values()))
                return
            except Exception as e:
                yield f"\nError in Command Code stream: {str(e)}"
                return

        full = self._build_prompt(prompt, system_prompt, messages)
        if not self._cmd_path:
            yield "Error: Command Code CLI not found."
            return
        timeout = int(kwargs.get("timeout", 300))
        try:
            proc = subprocess.Popen(
                [self._cmd_path, "-p", "--skip-onboarding"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONHOME": ""},
            )
            if proc.stdin:
                proc.stdin.write(full)
                proc.stdin.close()
            for line in iter(proc.stdout.readline, ""):
                if line:
                    yield line
            proc.wait(timeout=timeout)
            if proc.returncode != 0:
                err = (proc.stderr.read() or "").strip()
                yield f"\nError: Command Code CLI failed: {err or f'exit code {proc.returncode}'}"
        except subprocess.TimeoutExpired:
            proc.kill()
            yield f"\nError: Command Code CLI timed out after {timeout}s."
        except Exception as e:
            yield f"\nError in Command Code stream: {str(e)}"


