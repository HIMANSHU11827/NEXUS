from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider
import json
import os
import logging

logger = logging.getLogger("NEXUS_NVIDIA")

class NvidiaProvider(NexusBaseProvider):
    """
    NEXUS NVIDIA NIM PROVIDER
    Custom driver for z-ai/glm-5.1 on NVIDIA Integrate API.
    """
    def __init__(self):
        super().__init__("nvidia", "https://integrate.api.nvidia.com/v1/chat/completions")
        self.default_model = "z-ai/glm-5.1"
        if not self.model:
            self.model = "z-ai/glm-5.1"
        if not self.api_key:
            self.api_key = os.getenv("NVIDIA_API_KEY", "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")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        model = kwargs.get("model") or self.model
        payload = {"model": model, "messages": msgs}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            result = f"Error: NVIDIA API returned {response.status_code}. {response.text}"
            logger.error(result)
            return result
        except Exception as e:
            return f"Error: Failed to reach NVIDIA NIM. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        model = kwargs.get("model") or self.model
        payload = {"model": model, "messages": msgs, "stream": True}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=120)
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    content = choices[0].get("delta", {}).get("content", "")
                                    if content: yield content
                            except json.JSONDecodeError: continue
            else:
                yield f"Error: {response.status_code}. {response.text}"
        except Exception as e:
            yield f"Error in NVIDIA NIM stream: {str(e)}"
