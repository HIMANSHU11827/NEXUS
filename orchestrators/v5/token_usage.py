"""Provider-agnostic token usage normalization for the V5 runtime.

Providers return usage in several shapes (OpenAI dictionaries, nested
``usage`` objects, and lightweight response objects).  Keeping normalization
here prevents the loop budget from depending on one provider's response
format and gives local providers a deterministic estimate when usage is not
reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _read(value: Any, *names: str) -> int:
    for name in names:
        if isinstance(value, Mapping):
            candidate = value.get(name)
        else:
            candidate = getattr(value, name, None)
        try:
            if candidate is not None:
                return max(0, int(candidate))
        except (TypeError, ValueError):
            continue
    return 0


def normalize_usage(response: Any) -> TokenUsage:
    """Extract canonical input/output/reasoning counts from a response."""
    usage = response.get("usage") if isinstance(response, Mapping) else getattr(response, "usage", None)
    usage = usage if usage is not None else response
    input_tokens = _read(usage, "input_tokens", "prompt_tokens")
    output_tokens = _read(usage, "output_tokens", "completion_tokens")
    reasoning = _read(usage, "reasoning_tokens")
    details = usage.get("completion_tokens_details") if isinstance(usage, Mapping) else getattr(usage, "completion_tokens_details", None)
    reasoning = reasoning or _read(details, "reasoning_tokens")
    return TokenUsage(input_tokens, output_tokens, reasoning)


def estimate_messages_tokens(messages: Any) -> int:
    """Conservative, dependency-free estimate used only when usage is absent."""
    if not isinstance(messages, list):
        return 0
    total_chars = 0
    for message in messages:
        if isinstance(message, Mapping):
            total_chars += len(str(message.get("content") or ""))
            total_chars += len(str(message.get("tool_calls") or ""))
        else:
            total_chars += len(str(message))
    return max(0, (total_chars + 3) // 4)


__all__ = ["TokenUsage", "estimate_messages_tokens", "normalize_usage"]
