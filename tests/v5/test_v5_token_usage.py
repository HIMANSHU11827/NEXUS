from types import SimpleNamespace

import pytest

from orchestrators.v5.token_usage import (
    estimate_cost_usd,
    estimate_messages_tokens,
    normalize_usage,
)
from orchestrators.v5.direct_loop import V5DirectModelToolLoop


def test_estimate_cost_known_cloud_model_uses_list_price():
    cost = estimate_cost_usd("openai", "gpt-4o-mini", 1_000_000, 500_000)
    assert cost == pytest.approx(0.15 + 0.30)


def test_estimate_cost_local_provider_is_free():
    assert estimate_cost_usd("ollama", "llama3", 1_000_000, 1_000_000) == 0.0


def test_estimate_cost_unknown_model_uses_conservative_fallback():
    cost = estimate_cost_usd("my-gateway", "custom-model-v3", 1_000_000, 1_000_000)
    assert cost == pytest.approx(1.00 + 2.00)


def test_normalize_openai_usage_and_reasoning_details():
    usage = normalize_usage({
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "completion_tokens_details": {"reasoning_tokens": 3},
        }
    })
    assert usage.input_tokens == 11
    assert usage.output_tokens == 7
    assert usage.reasoning_tokens == 3
    assert usage.total_tokens == 18


def test_normalize_object_usage_and_estimate_when_no_usage():
    response = SimpleNamespace(usage=SimpleNamespace(input_tokens=4, output_tokens=5))
    assert normalize_usage(response).total_tokens == 9
    assert estimate_messages_tokens([{"role": "user", "content": "abcd"}]) == 1


def test_normalize_malformed_usage_fails_closed_to_zero():
    assert normalize_usage({"usage": {"prompt_tokens": "bad"}}).total_tokens == 0


def test_direct_loop_accumulates_measured_usage_without_estimates():
    loop = V5DirectModelToolLoop.__new__(V5DirectModelToolLoop)

    loop._record_model_usage({"usage": {"prompt_tokens": 12, "completion_tokens": 4}})
    loop._record_model_usage({"usage": {"prompt_tokens": 20, "completion_tokens": 6}})

    assert loop._last_turn_usage == {
        "input_tokens": 32,
        "output_tokens": 10,
        "reasoning_tokens": 0,
        "context_tokens": 20,
    }


def test_direct_loop_does_not_create_usage_for_missing_provider_telemetry():
    loop = V5DirectModelToolLoop.__new__(V5DirectModelToolLoop)

    loop._record_model_usage({"message": {"content": "text only"}})

    assert not hasattr(loop, "_last_turn_usage")
