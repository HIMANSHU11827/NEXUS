from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider
import json

class QwenProvider(NexusBaseProvider):
    """
    NEXUS DASH-SCOPE PROVIDER (ALIBABA QWEN)
    Native driver for high-performance Qwen models.
    """

    def __init__(self):
        super().__init__("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        if not self.model:
            self.model = "qwen-turbo"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        target_model = kwargs.get("model") or self.model
        payload = {"model": target_model, "messages": msgs}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            result = f"Error: Qwen API returned {response.status_code}: {response.text}"
            return result
        except Exception as e:
            return f"Error: Failed to reach Qwen. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        target_model = kwargs.get("model") or self.model
        payload = {"model": target_model, "messages": msgs, "stream": True}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=30)
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode('utf-8').strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                content = chunk["choices"][0]["delta"].get("content", "")
                                if content: yield content
                            except Exception: pass
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in Qwen stream: {e}"
