import json
import logging
from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider

class DeepSeekProvider(NexusBaseProvider):
    """
    NEXUS NATIVE DEEPSEEK PROVIDER
    High-performance reasoning and coding models.
    """
    
    def __init__(self):
        super().__init__("deepseek", "https://api.deepseek.com/chat/completions")
        if not self.model:
            self.model = "deepseek-chat"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": self.model, "messages": msgs}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            result = f"Error: DeepSeek API returned {response.status_code}. {response.text}"
            logging.error(result)
            return result
        except Exception as e:
            return f"Error: Failed to reach DeepSeek. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": self.model, "messages": msgs, "stream": True}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=30)
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                content = chunk["choices"][0].get("delta", {}).get("content", "")
                                if content: yield content
                            except json.JSONDecodeError: continue
            else:
                yield f"Error: {response.status_code}. {response.text}"
        except Exception as e:
            yield f"Error in DeepSeek stream: {str(e)}"
