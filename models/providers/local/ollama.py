import json
import logging
import os
from typing import Dict, Iterator, List, Optional

from models.providers.core.base import NexusBaseProvider

logger = logging.getLogger(__name__)


class OllamaProvider(NexusBaseProvider):
    """
    NEXUS LOCAL PROVIDER (OLLAMA)
    The primary driver for high-privacy, local-only 
    model execution on edge hardware.
    """
    
    def __init__(self):
        super().__init__("ollama", "http://localhost:11434/api/chat")
        if not self.model:
            self.model = os.environ.get("NEXUS_PROVIDER_OLLAMA_MODEL", "llama3")
            
    @staticmethod
    def _tool_envelope(tool_calls) -> str:
        """Convert Ollama-native calls to the V5 parser format."""
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

    @staticmethod
    def _add_tool_payload(payload: dict, kwargs: dict) -> None:
        """Preserve native Ollama tool calling when requested."""
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": False
        }
        self._add_tool_payload(payload, kwargs)
        response = None
        try:
            response = self.session.post(self.endpoint, json=payload, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                data = response.json()
                message = data.get("message", {})
                native_tools = message.get("tool_calls") or []
                if native_tools:
                    return self._tool_envelope(native_tools)
                return message.get("content", "")
            return f"Error: Local Ollama returned {response.status_code}"
        except Exception as e:
            return f"Error: Local Ollama not reachable. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": True
        }
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(self.endpoint, json=payload, stream=True, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                # Ollama streams full tool_call objects per chunk (index-keyed).
                streamed_tool_calls = {}
                for line in response.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                            for tool_call in chunk.get("message", {}).get("tool_calls", []) or []:
                                index = tool_call.get("index", len(streamed_tool_calls))
                                streamed_tool_calls[index] = tool_call
                            content = chunk.get("message", {}).get("content", "")
                            if content: yield content
                            if chunk.get("done"): break
                        except json.JSONDecodeError: continue
                if streamed_tool_calls:
                    yield self._tool_envelope(list(streamed_tool_calls.values()))
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in Ollama stream: {str(e)}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.debug("Ollama stream response cleanup failed", exc_info=True)


if __name__ == "__main__":
    p = OllamaProvider()
    print(f"Connecting to [{p.model}] on {p.endpoint}")


