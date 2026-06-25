from typing import Dict, Any, Optional, List, Iterator
from providers.base import NexusBaseProvider
import json
import logging
import os
import time

logger = logging.getLogger("NEXUS_OPENROUTER")

class OpenRouterProvider(NexusBaseProvider):
    """
    NEXUS UNIVERSAL BRIDGE (OPENROUTER.AI)
    The ultimate cloud connector that provides
    access to 200+ models through one API.
    """

    def __init__(self):
        super().__init__("openrouter", "https://openrouter.ai/api/v1/chat/completions")
        if not self.model:
            self.model = "openrouter/free"
        self._base_model = self.model

        self.fallback_models = [
            "openrouter/free",
            "nvidia/nemotron-3-nano-30b-a3b:free",
            "poolside/laguna-xs.2:free",
            "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
            "meta-llama/llama-3.2-3b-instruct:free",
            "nousresearch/hermes-3-llama-3.1-405b:free"
        ]
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://nexus-ai-os.com",
            "X-Title": "Nexus AI OS",
            "Content-Type": "application/json",
        }

    def configure_thinking(self, enabled: bool):
        self.thinking = enabled

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        if not self.validate_api_key():
            return "Error: OpenRouter API key is missing or invalid. Set OPENROUTER_API_KEY to use openrouter/free."
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        target_model = kwargs.get("model") or self.model
        timeout = kwargs.get("timeout") or int(os.getenv("NEXUS_PROVIDER_TIMEOUT", "60"))
        max_models = int(os.getenv("NEXUS_PROVIDER_MAX_MODELS", "5"))
        models_to_try = [target_model] + [m for m in self.fallback_models if m != target_model]
        models_to_try = models_to_try[:max(1, max_models)]
        
        for i, model_name in enumerate(models_to_try):
            payload = {"model": model_name, "messages": msgs}
            if self.thinking:
                payload["thinking"] = {}
            try:
                response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=timeout)
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        return data["choices"][0]["message"]["content"]
                    continue
                
                if response.status_code == 429 and i < len(models_to_try) - 1:
                    logger.warning(f"[MESH_RIPPLE]: Model '{model_name}' rate limited. Rippling...")
                    continue
                    
                return f"Error: OpenRouter API returned {response.status_code}. {response.text}"
            except Exception as e:
                if i < len(models_to_try) - 1: continue
                return f"Error: Failed to reach OpenRouter. {str(e)}"
        return "Error: All models in the AGI Mesh are currently unavailable."

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        if not self.validate_api_key():
            yield "Error in stream: OpenRouter API key is missing or invalid. Set OPENROUTER_API_KEY to use openrouter/free."
            return
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        target_model = kwargs.get("model") or self.model
        timeout = kwargs.get("timeout") or int(os.getenv("NEXUS_PROVIDER_TIMEOUT", "60"))
        deadline = time.time() + int(os.getenv("NEXUS_STREAM_DEADLINE", "120"))
        max_models = int(os.getenv("NEXUS_PROVIDER_MAX_MODELS", "5"))
        models_to_try = [target_model] + [m for m in self.fallback_models if m != target_model]
        models_to_try = models_to_try[:max(1, max_models)]
        
        for i, model_name in enumerate(models_to_try):
            if time.time() >= deadline:
                yield "Error in stream: OpenRouter stream deadline exceeded"
                return
            payload = {"model": model_name, "messages": msgs, "stream": True}
            if self.thinking:
                payload["thinking"] = {}
            try:
                response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=timeout)
                if response.status_code == 200:
                    try:
                        if hasattr(response, "raw") and response.raw:
                            conn = getattr(response.raw, "connection", None)
                            if conn:
                                sock = getattr(conn, "sock", None)
                                if sock:
                                    sock.settimeout(float(timeout))
                    except Exception:
                        pass
                    first_token_deadline = time.time() + timeout
                    has_received_token = False
                    for line in response.iter_lines():
                        if time.time() >= deadline:
                            yield "Error in stream: OpenRouter stream deadline exceeded"
                            return
                        if not has_received_token and time.time() >= first_token_deadline:
                            raise TimeoutError("No token received within timeout period")
                        if line:
                            decoded = line.decode("utf-8").strip()
                            if decoded.startswith("data: "):
                                data_str = decoded[6:].strip()
                                if data_str == "[DONE]": return
                                try:
                                    chunk = json.loads(data_str)
                                    choices = chunk.get("choices", [])
                                    if choices:
                                        has_received_token = True
                                        content = choices[0].get("delta", {}).get("content", "")
                                        if content: yield content
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                    return # Success
                
                if i < len(models_to_try) - 1:
                    yield f"\n[MESH_RIPPLE]: '{model_name}' returned status {response.status_code}. Switching to '{models_to_try[i+1]}'...\n"
                    continue
                
                yield f"Error: {response.status_code}. {response.text[:200]}..."
                return
            except Exception as e:
                if i < len(models_to_try) - 1:
                    yield f"\n[MESH_RIPPLE]: '{model_name}' failed ({str(e)}). Switching to '{models_to_try[i+1]}'...\n"
                    continue
                yield f"Error in stream: {str(e)}"
                return
