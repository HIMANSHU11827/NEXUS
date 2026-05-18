from typing import Dict, Any, Optional, List, Iterator
import json
import logging
from core.providers.base import NexusBaseProvider

logger = logging.getLogger("NEXUS_UNIVERSAL")

class UniversalProvider(NexusBaseProvider):
    """
    NEXUS UNIVERSAL PROVIDER (OpenAI Compatible)
    Connects to ANY OpenAI-compatible endpoint (vLLM, TGI, Ollama, LM Studio, Private APIs).
    """
    
    def __init__(self):
        # Default to a placeholder, will be overridden by config
        super().__init__("universal", "http://localhost:8000/v1/chat/completions")
        
        # Ensure headers are set up correctly with the API key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model, 
            "messages": msgs,
            **kwargs
        }
        try:
            # Re-apply headers in case API key was updated after init
            self.headers["Authorization"] = f"Bearer {self.api_key}"
            
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=kwargs.get("timeout", 60))
            if response.status_code == 200:
                data = response.json()
                # Handle standard OpenAI format
                if "choices" in data:
                    return data["choices"][0]["message"]["content"]
                # Handle common alternative formats
                if "content" in data:
                    return data["content"]
                return f"Error: Unexpected response format from {self.endpoint}: {data}"
                
            result = f"Error: Universal API ({self.endpoint}) returned {response.status_code}. {response.text}"
            logger.error(result)
            return result
        except Exception as e:
            return f"Error: Failed to reach Universal Endpoint {self.endpoint}. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": self.model, 
            "messages": msgs, 
            "stream": True,
            **kwargs
        }
        try:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
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
                                if "choices" in chunk:
                                    content = chunk["choices"][0].get("delta", {}).get("content", "")
                                    if content: yield content
                            except json.JSONDecodeError: continue
            else:
                yield f"Error: {response.status_code}. {response.text}"
        except Exception as e:
            yield f"Error in Universal stream: {str(e)}"
