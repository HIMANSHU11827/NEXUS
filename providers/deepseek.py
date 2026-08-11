import json
import logging
import os
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider
from providers.reliability import redact_secrets


class DeepSeekProvider(NexusBaseProvider):
    """
    NEXUS NATIVE DEEPSEEK PROVIDER
    High-performance reasoning and coding models.
    """
    
    def __init__(self):
        super().__init__("deepseek", "https://api.deepseek.com/chat/completions")
        if not self.model:
            self.model = os.environ.get("NEXUS_PROVIDER_DEEPSEEK_MODEL", "deepseek-chat")
        self._base_model = self.model
        self._thinking_model = "deepseek-reasoner"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def configure_thinking(self, enabled: bool):
        self.thinking = enabled
        self.model = self._thinking_model if enabled else self._base_model

    @staticmethod
    def _tool_envelope(tool_calls) -> str:
        """Convert OpenAI-compatible native calls to the V5 parser format."""
        envelopes = []
        for call in tool_calls or []:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
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
            raise RuntimeError("deepseek: missing or invalid API key")
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": kwargs.get("model") or self.model, "messages": msgs}
        if kwargs.get("max_tokens") is not None:
            payload["max_tokens"] = kwargs["max_tokens"]
        self._add_tool_payload(payload, kwargs)
        response = None
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0].get("message", {})
                native_tools = message.get("tool_calls") or []
                if native_tools:
                    return self._tool_envelope(native_tools)
                return message.get("content") or ""
            result = (
                f"Error: DeepSeek API returned status {response.status_code}. "
                f"{redact_secrets(response.text)[:500]}"
            )
            logging.error(
                "DeepSeek API error status=%s detail=%s",
                response.status_code,
                redact_secrets(response.text)[:500],
            )
            return result
        except Exception as e:
            return f"Error: Failed to reach DeepSeek. {redact_secrets(e)[:500]}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        if not self.validate_api_key():
            raise RuntimeError("deepseek: missing or invalid API key")
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {"model": kwargs.get("model") or self.model, "messages": msgs, "stream": True}
        if kwargs.get("max_tokens") is not None:
            payload["max_tokens"] = kwargs["max_tokens"]
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                in_thinking = False
                streamed_tool_calls = {}
                # Use the smallest practical chunk size so the GUI gets tokens
                # as early as the provider sends them.
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
                                reasoning = delta.get("reasoning_content", "")
                                if reasoning:
                                    if not in_thinking:
                                        yield "<thinking>"
                                        in_thinking = True
                                    yield reasoning
                                if content:
                                    if in_thinking:
                                        yield "</thinking>"
                                        in_thinking = False
                                    yield content
                            except json.JSONDecodeError: continue
                if in_thinking:
                    yield "</thinking>"
                if streamed_tool_calls:
                    yield self._tool_envelope(list(streamed_tool_calls.values()))
            else:
                logging.error(
                    "DeepSeek stream API error status=%s detail=%s",
                    response.status_code,
                    redact_secrets(response.text)[:500],
                )
                yield (
                    f"Error: DeepSeek API returned status {response.status_code}. "
                    f"{redact_secrets(response.text)[:500]}"
                )
        except Exception as e:
            yield f"Error in DeepSeek stream: {redact_secrets(e)[:500]}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logging.debug("DeepSeek stream response cleanup failed", exc_info=True)


