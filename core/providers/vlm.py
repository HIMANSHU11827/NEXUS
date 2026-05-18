from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider
import json

class VLMProvider(NexusBaseProvider):
    """
    NEXUS VISION-LANGUAGE PROVIDER (VLM)
    Specialized driver for multi-modal reasoning and image analysis.
    """
    
    def __init__(self):
        super().__init__("vlm", "https://api.openai.com/v1/chat/completions") # Default to OpenAI-compatible
        if not self.model:
            self.model = "gpt-4o"

    def analyze_image(self, image_path: str, prompt: str = "Describe this image.") -> str:
        """Standard interface for VLM tasks."""
        import base64
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
            return self.generate(prompt="", messages=messages)
        except Exception as e:
            return f"Error in VLM analysis: {e}"

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": self.model, "messages": msgs}
        try:
            response = self.session.post(self.endpoint, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=60)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return f"Error: VLM API returned {response.status_code}"
        except Exception as e:
            return f"Error: {e}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        # Basic implementation
        yield self.generate(prompt, system_prompt, messages)
