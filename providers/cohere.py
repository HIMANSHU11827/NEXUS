import json
import logging
import os
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider

logger = logging.getLogger(__name__)


class CohereProvider(NexusBaseProvider):
    """
    NEXUS COHERE PROVIDER
    Enterprise-grade RAG and search-optimized models.
    """

    def __init__(self):
        super().__init__("cohere", "https://api.cohere.ai/v1/chat")
        if not self.model:
            self.model = os.environ.get("NEXUS_PROVIDER_COHERE_MODEL", "command-r-plus")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

    @staticmethod
    def _tool_envelope(tool_calls) -> str:
        """Convert Cohere-native calls to the V5 parser format."""
        envelopes = []
        for call in tool_calls or []:
            name = str(call.get("name") or "").strip()
            if not name:
                continue
            parameters = call.get("parameters", {}) or {}
            if not isinstance(parameters, dict):
                parameters = {}
            envelopes.append(f"<function={name}>{json.dumps(parameters, ensure_ascii=False)}")
        return "\n".join(envelopes)

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        # Cohere uses a slightly different message structure for its native API
        # but Command R+ supports chat-history style
        if messages:
            chat_history = [{"role": m["role"].upper(), "message": m["content"]} for m in messages[:-1]]
            message = messages[-1]["content"]
        else:
            chat_history = [{"role": "SYSTEM", "message": system_prompt}]
            message = prompt

        payload = {
            "model": self.model,
            "message": message,
            "chat_history": chat_history,
            "preamble": system_prompt
        }
        # NOTE: Cohere /v1/chat takes native parameter_definitions tool schemas,
        # NOT OpenAI-style tools — forwarding raw OpenAI tools would 422, so the
        # request payload is left untouched. Response-side tool_calls are parsed below.
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=self.request_timeout(kwargs, 30))
            if response.status_code == 200:
                data = response.json()
                native_tools = (data.get("message", {}) or {}).get("tool_calls") or []
                if native_tools:
                    return self._tool_envelope(native_tools)
                return data.get("text", "")
            result = f"Error: Cohere API returned {response.status_code}. {response.text}"
            logging.error(result)
            return result
        except Exception as e:
            return f"Error: Failed to reach Cohere. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        response = None
        if messages:
            chat_history = [{"role": m["role"].upper(), "message": m["content"]} for m in messages[:-1]]
            message = messages[-1]["content"]
        else:
            chat_history = [{"role": "SYSTEM", "message": system_prompt}]
            message = prompt

        payload = {
            "model": self.model,
            "message": message,
            "chat_history": chat_history,
            "preamble": system_prompt,
            "stream": True
        }
        try:
            # Cohere streaming endpoint is the same but with stream=True
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 30))
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                            if chunk.get("event_type") == "text-generation":
                                yield chunk.get("text", "")
                        except json.JSONDecodeError: continue
            else:
                yield f"Error: {response.status_code}. {response.text}"
        except Exception as e:
            yield f"Error in Cohere stream: {str(e)}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.debug("Cohere stream response cleanup failed", exc_info=True)
