"""Tests for reliability.states: validated transitions and persistence."""

import json

import pytest

from reliability.states import (
    TRANSITION_TABLE,
    RunState,
    RunStateMachine,
    TransitionRecord,
)


class TestTransitions:
    def test_valid_execution_path(self):
        machine = RunStateMachine()
        assert machine.transition(RunState.PLANNING, reason="turn start")
        assert machine.transition(RunState.EXECUTING, reason="model loop")
        assert machine.transition(RunState.RECOVERING, reason="tool failed")
        assert machine.transition(RunState.EXECUTING, reason="recovered")
        assert machine.transition(RunState.VERIFYING, reason="verify evidence")
        assert machine.transition(RunState.GOAL_COMPLETED, reason="verified")
        assert machine.state == RunState.GOAL_COMPLETED

    def test_invalid_transition_rejected(self):
        machine = RunStateMachine(RunState.GOAL_COMPLETED)
        assert not machine.transition(RunState.EXECUTING, reason="should fail")
        assert machine.state == RunState.GOAL_COMPLETED

    def test_terminal_states_are_absorbing(self):
        for terminal in (RunState.GOAL_COMPLETED, RunState.FAILED,
                         RunState.CANCELLED_BY_USER, RunState.TIMED_OUT):
            machine = RunStateMachine(terminal)
            assert machine.transition(RunState.EXECUTING, reason="late") is False

    def test_same_state_is_noop(self):
        machine = RunStateMachine(RunState.PLANNING)
        assert machine.transition(RunState.PLANNING, reason="again") is True

    def test_history_records_reason(self):
        machine = RunStateMachine()
        machine.transition(RunState.PLANNING, reason="first step")
        machine.transition(RunState.EXECUTING, reason="second step", meta={"x": 1})
        history = machine.history()
        assert len(history) == 2
        assert history[0].reason == "first step"
        assert history[0].previous_state == RunState.INITIALIZING
        assert history[1].meta == {"x": 1}

    def test_on_change_callback(self):
        seen = []
        machine = RunStateMachine(on_change=lambda prev, new, reason: seen.append((prev, new, reason)))
        machine.transition(RunState.PLANNING, reason="why")
        assert seen == [(RunState.INITIALIZING, RunState.PLANNING, "why")]

    def test_recovering_exit_options(self):
        allowed = TRANSITION_TABLE[RunState.RECOVERING]
        assert RunState.EXECUTING in allowed
        assert RunState.REPLANNING in allowed
        assert RunState.BLOCKED_NON_RECOVERABLE in allowed
        assert RunState.FAILED in allowed

    def test_blocked_is_not_terminal(self):
        assert RunState.BLOCKED_NON_RECOVERABLE.is_terminal is False
        assert RunState.BLOCKED_NON_RECOVERABLE.is_blocked is True
        assert RunState.WAITING_FOR_PERMISSION.is_blocked is True


class TestV5Mapping:
    def test_from_v5_full_map(self):
        mapping = {
            "initializing": RunState.INITIALIZING,
            "perceiving": RunState.PERCEIVING,
            "planning": RunState.PLANNING,
            "acting": RunState.EXECUTING,
            "observing": RunState.OBSERVING,
            "reflecting": RunState.REFLECTING,
            "retrying": RunState.RETRYING,
            "evolving": RunState.PLANNING,
            "conscious": RunState.PLANNING,
            "outputting": RunState.OUTPUTTING,
            "completed": RunState.GOAL_COMPLETED,
            "cancelled": RunState.CANCELLED_BY_USER,
            "timed_out": RunState.TIMED_OUT,
            "failed": RunState.FAILED,
        }
        for raw, expected in mapping.items():
            assert RunState.from_v5(raw) is expected, raw

    def test_from_v5_enum_object(self):
        class FakeV5:
            value = "acting"

        assert RunState.from_v5(FakeV5()) is RunState.EXECUTING

    def test_from_v5_unknown_falls_back(self):
        assert RunState.from_v5("quantum") is RunState.INITIALIZING
        assert RunState.from_v5(None) is RunState.INITIALIZING


class TestPersistence:
    def test_persist_and_load(self, tmp_path):
        path = str(tmp_path / "state.json")
        machine = RunStateMachine(persist_path=path)
        machine.transition(RunState.PLANNING, reason="plan")
        machine.transition(RunState.EXECUTING, reason="execute")
        loaded = RunStateMachine.load(path)
        assert loaded.state == RunState.EXECUTING
        assert len(loaded.history()) == 2
        assert loaded.history()[0].reason == "plan"

    def test_corrupt_snapshot_tolerated(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{not json", encoding="utf-8")
        machine = RunStateMachine.load(str(path))
        assert machine.state == RunState.INITIALIZING

    def test_missing_snapshot(self, tmp_path):
        machine = RunStateMachine.load(str(tmp_path / "nope.json"))
        assert machine.state == RunState.INITIALIZING

    def test_restore(self):
        machine = RunStateMachine()
        records = [
            TransitionRecord(
                state=RunState.PLANNING,
                previous_state=RunState.INITIALIZING,
                reason="r",
                timestamp=1.0,
            )
        ]
        machine.restore(RunState.PLANNING, records)
        assert machine.state == RunState.PLANNING
        assert machine.history()[0].reason == "r"

    def test_transition_record_round_trip(self):
        record = TransitionRecord(
            state=RunState.EXECUTING,
            previous_state=RunState.PLANNING,
            reason="go",
            timestamp=2.0,
            meta={"k": "v"},
        )
        data = record.to_dict()
        assert data["state"] == "executing"
        assert data["meta"] == {"k": "v"}