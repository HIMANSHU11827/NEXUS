import json
import logging
import os
from typing import Dict, Iterator, List, Optional

from providers.base import NexusBaseProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(NexusBaseProvider):
    """
    NEXUS CLOUD PROVIDER (ANTHROPIC CLAUDE)
    Strategic reasoning and high-end architectural coding.
    Uses Anthropic's native Messages API with tool support.
    """

    def __init__(self):
        super().__init__("anthropic", "https://api.anthropic.com/v1/messages")
        if not self.model:
            self.model = os.environ.get("NEXUS_PROVIDER_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": os.environ.get("NEXUS_ANTHROPIC_VERSION", "2023-06-01"),
            "content-type": "application/json"
        }
        # Filled at end-of-stream when the API reports token usage.
        self._last_usage: Optional[Dict[str, int]] = None

    @staticmethod
    def _content_to_text(content: list) -> str:
        """Extract plain text from Anthropic content blocks.
        Anthropic returns content as a list of blocks like:
        [{"type": "text", "text": "..."}, {"type": "tool_use", ...}]
        """
        parts = []
        for block in content or []:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
        return "\n".join(parts)

    @staticmethod
    def _tool_envelope_from_content(content: list) -> str:
        """Convert Anthropic tool_use content blocks to V5 envelope format.
        Anthropic returns tool calls as content blocks with type="tool_use":
        {"type": "tool_use", "name": "...", "input": {...}}
        """
        envelopes = []
        for block in content or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = str(block.get("name") or "").strip()
                if not name:
                    continue
                arguments = NexusBaseProvider.normalize_tool_arguments(
                    block.get("input", {}), tool_name=name
                )
                envelopes.append(f"<function={name}>{json.dumps(arguments, ensure_ascii=False)}")
        return "\n".join(envelopes)

    @staticmethod
    def _add_tool_payload(payload: dict, kwargs: dict) -> None:
        """Preserve model-selected native tool calling when requested."""
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
            payload["tool_choice"] = kwargs.get("tool_choice", {"type": "auto"})

    def generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        # Anthropic separates system prompt from messages
        payload = {
            "model": kwargs.get("model") or self.model,
            "max_tokens": kwargs.get("max_tokens") or 4096,
            "system": system_prompt,
            "messages": [m for m in msgs if m["role"] != "system"]
        }
        self._add_tool_payload(payload, kwargs)
        response = None
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, timeout=self.request_timeout(kwargs, 60))
            if response.status_code == 200:
                data = response.json()
                content = data.get("content", [])
                # Anthropic returns tool_use blocks inside content list
                tool_envelope = self._tool_envelope_from_content(content)
                if tool_envelope:
                    return tool_envelope
                return self._content_to_text(content)
            return f"Error: Anthropic API returned {response.status_code} - {response.text}"
        except Exception as e:
            return f"Error: Failed to reach Anthropic. {str(e)}"

    def stream_generate(self, prompt: str = '', system_prompt: str = "", messages: Optional[List[Dict[str, str]]] = None, **kwargs) -> Iterator[str]:
        msgs = self._prepare_messages(prompt, system_prompt, messages)
        payload = {
            "model": kwargs.get("model") or self.model,
            "max_tokens": kwargs.get("max_tokens") or 4096,
            "system": system_prompt,
            "messages": [m for m in msgs if m["role"] != "system"],
            "stream": True
        }
        self._add_tool_payload(payload, kwargs)
        try:
            response = self.session.post(self.endpoint, json=payload, headers=self.headers, stream=True, timeout=self.request_timeout(kwargs, 120))
            if response.status_code == 200:
                # Anthropic SSE streams: event: content_block_start, content_block_delta, content_block_stop, message_stop
                # Accumulate tool_use blocks across stream events
                current_block_index = None
                current_tool_use = None
                accumulated_envelopes = []
                # Extended thinking arrives as separate "thinking"/"redacted_thinking"
                # content blocks. Wrap their deltas in NEXUS <thinking> markers so
                # the transcript surfaces reasoning like the DeepSeek adapter does.
                in_thinking_block = False
                # Token usage reported by the API (message_start.input_tokens,
                # message_delta.output_tokens); surfaced on message_stop.
                _usage: Dict[str, int] = {}

                for line in response.iter_lines():
                    if line:
                        decoded = line.decode('utf-8').strip()
                        if decoded.startswith("data: "):
                            data_str = decoded[6:].strip()
                            try:
                                event_data = json.loads(data_str)
                                event_type = event_data.get("type", "")

                                if event_type == "message_start":
                                    message = event_data.get("message", {})
                                    start_usage = message.get("usage", {}) if isinstance(message, dict) else {}
                                    if isinstance(start_usage, dict) and start_usage.get("input_tokens"):
                                        input_tokens = int(start_usage.get("input_tokens") or 0)
                                        _usage["input_tokens"] = input_tokens
                                        _usage["total_tokens"] = _usage.get("total_tokens", 0) + input_tokens

                                elif event_type == "message_delta":
                                    delta_usage = event_data.get("usage", {})
                                    if isinstance(delta_usage, dict) and delta_usage.get("output_tokens"):
                                        output_tokens = int(delta_usage.get("output_tokens") or 0)
                                        _usage["output_tokens"] = output_tokens
                                        _usage["total_tokens"] = _usage.get("total_tokens", 0) + output_tokens

                                elif event_type == "content_block_start":
                                    block = event_data.get("content_block", {})
                                    current_block_index = event_data.get("index")
                                    block_type = str(block.get("type", "")) if isinstance(block, dict) else ""
                                    if block_type == "tool_use":
                                        current_tool_use = {
                                            "name": str(block.get("name", "")),
                                            "input": ""
                                        }
                                    elif block_type == "thinking":
                                        in_thinking_block = True
                                        current_tool_use = None
                                        yield "<thinking>"
                                    elif block_type == "redacted_thinking":
                                        # Redacted thinking carries no deltas; emit an inert marker.
                                        in_thinking_block = True
                                        current_tool_use = None
                                        yield "<thinking>[redacted reasoning]"
                                    else:
                                        # Anthropic may deliver the opening text of a block
                                        # directly on the start event.
                                        initial_text = block.get("text", "") if isinstance(block, dict) else ""
                                        if initial_text:
                                            yield initial_text
                                        current_tool_use = None

                                elif event_type == "content_block_delta":
                                    delta = event_data.get("delta", {})
                                    delta_type = str(delta.get("type", "")) if isinstance(delta, dict) else ""
                                    if delta_type == "thinking_delta" and in_thinking_block:
                                        thinking_text = delta.get("thinking", "")
                                        if thinking_text:
                                            yield thinking_text
                                    elif delta_type in ("text", "text_delta"):
                                        if in_thinking_block:
                                            yield "</thinking>"
                                            in_thinking_block = False
                                        text = delta.get("text", "")
                                        if text:
                                            yield text
                                    elif delta_type == "input_json_delta":
                                        if current_tool_use is not None:
                                            current_tool_use["input"] += delta.get("partial_json", "")

                                elif event_type == "content_block_stop":
                                    if in_thinking_block:
                                        yield "</thinking>"
                                        in_thinking_block = False
                                    if current_tool_use is not None:
                                        name = current_tool_use["name"]
                                        input_str = current_tool_use["input"]
                                        arguments = NexusBaseProvider.normalize_tool_arguments(
                                            input_str, tool_name=name
                                        )
                                        if name:
                                            accumulated_envelopes.append(
                                                f"<function={name}>{json.dumps(arguments, ensure_ascii=False)}"
                                            )
                                        current_tool_use = None
                                    current_block_index = None

                                elif event_type == "message_stop":
                                    # End of stream: surface token usage the API returned.
                                    if _usage:
                                        self._last_usage = dict(_usage)

                            except json.JSONDecodeError:
                                continue

                # Guard against a stream that ends inside a thinking block.
                if in_thinking_block:
                    yield "</thinking>"

                if accumulated_envelopes:
                    yield "\n".join(accumulated_envelopes)
            else:
                yield f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            yield f"Error in Anthropic stream: {str(e)}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logging.debug("Anthropic stream response cleanup failed", exc_info=True)

if __name__ == "__main__":
    p = AnthropicProvider()
    # print(p.generate("Tell me your name."))


