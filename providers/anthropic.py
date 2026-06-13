from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider
import json

class AnthropicProvider(NexusBaseProvider):
    """
    NEXUS CLOUD PROVIDER (ANTHROPIC SONNET 3.5)
    The primary 'Elite Brain' for strategic reasoning 
    and high-end architectural coding.
    """
    
    def __init__(self):
        super().__init__("anthropic", "https://api.anthropic.com/v1/messages")
        if not self.model:
            self.model = "claude-3-5-sonnet-20240620"
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        # Anthropic separate system prompt from messages
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [m for m in msgs if m["role"] != "system"]
        }
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "content" in data and len(data["content"]) > 0:
                    return data["content"][0].get("text", "")
                return f"Error: Anthropic response missing 'content'."
            return f"Error: Anthropic API returned {response.status_code} - {response.text}"
        except Exception as e:
            return f"Error: Failed to reach Anthropic. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [m for m in msgs if m["role"] != "system"],
            "stream": True
        }
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=30)
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        decoded = line.decode('utf-8')
                        if decoded.startswith("data: "):
                            data_str = decoded[6:].strip()
                            try:
                                chunk = json.loads(data_str)
                                if chunk.get("type") == "content_block_delta":
                                    delta = chunk.get("delta", {})
                                    text = delta.get("text", "")
                                    if text: yield text
                            except Exception: continue
            else:
                yield f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            yield f"Error in Anthropic stream: {str(e)}"

if __name__ == "__main__":
    p = AnthropicProvider()
    # print(p.generate("Tell me your name."))
