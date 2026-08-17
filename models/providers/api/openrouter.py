import json
import logging
import os
import time
from typing import Dict, Iterator, List, Optional

from models.providers.core.base import NexusBaseProvider
from models.providers.core.reliability import redact_secrets

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
            self.model = os.environ.get("NEXUS_PROVIDER_OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        self._base_model = self.model

        # Real, verified OpenRouter free-tier model slugs. (Invented slugs such as
        # 'openrouter/free' or 'poolside/laguna-xs.2:free' 400 and kill the mesh.)
        self.fallback_models = [
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-r1-distill-llama-70b:free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "google/gemma-2-9b-it:free",
            "microsoft/phi-3-mini-128k-instruct:free",
        ]
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": os.environ.get("NEXUS_OPENROUTER_REFERER", "https://nexus-ai-os.com"),
            "X-Title": os.environ.get("NEXUS_OPENROUTER_TITLE", "Nexus AI OS"),
            "Content-Type": "application/json",
        }

    def configure_thinking(self, enabled: bool):
        self.thinking = enabled

    @staticmethod
    def _tool_envelope(tool_calls) -> str:
        """Convert OpenAI-compatible native calls to NEXUS's parser format."""
        envelopes = []
        for call in tool_calls or []:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            arguments = NexusBaseProvider.normalize_tool_arguments(
                function.get("arguments", {}), tool_name=name
            )
            envelopes.append(f"<function={name}>{json.dumps(arguments, ensure_ascii=False)}")
        return "\n".join(envelopes)

    @staticmethod
    def _add_tool_payload(payload: dict, kwargs: dict) -> None:
        """Preserve native tool calling when the orchestrator supplies schemas."""
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            payload["tool_choice"] = kwargs["tool_choice"]

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
            self._add_tool_payload(payload, kwargs)
            if self.thinking:
                payload["thinking"] = {}
            try:
                response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=timeout)
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        message = data["choices"][0].get("message", {})
                        native_tools = message.get("tool_calls") or []
                        if native_tools:
                            return self._tool_envelope(native_tools)
                        return message.get("content") or ""
                    continue
                
                if response.status_code in (408, 429, 500, 502, 503, 504) and i < len(models_to_try) - 1:
                    logger.warning(f"[MESH_RIPPLE]: Model '{model_name}' returned {response.status_code}. Rippling...")
                    continue
                    
                return (
                    f"Error: OpenRouter API returned status {response.status_code}. "
                    f"{redact_secrets(response.text)[:500]}"
                )
            except Exception as e:
                if i < len(models_to_try) - 1: continue
                return f"Error: Failed to reach OpenRouter. {redact_secrets(e)[:500]}"
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
            self._add_tool_payload(payload, kwargs)
            if self.thinking:
                payload["thinking"] = {}
            response = None
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
                        logger.warning("providers/openrouter.py:103 : suppressed error", exc_info=True)
                        pass
                    first_token_deadline = time.time() + timeout
                    has_received_token = False
                    streamed_tool_calls = {}
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
                                        delta = choices[0].get("delta", {})
                                        for tool_call in delta.get("tool_calls", []) or []:
                                            index = tool_call.get("index", 0)
                                            current = streamed_tool_calls.setdefault(index, {
                                                "function": {"name": "", "arguments": ""}
                                            })
                                            function = tool_call.get("function", {}) or {}
                                            current["function"]["name"] += str(function.get("name") or "")
                                            current["function"]["arguments"] += str(function.get("arguments") or "")
                                        content = delta.get("content", "")
                                        if content: yield content
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                    if streamed_tool_calls:
                        yield self._tool_envelope(list(streamed_tool_calls.values()))
                    return # Success
                
                if i < len(models_to_try) - 1:
                    # Retry diagnostics belong in logs, never in the model
                    # stream.  Streaming them makes the UI render internal
                    # router chatter as if it were the assistant's answer.
                    logger.warning(
                        "[MESH_RIPPLE]: Model '%s' returned %s. Retrying '%s'.",
                        model_name, response.status_code, models_to_try[i + 1],
                    )
                    continue
                
                yield (
                    f"Error: OpenRouter API returned status {response.status_code}. "
                    f"{redact_secrets(response.text)[:200]}..."
                )
                return
            except Exception as e:
                if i < len(models_to_try) - 1:
                    logger.warning(
                        "[MESH_RIPPLE]: Model '%s' failed (%s). Retrying '%s'.",
                        model_name, redact_secrets(e)[:200], models_to_try[i + 1],
                    )
                    continue
                yield f"Error in stream: {redact_secrets(e)[:500]}"
                return
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        logger.debug("OpenRouter stream response cleanup failed", exc_info=True)


