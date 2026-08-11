import json
import logging
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider

logger = logging.getLogger(__name__)


class LMStudioProvider(NexusBaseProvider):
    """
    NEXUS LOCAL GGUF PROVIDER (LM STUDIO)
    Highly optimized for quantized model execution on local hardware.
    """
    
    def __init__(self):
        super().__init__("lm_studio", "http://localhost:1234/v1/chat/completions")
        if not self.model:
            self.model = "unknown" # LM Studio often ignores model name if only one is loaded
        self.headers = {"Content-Type": "application/json"}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    @staticmethod
    def _tool_envelope(tool_calls) -> str:
        """Preserve OpenAI-compatible native calls for Nexus's tool loop."""
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
    def _has_tools(kwargs: Dict[str, object]) -> bool:
        """Return whether the caller supplied schemas to this request."""
        return bool(kwargs.get("tools"))

    def generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": kwargs.pop("model", None) or self.model,
            "messages": msgs,
            "temperature": 0.2,
            **kwargs,
            # The method contract is authoritative even if a caller passes a
            # stale stream flag in shared provider kwargs.
            "stream": False,
        }
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                message = response.json()["choices"][0]["message"]
                native_tools = message.get("tool_calls") or []
                if native_tools:
                    return self._tool_envelope(native_tools)
                return message.get("content") or ""
            return f"Error: LM Studio returned {response.status_code}"
        except Exception as e:
            return f"Error: LM Studio not reachable. {str(e)}"

    def stream_generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        response = None
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": kwargs.pop("model", None) or self.model,
            "messages": msgs,
            "temperature": 0.2,
            **kwargs,
            "stream": True,
        }
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                streamed_tool_calls = {}
                buffered_content = []
                has_native_tools = self._has_tools(kwargs)
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices") or []
                                if not choices:
                                    continue
                                delta = choices[0].get("delta") or {}
                                tool_calls = delta.get("tool_calls") or []
                                if tool_calls:
                                    for tool_call in tool_calls:
                                        index = tool_call.get("index", 0)
                                        current = streamed_tool_calls.setdefault(index, {
                                            "function": {"name": "", "arguments": ""}
                                        })
                                        function = tool_call.get("function") or {}
                                        current["function"]["name"] += str(function.get("name") or "")
                                        current["function"]["arguments"] += str(function.get("arguments") or "")
                                content = delta.get("content") or ""
                                if content:
                                    # A tool call can arrive after ordinary
                                    # deltas. Buffer when schemas are present
                                    # so a partial assistant answer is never
                                    # emitted before a native tool invocation.
                                    if has_native_tools:
                                        buffered_content.append(content)
                                    else:
                                        yield content
                            except json.JSONDecodeError: continue
                if streamed_tool_calls:
                    ordered_calls = [
                        streamed_tool_calls[index]
                        for index in sorted(
                            streamed_tool_calls,
                            key=lambda value: (
                                0, value
                            ) if isinstance(value, (int, float)) else (1, str(value)),
                        )
                    ]
                    yield self._tool_envelope(ordered_calls)
                elif buffered_content:
                    yield "".join(buffered_content)
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in LM Studio stream: {str(e)}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.debug("LM Studio stream response cleanup failed", exc_info=True)
