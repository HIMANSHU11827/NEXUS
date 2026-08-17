"""Canonical event identity, ordering, and replay-field regression tests.

New tests only — no existing test files are modified.
"""

import pytest

from nexus.events import EVENT_TYPES, CanonicalEvent, infer_event_type


# ───────────────────────── (a) identity ─────────────────────────────────────


def test_event_id_deterministic_fallback():
    raw = {"status": "running", "kind": "tool", "tool": "reading"}
    first = CanonicalEvent.from_work_event(dict(raw), "conv-x", 42)
    second = CanonicalEvent.from_work_event(dict(raw), "conv-x", 42)

    # Same log line converted twice must produce the same event id.
    assert first.event_id == second.event_id
    assert first.event_id == "evt_conv-x_42"


def test_event_id_fallback_is_unique_across_sequences():
    a = CanonicalEvent.from_work_event({"status": "running"}, "conv", 1)
    b = CanonicalEvent.from_work_event({"status": "running"}, "conv", 2)
    assert a.event_id != b.event_id
    assert a.event_id.startswith("evt_")


def test_explicit_event_id_and_producer_id_preserved():
    event = CanonicalEvent.from_work_event(
        {"event_id": "sub_agent-1_abc", "status": "running"}, "conv", 5
    )
    assert event.event_id == "sub_agent-1_abc"

    fallback = CanonicalEvent.from_work_event(
        {"id": "producer-id", "status": "running"}, "conv", 6
    )
    assert fallback.event_id == "producer-id"


# ───────────────────────── (b) ordering ─────────────────────────────────────


def test_producer_sequence_is_ignored_by_allocator_contract():
    # The canonical sequence always comes from the allocator argument; a
    # producer-supplied sequence key is never trusted or surfaced.
    event = CanonicalEvent.from_work_event(
        {"status": "running", "sequence": 999}, "conv", 3
    )
    assert event.sequence == 3
    assert "sequence" not in event.payload


def test_sequence_must_be_positive():
    with pytest.raises(ValueError):
        CanonicalEvent.from_work_event({"status": "running"}, "conv", 0)
    with pytest.raises(ValueError):
        CanonicalEvent.from_work_event({"status": "running"}, "conv", -1)


# ───────────────────── (c) lifecycle completeness ───────────────────────────


def test_event_types_cover_required_runtime_families():
    required = {
        "run", "conversation", "message", "plan", "phase", "tool", "command",
        "file", "search", "web", "test", "subagent", "handoff", "approval",
        "checkpoint", "skill", "mcp", "error", "retry", "status", "agent", "memory",
    }
    for family in required:
        assert any(
            event_type == family or event_type.startswith(f"{family}.")
            for event_type in EVENT_TYPES
        ), f"No event type matches prefix '{family}'"


def test_infer_event_type_kind_coverage():
    assert infer_event_type({"kind": "handoff", "status": "running"}, "running") == "handoff.started"
    assert infer_event_type({"kind": "handoff", "status": "success"}, "success") == "handoff.completed"
    assert infer_event_type({"kind": "handoff", "status": "failed"}, "failed") == "handoff.failed"
    assert infer_event_type({"kind": "mcp", "status": "running"}, "running") == "mcp.started"
    assert infer_event_type({"kind": "mcp", "status": "success"}, "success") == "mcp.completed"
    assert infer_event_type({"kind": "checkpoint", "status": "failed"}, "failed") == "checkpoint.failed"
    assert infer_event_type({"kind": "approval", "status": "running"}, "running") == "approval.requested"
    assert infer_event_type({"kind": "subagent", "status": "running"}, "running") == "subagent.started"


def test_infer_event_type_explicit_event_type_wins_for_hive():
    # Hive events always carry an explicit event_type; it must be preserved.
    assert (
        infer_event_type(
            {"kind": "subagent", "event_type": "subagent.result", "status": "success"},
            "success",
        )
        == "subagent.result"
    )


def test_inferred_types_always_validate():
    for kind in ("handoff", "mcp", "checkpoint", "subagent", "hive"):
        for status in ("running", "success", "failed"):
            inferred = infer_event_type({"kind": kind}, status)
            assert inferred in EVENT_TYPES, (kind, status, inferred)


# ─────────────────────── (d) replay recovery fields ─────────────────────────


def test_hive_event_maps_replay_fields_for_recovery():
    event = CanonicalEvent.from_work_event(
        {
            "event_id": "sub_agent-1_x",
            "event_type": "subagent.failed",
            "kind": "subagent",
            "run_id": "run-parent",
            "turn_id": "run-parent",
            "parent_run_id": "run-parent",
            "task_id": "agent-1",
            "related_subagent": "agent-1",
            "hive_id": "hive_abc",
            "status": "failed",
            "error": {"message": "boom"},
        },
        "conv",
        7,
    )

    assert event.event_id == "sub_agent-1_x"
    assert event.run_id == "run-parent"
    assert event.parent_run_id == "run-parent"
    assert event.sequence == 7
    assert event.timestamp > 0
    assert event.type == "subagent.failed"
    assert event.related_subagent == "agent-1"
    assert event.payload["task_id"] == "agent-1"
    assert event.payload["hive_id"] == "hive_abc"
    assert event.error == {"message": "boom"}


def test_replay_required_fields_present_in_serialized_form():
    event = CanonicalEvent.from_work_event(
        {"event_type": "subagent.completed", "kind": "subagent", "status": "success"},
        "conv",
        9,
    )
    serialized = event.to_dict()
    for field in ("event_id", "run_id", "conversation_id", "sequence", "timestamp", "parent_run_id"):
        assert field in serialized
    assert serialized["sequence"] == 9
