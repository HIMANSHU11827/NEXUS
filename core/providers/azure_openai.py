from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider
import json
import os

class AzureOpenAIProvider(NexusBaseProvider):
    """
    NEXUS ENTERPRISE BRIDGE (AZURE OPENAI)
    The Microsoft-backed cloud driver for zero-trust 
    enterprise reasoning and secured data access.
    """
    
    def __init__(self):
        super().__init__("azure_openai", "") 
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        self.headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> str:
        target_url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version=2024-02-15-preview"
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"messages": msgs}
        try:
            response = self.session.post(target_url, json=payload, headers=self.headers, timeout=30)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return f"Error: Azure OpenAI returned {response.status_code}"
        except Exception as e:
            return f"Error: Failed to reach Azure. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None) -> Iterator[str]:
        target_url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version=2024-02-15-preview"
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"messages": msgs, "stream": True}
        try:
            response = self.session.post(target_url, json=payload, headers=self.headers, stream=True, timeout=30)
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
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error: {e}"
