from typing import Dict, Any, Optional, List, Iterator
from core.providers.base import NexusBaseProvider
import json

class GoogleGeminiProvider(NexusBaseProvider):
    """
    NEXUS LARGE-CONTEXT PROVIDER (GOOGLE GEMINI 1.5 PRO)
    The primary driver for tasks requiring massive 
    context windows (1M+ tokens).
    """
    
    def __init__(self):
        super().__init__("gemini", "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent")
        # Injected key correctly via base class logic
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.api_key}"
        self.headers = {"Content-Type": "application/json"}
        
    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        contents = []
        for m in msgs:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
            
        payload = {"contents": contents}
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    cand = data["candidates"][0]
                    if "content" in cand and "parts" in cand["content"]:
                        return cand["content"]["parts"][0]["text"]
            return f"Error: Gemini API returned {response.status_code}. {response.text}"
        except Exception as e:
            return f"Error: Failed to reach Gemini. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        contents = []
        for m in msgs:
             role = "model" if m["role"] == "assistant" else "user"
             contents.append({"role": role, "parts": [{"text": m["content"]}]})
             
        payload = {"contents": contents}
        try:
            stream_url = self.endpoint.replace(":generateContent", ":streamGenerateContent")
            response = self.session.post(stream_url, json=payload, headers=self.headers, stream=True, timeout=60)
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        chunk_str = line.decode('utf-8').strip()
                        # Clean up Google's streaming array format
                        chunk_labels = ["[,", "[", ",", "]"]
                        for lbl in chunk_labels:
                            if chunk_str.startswith(lbl): chunk_str = chunk_str[len(lbl):].strip()
                            if chunk_str.endswith(lbl): chunk_str = chunk_str[:-len(lbl)].strip()
                        
                        if not chunk_str: continue
                        try:
                            chunk = json.loads(chunk_str)
                            if "candidates" in chunk:
                                cand = chunk["candidates"][0]
                                if "content" in cand and "parts" in cand["content"]:
                                    yield cand["content"]["parts"][0].get("text", "")
                        except: continue
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error in Gemini stream: {e}"
