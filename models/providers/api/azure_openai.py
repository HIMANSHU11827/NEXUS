import json
import logging
import os
from typing import Dict, Iterator, List, Optional

from models.providers.core.base import NexusBaseProvider

logger = logging.getLogger(__name__)


class AzureOpenAIProvider(NexusBaseProvider):
    """
    NEXUS ENTERPRISE BRIDGE (AZURE OPENAI)
    The Microsoft-backed cloud driver for zero-trust
    enterprise reasoning and secured data access.
    """

    def __init__(self):
        super().__init__("azure_openai", "")
        # The config loader may already have provided an endpoint (base.py).
        # Otherwise fall back to the canonical AZURE_OPENAI_ENDPOINT env var.
        if not self.endpoint:
            self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip() or self.model or "gpt-4o"
        if not self.model:
            self.model = self.deployment
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        self.headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json"
        }

    def _build_url(self) -> str:
        """Build the full Azure chat completions URL.

        Never silently fall back to a relative URL: a missing endpoint is a
        configuration error and should be surfaced loudly.
        """
        base = (self.endpoint or "").strip().rstrip("/")
        if not base:
            raise RuntimeError(
                "azure_openai: AZURE_OPENAI_ENDPOINT is not set. "
                "Set it to the resource root (e.g. https://<resource>.openai.azure.com)"
                " or provide an endpoint in the provider config."
            )
        return (
            f"{base}/openai/deployments/{self.deployment}/chat/completions"
            f"?api-version={self.api_version}"
        )

    @staticmethod
    def _tool_envelope(tool_calls) -> str:
        """Convert OpenAI-compatible native calls to the V5 parser format."""
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
        """Preserve model-selected native tool calling when requested."""
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            payload["tool_choice"] = kwargs["tool_choice"]

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        if not self.validate_api_key():
            raise RuntimeError("azure_openai: missing or invalid API key")
        target_url = self._build_url()
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": kwargs.get("model") or self.deployment, "messages": msgs}
        if kwargs.get("max_tokens") is not None:
            payload["max_tokens"] = kwargs["max_tokens"]
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(target_url, json=payload, headers=self.headers, timeout=self.request_timeout(kwargs, 30))
            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0].get("message", {})
                native_tools = message.get("tool_calls") or []
                if native_tools:
                    return self._tool_envelope(native_tools)
                return message.get("content") or ""
            result = f"Error: Azure OpenAI returned status {response.status_code}. {response.text}"
            logger.error(result)
            return result
        except Exception as e:
            return f"Error: Failed to reach Azure. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        response = None
        if not self.validate_api_key():
            raise RuntimeError("azure_openai: missing or invalid API key")
        target_url = self._build_url()
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": kwargs.get("model") or self.deployment, "messages": msgs, "stream": True}
        if kwargs.get("max_tokens") is not None:
            payload["max_tokens"] = kwargs["max_tokens"]
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(target_url, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 30))
            if response.status_code == 200:
                streamed_tool_calls = {}
                for line in response.iter_lines(chunk_size=1):
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:]
                            if data_str == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0].get("delta", {})
                                for tool_call in delta.get("tool_calls", []) or []:
                                    index = tool_call.get("index", 0)
                                    current = streamed_tool_calls.setdefault(index, {
                                        "function": {"name": "", "arguments": ""}
                                    })
                                    function = tool_call.get("function", {}) or {}
                                    current["function"]["name"] += str(function.get("name") or "")
                                    current["function"]["arguments"] += str(function.get("arguments") or "")
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                if streamed_tool_calls:
                    yield self._tool_envelope(list(streamed_tool_calls.values()))
            else:
                yield f"Error: {response.status_code}"
        except Exception as e:
            yield f"Error: {e}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.debug("Azure OpenAI stream response cleanup failed", exc_info=True)
