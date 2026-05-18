import json
import logging
from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider

class CohereProvider(NexusBaseProvider):
    """
    NEXUS COHERE PROVIDER
    Enterprise-grade RAG and search-optimized models.
    """
    
    def __init__(self):
        super().__init__("cohere", "https://api.cohere.ai/v1/chat")
        if not self.model:
            self.model = "command-r-plus"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        # Cohere uses a slightly different message structure for its native API
        # but Command R+ supports chat-history style
        if messages:
            chat_history = [{"role": m["role"].upper(), "message": m["content"]} for m in messages[:-1]]
            message = messages[-1]["content"]
        else:
            chat_history = [{"role": "SYSTEM", "message": system_prompt}]
            message = prompt
            
        payload = {
            "model": self.model,
            "message": message,
            "chat_history": chat_history,
            "preamble": system_prompt
        }
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get("text", "")
            result = f"Error: Cohere API returned {response.status_code}. {response.text}"
            logging.error(result)
            return result
        except Exception as e:
            return f"Error: Failed to reach Cohere. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        if messages:
            chat_history = [{"role": m["role"].upper(), "message": m["content"]} for m in messages[:-1]]
            message = messages[-1]["content"]
        else:
            chat_history = [{"role": "SYSTEM", "message": system_prompt}]
            message = prompt
            
        payload = {
            "model": self.model,
            "message": message,
            "chat_history": chat_history,
            "preamble": system_prompt,
            "stream": True
        }
        try:
            # Cohere streaming endpoint is the same but with stream=True
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=30)
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line.decode("utf-8"))
                            if chunk.get("event_type") == "text-generation":
                                yield chunk.get("text", "")
                        except json.JSONDecodeError: continue
            else:
                yield f"Error: {response.status_code}. {response.text}"
        except Exception as e:
            yield f"Error in Cohere stream: {str(e)}"
