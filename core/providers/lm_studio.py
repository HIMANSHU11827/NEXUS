from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider
import json

class LMStudioProvider(NexusBaseProvider):
    """
    NEXUS LOCAL GGUF PROVIDER (LM STUDIO)
    Highly optimized for quantized model execution on local hardware.
    """
    
    def __init__(self):
        super().__init__("lm_studio", "http://localhost:1234/v1/chat/completions")
        if not self.model:
            self.model = "unknown" # LM Studio often ignores model name if only one is loaded

    def generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            "temperature": 0.2,
            "stream": False,
            **kwargs,
        }
        try:
            response = self.session.post(self.endpoint, json=payload, timeout=60)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return f"Error: LM Studio returned {response.status_code}"
        except Exception as e:
            return f"Error: LM Studio not reachable. {str(e)}"

    def stream_generate(self, prompt: str = "", system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            "temperature": 0.2,
            "stream": True,
            **kwargs,
        }
        try:
            response = self.session.post(self.endpoint, json=payload, stream=True, timeout=60)
            if response.status_code == 200:
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
                                content = delta.get("content") or ""
                                if content: yield content
                            except json.JSONDecodeError: continue
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in LM Studio stream: {str(e)}"
