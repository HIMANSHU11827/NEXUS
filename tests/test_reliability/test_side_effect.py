"""Tests for reliability.side_effect — P1 side-effect reconciliation adapter.

RED -> GREEN: prove a retried side-effect reconciles the prior result
instead of repeating it, and that an in-flight effect is refused (no
concurrent double execution).
"""

import os

from reliability.side_effect import (
    EXECUTE,
    REPLAY,
    UNCERTAIN,
    SideEffectGuard,
)


def test_duplicate_attempt_replays_instead_of_repeating(tmp_path):
    calls = []

    def send():
        calls.append(1)
        return "ok-42"

    guard = SideEffectGuard(str(tmp_path))
    key = guard.make_key("agent-1", "task-7", 0, "webhook", {"x": 1})

    first = guard.execute_once(key, agent_id="agent-1", tool="webhook", call=send)
    assert first.verdict == EXECUTE
    assert first.result == "ok-42"
    assert first.ran is True

    # Retry of the same logical work: must NOT call send() again.
    second = guard.execute_once(key, agent_id="agent-1", tool="webhook", call=send)
    assert second.verdict == REPLAY
    assert second.replayed is True
    assert second.result == "ok-42"
    assert calls == [1]  # executed exactly once


def test_failed_effect_is_recorded_and_retry_re_executes(tmp_path):
    fails = {"n": 0}

    def flaky():
        fails["n"] += 1
        if fails["n"] == 1:
            raise RuntimeError("boom")
        return "recovered"

    guard = SideEffectGuard(str(tmp_path))
    key = guard.make_key("a", "t", 0, "api", {})

    out1 = guard.execute_once(key, agent_id="a", tool="api", call=flaky)
    assert out1.verdict == EXECUTE
    assert out1.error == "boom"
    assert fails["n"] == 1

    # A failed effect is not "succeeded", so a later retry must re-execute.
    out2 = guard.execute_once(key, agent_id="a", tool="api", call=flaky)
    assert out2.verdict == EXECUTE
    assert out2.result == "recovered"
    assert fails["n"] == 2


def test_in_flight_effect_is_refused(tmp_path):
    guard = SideEffectGuard(str(tmp_path), lease_seconds=300)
    key = guard.make_key("a", "t", 0, "api", {})

    # First claim takes the lease and returns EXECUTE (work not yet done).
    first = guard.claim_only(key, agent_id="a", tool="api")
    assert first == (EXECUTE, "")

    # A second claim while the lease is still held must be refused, so a
    # retry cannot run the side-effect concurrently with the first attempt.
    second = guard.claim_only(key, agent_id="a", tool="api")
    assert second[0] == UNCERTAIN
    assert second[1]


def test_completed_effect_replays_on_reclaim(tmp_path):
    guard = SideEffectGuard(str(tmp_path), lease_seconds=300)
    key = guard.make_key("a", "t", 0, "api", {})
    # Take the lease, then complete the work.
    assert guard.claim_only(key, agent_id="a", tool="api") == (EXECUTE, "")
    guard._ledger.complete(key, "result-99")
    # A later reclaim must replay the recorded result, never re-execute.
    verdict, payload = guard.claim_only(key, agent_id="a", tool="api")
    assert verdict == REPLAY
    assert payload == "result-99"
