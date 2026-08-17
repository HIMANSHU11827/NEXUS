import json
import logging
import os
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider

logger = logging.getLogger(__name__)


class GoogleGeminiProvider(NexusBaseProvider):
    """
    NEXUS LARGE-CONTEXT PROVIDER (GOOGLE GEMINI 1.5 PRO)
    The primary driver for tasks requiring massive
    context windows (1M+ tokens).
    """

    def __init__(self):
        model = os.environ.get("NEXUS_PROVIDER_GEMINI_MODEL", "gemini-1.5-pro")
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        super().__init__("gemini", endpoint)
        self.endpoint = endpoint
        # Model baked into the default endpoint at construction; a per-call
        # ``model`` kwarg must override it, so keep the raw default around.
        self._default_model = model
        self.headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    def _request_model(self, kwargs: dict) -> str:
        """Resolve the per-call model, honoring a runtime override."""
        return str(kwargs.get("model") or self.model or self._default_model)

    @staticmethod
    def _endpoint_for_model(model: str, streaming: bool = False) -> str:
        suffix = "streamGenerateContent" if streaming else "generateContent"
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:{suffix}"

    @staticmethod
    def _tools_to_gemini(tools) -> Optional[list]:
        """Convert OpenAI-style tools into Gemini functionDeclarations."""
        if not tools:
            return None
        declarations = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function", {}) or {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            declaration = {"name": name}
            description = function.get("description")
            if description:
                declaration["description"] = description
            parameters = function.get("parameters")
            if parameters:
                declaration["parameters"] = parameters
            declarations.append(declaration)
        if not declarations:
            return None
        return [{"functionDeclarations": declarations}]

    @staticmethod
    def _parse_parts(parts) -> str:
        """Emit text parts as content and functionCall parts as V5 envelopes."""
        outputs = []
        for part in parts or []:
            if not isinstance(part, dict):
                continue
            function_call = part.get("functionCall") or {}
            if function_call:
                name = str(function_call.get("name") or "").strip()
                if name:
                    args = NexusBaseProvider.normalize_tool_arguments(
                        function_call.get("args", {}), tool_name=name
                    )
                    outputs.append(f"<function={name}>{json.dumps(args, ensure_ascii=False)}")
            text = part.get("text")
            if text:
                outputs.append(str(text))
        return "\n".join(outputs)

    def _payload(self, prompt: str, system_prompt: str, messages: Optional[List[Dict[str, str]]], kwargs: dict) -> dict:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        contents = []
        for m in msgs:
            role = "model" if m["role"] == "assistant" else "user"
            parts = [{"text": m["content"]}]
            contents.append({"role": role, "parts": parts})
        payload = {"contents": contents}
        gemini_tools = self._tools_to_gemini(kwargs.get("tools"))
        if gemini_tools:
            payload["tools"] = gemini_tools
        return payload

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        payload = self._payload(prompt, system_prompt, messages, kwargs)
        model = self._request_model(kwargs)
        payload["model"] = model
        response = None
        try:
            response = self.session.post(self._endpoint_for_model(model), json=payload, headers=self.headers, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    cand = data["candidates"][0]
                    if "content" in cand and "parts" in cand["content"]:
                        return self._parse_parts(cand["content"]["parts"]) or ""
            return f"Error: Gemini API returned {response.status_code}. {response.text}"
        except Exception as e:
            return f"Error: Failed to reach Gemini. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        payload = self._payload(prompt, system_prompt, messages, kwargs)
        model = self._request_model(kwargs)
        payload["model"] = model
        try:
            stream_url = self._endpoint_for_model(model, streaming=True)
            response = self.session.post(stream_url, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        chunk_str = line.decode('utf-8').strip()
                        # Clean up Google's streaming array format
                        chunk_labels = ["[,", "[", ",", "]"]
                        for lbl in chunk_labels:
                            if chunk_str.startswith(lbl): chunk_str = chunk_str[len(lbl):].strip()
                            if chunk_str.endswith(lbl): chunk_str = chunk_str[:-len(lbl)].strip()

                        if not chunk_str: continue
                        try:
                            chunk = json.loads(chunk_str)
                            if "candidates" in chunk:
                                cand = chunk["candidates"][0]
                                if "content" in cand and "parts" in cand["content"]:
                                    part_text = self._parse_parts(cand["content"]["parts"])
                                    if part_text:
                                        yield part_text
                        except Exception: continue
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in Gemini stream: {e}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.debug("Gemini stream response cleanup failed", exc_info=True)
