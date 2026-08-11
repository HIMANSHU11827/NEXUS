from types import SimpleNamespace

from orchestrators.v5.token_usage import (
    estimate_messages_tokens,
    normalize_usage,
)


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
