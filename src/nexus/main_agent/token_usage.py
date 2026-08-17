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


# (substring, input_usd_per_million, output_usd_per_million) — public list
# prices, kept compact on purpose. Order matters: specific keys first so a
# generic key ("gpt-4") never shadows "gpt-4o-mini".
_ESTIMATED_PRICES_PER_MT = [
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.00),
    ("gpt-4.1", 2.00, 8.00),
    ("gpt-4", 30.00, 60.00),
    ("o4-mini", 1.10, 4.40),
    ("o3", 2.00, 8.00),
    ("claude-3-7-sonnet", 3.00, 15.00),
    ("claude-3-5-sonnet", 3.00, 15.00),
    ("claude-sonnet", 3.00, 15.00),
    ("claude-3-5-haiku", 0.80, 4.00),
    ("claude-3-haiku", 0.25, 1.25),
    ("claude-opus", 15.00, 75.00),
    ("deepseek-reasoner", 0.55, 2.19),
    ("deepseek-chat", 0.27, 1.10),
    ("deepseek", 0.55, 2.19),
    ("gemini-2.5-pro", 1.25, 10.00),
    ("gemini-2.5-flash", 0.30, 2.50),
    ("gemini", 1.25, 10.00),
]

_LOCAL_PROVIDER_MARKERS = (
    "local", "ollama", "lmstudio", "llama", "kobold", "vllm", "text-generation",
)

# Conservative mid-range fallback when the model is unknown: $1.00 / $2.00 per
# million tokens.
_DEFAULT_PRICE_IN = 1.00
_DEFAULT_PRICE_OUT = 2.00


def estimate_cost_usd(
    provider: Any,
    model: Any,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate the USD cost of a model call from public list prices.

    Providers do not report cost, so this is a documented estimate: local
    providers cost zero, known cloud models use their list price, and unknown
    models fall back to a conservative mid-range rate. Never raises.
    """
    prov = str(provider or "").lower()
    mod = str(model or "").lower()
    if any(marker in prov for marker in _LOCAL_PROVIDER_MARKERS):
        return 0.0
    price_in, price_out = _DEFAULT_PRICE_IN, _DEFAULT_PRICE_OUT
    for key, pin, pout in _ESTIMATED_PRICES_PER_MT:
        if key in mod or key in prov:
            price_in, price_out = pin, pout
            break
    return max(
        0.0,
        max(0, int(input_tokens)) * price_in / 1_000_000
        + max(0, int(output_tokens)) * price_out / 1_000_000,
    )


__all__ = [
    "TokenUsage",
    "estimate_cost_usd",
    "estimate_messages_tokens",
    "normalize_usage",
]
