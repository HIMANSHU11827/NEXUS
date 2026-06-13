from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider
import json

class OllamaProvider(NexusBaseProvider):
    """
    NEXUS LOCAL PROVIDER (OLLAMA)
    The primary driver for high-privacy, local-only 
    model execution on edge hardware.
    """
    
    def __init__(self):
        super().__init__("ollama", "http://localhost:11434/api/chat")
        if not self.model:
            self.model = "llama3"
            
    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": False
        }
        try:
            response = self.session.post(self.endpoint, json=payload, timeout=60)
            if response.status_code == 200:
                return response.json().get("message", {}).get("content", "")
            return f"Error: Local Ollama returned {response.status_code}"
        except Exception as e:
            return f"Error: Local Ollama not reachable. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model,
            "messages": msgs,
            "stream": True
        }
        try:
            response = self.session.post(self.endpoint, json=payload, stream=True, timeout=60)
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                            content = chunk.get("message", {}).get("content", "")
                            if content: yield content
                            if chunk.get("done"): break
                        except json.JSONDecodeError: continue
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in Ollama stream: {str(e)}"


if __name__ == "__main__":
    p = OllamaProvider()
    print(f"Connecting to [{p.model}] on {p.endpoint}")
