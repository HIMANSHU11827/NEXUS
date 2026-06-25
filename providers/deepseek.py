import json
import logging
from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider

class DeepSeekProvider(NexusBaseProvider):
    """
    NEXUS NATIVE DEEPSEEK PROVIDER
    High-performance reasoning and coding models.
    """
    
    def __init__(self):
        super().__init__("deepseek", "https://api.deepseek.com/chat/completions")
        if not self.model:
            self.model = "deepseek-chat"
        self._base_model = self.model
        self._thinking_model = "deepseek-reasoner"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def configure_thinking(self, enabled: bool):
        self.thinking = enabled
        self.model = self._thinking_model if enabled else self._base_model

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": self.model, "messages": msgs}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=60)
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
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=60)
            if response.status_code == 200:
                in_thinking = False
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                reasoning = delta.get("reasoning_content", "")
                                if reasoning:
                                    if not in_thinking:
                                        yield "<thinking>"
                                        in_thinking = True
                                    yield reasoning
                                if content:
                                    if in_thinking:
                                        yield "</thinking>"
                                        in_thinking = False
                                    yield content
                            except json.JSONDecodeError: continue
                if in_thinking:
                    yield "</thinking>"
                yield "\n\nTASK_COMPLETE"
            else:
                yield f"Error: {response.status_code}. {response.text}\n\nTASK_COMPLETE"
        except Exception as e:
            yield f"Error in DeepSeek stream: {str(e)}\n\nTASK_COMPLETE"
