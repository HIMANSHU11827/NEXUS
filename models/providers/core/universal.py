import json
import logging
from typing import Dict, Iterator, List, Optional

from models.providers.core.base import NexusBaseProvider

logger = logging.getLogger("NEXUS_UNIVERSAL")

class UniversalProvider(NexusBaseProvider):
    """
    NEXUS UNIVERSAL PROVIDER (OpenAI Compatible)
    Connects to ANY OpenAI-compatible endpoint (vLLM, TGI, Ollama, LM Studio, Private APIs).
    """

    def __init__(self):
        # Default to a placeholder, will be overridden by config
        super().__init__("universal", "http://localhost:8000/v1/chat/completions")

        # Ensure headers are set up correctly with the API key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
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
            arguments = NexusBaseProvider.normalize_tool_arguments(
                function.get("arguments", {}), tool_name=name
            )
            envelopes.append(f"<function={name}>{json.dumps(arguments, ensure_ascii=False)}")
        return "\n".join(envelopes)

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            **kwargs
        }
        try:
            # Re-apply headers in case API key was updated after init
            self.headers["Authorization"] = f"Bearer {self.api_key}"

            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=kwargs.get("timeout", 60))
            if response.status_code == 200:
                data = response.json()
                # Handle standard OpenAI format
                if "choices" in data:
                    message = data["choices"][0].get("message", {})
                    native_tools = message.get("tool_calls") or []
                    if native_tools:
                        return self._tool_envelope(native_tools)
                    return message.get("content") or ""
                # Handle common alternative formats
                if "content" in data:
                    return data["content"]
                return f"Error: Unexpected response format from {self.endpoint}: {data}"

            result = f"Error: Universal API ({self.endpoint}) returned {response.status_code}. {response.text}"
            logger.error(result)
            return result
        except Exception as e:
            return f"Error: Failed to reach Universal Endpoint {self.endpoint}. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        response = None
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": True,
            **kwargs
        }
        try:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 120))

            if response.status_code == 200:
                streamed_tool_calls = {}
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                if "choices" in chunk:
                                    delta = chunk["choices"][0].get("delta", {})
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
                            except json.JSONDecodeError: continue
                if streamed_tool_calls:
                    yield self._tool_envelope(list(streamed_tool_calls.values()))
            else:
                yield f"Error: {response.status_code}. {response.text}"
        except Exception as e:
            yield f"Error in Universal stream: {str(e)}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.debug("Universal stream response cleanup failed", exc_info=True)
