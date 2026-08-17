"""Regression tests for hard context-budget admission boundaries."""

from nexus.context import compact_messages, inspect


def test_recent_only_messages_do_not_bypass_hard_budget_on_floored_estimate():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "1234"},
    ]

    # The diagnostic estimate floors 5 // 4 to one token, but the hard
    # character envelope for a one-token budget is four characters.
    assert inspect(messages)["est_tokens"] == 1
    compacted, dropped = compact_messages(messages, budget_tokens=1, keep_recent=6)

    assert inspect(compacted)["total_chars"] <= 4
    assert all(message.get("content") != "1234" for message in compacted)
    assert dropped >= 1
