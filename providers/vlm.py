import json
import os
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider


class VLMProvider(NexusBaseProvider):
    """
    NEXUS VISION-LANGUAGE PROVIDER (VLM)
    Specialized driver for multi-modal reasoning and image analysis.
    """
    
    def __init__(self):
        super().__init__("vlm", "https://api.openai.com/v1/chat/completions") # Default to OpenAI-compatible
        if not self.model:
            self.model = os.environ.get("NEXUS_PROVIDER_VLM_MODEL", "gpt-4o")

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

    @staticmethod
    def _add_tool_payload(payload: dict, kwargs: dict) -> None:
        """Preserve model-selected native tool calling when requested."""
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            payload["tool_choice"] = kwargs["tool_choice"]

    def analyze_image(self, image_path: str, prompt: str = "Describe this image.") -> str:
        """Standard interface for VLM tasks."""
        import base64
        import os
        resolved = os.path.normpath(os.path.abspath(image_path))
        if not resolved.startswith(os.path.abspath(os.curdir)) and not os.path.isabs(resolved):
            return f"Error: path traversal detected in {image_path}"
        try:
            with open(resolved, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
            return self.generate(prompt="", messages=messages)
        except Exception as e:
            return f"Error in VLM analysis: {e}"

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": self.model, "messages": msgs}
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(self.endpoint, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0].get("message", {})
                native_tools = message.get("tool_calls") or []
                if native_tools:
                    return self._tool_envelope(native_tools)
                return message.get("content") or ""
            return f"Error: VLM API returned {response.status_code}"
        except Exception as e:
            return f"Error: {e}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        # Forward tools/kwargs through; generate() handles native tool_calls.
        yield self.generate(prompt, system_prompt, messages, **kwargs)


