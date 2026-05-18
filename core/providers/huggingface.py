from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider
import json

class HuggingFaceProvider(NexusBaseProvider):
    """
    NEXUS MODEL HUB PROVIDER (HUGGING FACE)
    Accesses the world's largest repository of 
    open-source AI models and inference APIs.
    """
    
    def __init__(self):
        super().__init__("huggingface", "https://api-inference.huggingface.co/models")
        if not self.model:
            self.model = "google/gemma-2-9b-it"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        # HuggingFace Inference API usually expects a single string for 'inputs' 
        # but modern models support ChatML/messages too if handled by the hub
        target_url = f"{self.endpoint}/{self.model}"
        payload = {"inputs": f"{system_prompt}\n\n{prompt}"}
        try:
            response = self.session.post(target_url, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    return result[0].get("generated_text", "")
                return str(result)
            return f"Error: HuggingFace returned {response.status_code}. {response.text}"
        except Exception as e:
            return f"Error: Failed to reach HuggingFace hub. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        # HuggingFace Inference API doesn't support easy streaming via requests easily 
        # without specialized clients. We yield the full result for consistency.
        yield self.generate(prompt, system_prompt, messages)
