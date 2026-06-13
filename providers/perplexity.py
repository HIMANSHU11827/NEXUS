from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider
import json

class PerplexityProvider(NexusBaseProvider):
    """
    NEXUS SEARCH-LLM PROVIDER (PERPLEXITY.AI)
    The high-IQ search driver that understands the 
    current web as a unified knowledge graph.
    """
    
    def __init__(self):
        super().__init__("perplexity", "https://api.perplexity.ai/chat/completions")
        if not self.model:
            self.model = "llama-3.1-sonar-large-128k-online"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def generate(self, prompt: str = '', system_prompt: str = "Be precise and cite sources.", messages: Optional[List[Dict[str, str]]] = None) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": self.model, "messages": msgs}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return f"Error: Perplexity API returned {response.status_code}"
        except Exception as e:
            return f"Error: Failed to reach Perplexity. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "Be precise and cite sources.", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
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
            yield f"Error in Perplexity stream: {str(e)}"

if __name__ == "__main__":
    p = PerplexityProvider()
    # print(p.generate("What is the latest AI breakthrough today?"))
