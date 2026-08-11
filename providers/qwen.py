import json
import logging
import os
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider

logger = logging.getLogger("NEXUS_QWEN")


class QwenProvider(NexusBaseProvider):
    """
    NEXUS DASH-SCOPE PROVIDER (ALIBABA QWEN)
    Native driver for high-performance Qwen models.
    """

    def __init__(self):
        super().__init__("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        if not self.model:
            self.model = os.environ.get("NEXUS_PROVIDER_QWEN_MODEL", "qwen-turbo")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        target_model = kwargs.get("model") or self.model
        payload = {"model": target_model, "messages": msgs}
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=self.request_timeout(kwargs, 30))
            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0].get("message", {})
                native_tools = message.get("tool_calls") or []
                if native_tools:
                    return self._tool_envelope(native_tools)
                return message.get("content") or ""
            result = f"Error: Qwen API returned {response.status_code}: {response.text}"
            return result
        except Exception as e:
            return f"Error: Failed to reach Qwen. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        response = None
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        target_model = kwargs.get("model") or self.model
        payload = {"model": target_model, "messages": msgs, "stream": True}
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 30))
            if response.status_code == 200:
                streamed_tool_calls = {}
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode('utf-8').strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0]["delta"]
                                for tool_call in delta.get("tool_calls", []) or []:
                                    index = tool_call.get("index", 0)
                                    current = streamed_tool_calls.setdefault(index, {
                                        "function": {"name": "", "arguments": ""}
                                    })
                                    function = tool_call.get("function", {}) or {}
                                    current["function"]["name"] += str(function.get("name") or "")
                                    current["function"]["arguments"] += str(function.get("arguments") or "")
                                content = delta.get("content", "")
                                if content: yield content
                            except Exception as e:
                                logger.warning(f"Qwen stream parse error: {e}")
                if streamed_tool_calls:
                    yield self._tool_envelope(list(streamed_tool_calls.values()))
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in Qwen stream: {e}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.debug("Qwen stream response cleanup failed", exc_info=True)


