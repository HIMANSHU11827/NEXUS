from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider
import json
import time

class ReplicateProvider(NexusBaseProvider):
    """
    NEXUS REPLICATE PROVIDER
    The modular cloud driver for diverse architectural models.
    """
    
    def __init__(self):
        super().__init__("replicate", "https://api.replicate.com/v1/predictions")
        if not self.model:
            self.model = "meta/meta-llama-3.1-405b-instruct"
        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        # Replicate usually takes an 'input' dict
        # We need to map the model string to a version hash or use the deployment ID
        # For simplicity, we assume model string is the full path
        payload = {
            "version": self.model.split(":")[-1] if ":" in self.model else self.model,
            "input": {
                "prompt": prompt,
                "system_prompt": system_prompt
            }
        }
        
        # If it's a version path
        if "/" in self.model and ":" not in self.model:
             # We might need to fetch the latest version but for this project we assume version is provided
             pass

        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 201:
                prediction = response.json()
                poll_url = prediction["urls"]["get"]
                
                # Simple polling loop
                for _ in range(60):
                    res = self.session.get(poll_url, headers=self.headers)
                    data = res.json()
                    if data["status"] == "succeeded":
                        output = data["output"]
                        return "".join(output) if isinstance(output, list) else str(output)
                    if data["status"] == "failed":
                        return f"Error: Replicate prediction failed: {data.get('error')}"
                    time.sleep(1)
                return "Error: Replicate prediction timed out."
            return f"Error: Replicate API returned {response.status_code}. {response.text}"
        except Exception as e:
            return f"Error: Failed to reach Replicate. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        # Replicate streaming is a bit complex via HTTP, usually uses Server-Sent Events on a specific URL
        # For now, we'll yield the full result to maintain compatibility
        yield self.generate(prompt, system_prompt, messages)
