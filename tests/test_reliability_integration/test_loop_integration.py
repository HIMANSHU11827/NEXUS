"""Integration tests: reliability core wired into the V5 loop.

These tests construct the NexusLoopV5 harness the same way existing v5 tests
do (see tests/v5/test_v5_loop.py) and verify the reliability integration:
state machine mirroring, durable goals, checkpoint failure surfacing,
recovery events, and stall detection.
"""

import asyncio

import pytest

from nexus.run_context import load_run_context, start_run_context
from reliability.failure import FailureClass
from reliability.goal import GoalStore
from reliability.progress import ProgressTracker
from reliability.states import RunState


def build_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_V5_STATE_DIR", str(tmp_path / "v5state"))
    from orchestrators.v5.core import V5LoopState, NexusLoopV5

    loop = NexusLoopV5(root_dir=str(tmp_path / "root"), session_id="testsession")
    loop.root_dir = str(tmp_path / "root")
    loop.session_id = "testsession"
    return loop, V5LoopState


class TestStateMachineMirror:
    def test_transition_mirrors_through_machine(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._ensure_reliability()
        assert not getattr(loop, "_reliability_disabled", False)
        loop._mirror_transition("planning", reason="turn start")
        loop._mirror_transition("acting", reason="execute")
        loop._mirror_transition("recovering", reason="tool failed")
        assert loop._state_machine.state == RunState.RECOVERING
        reasons = [record.reason for record in loop._state_machine.history()]
        assert "tool failed" in reasons

    def test_invalid_transition_does_not_crash(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._ensure_reliability()
        loop._mirror_transition("planning", reason="turn start")
        loop._mirror_transition("executing", reason="execute")
        loop._mirror_transition("completed", reason="done")
        loop._mirror_transition("executing", reason="late")
        assert loop._state_machine.state == RunState.GOAL_COMPLETED

    def test_async_transition_to_runs(self, tmp_path, monkeypatch):
        loop, v5_state = build_loop(tmp_path, monkeypatch)
        asyncio.run(loop._transition_to(v5_state.PLANNING, reason="plan"))
        asyncio.run(loop._transition_to(v5_state.ACTING, reason="act"))
        asyncio.run(loop._transition_to(v5_state.COMPLETED, reason="verify"))
        assert loop._state_machine.state == RunState.GOAL_COMPLETED


class TestGoalDurability:
    def test_goal_created_and_persisted(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        goal = loop._get_goal("research topic X and implement it")
        assert goal is not None
        assert goal.goal_id == "goal_testsession"
        store = GoalStore(str(tmp_path / "v5state" / "goals"))
        persisted = store.load(goal.goal_id)
        assert persisted is not None
        assert persisted.parsed_objective == "research topic X and implement it"

    def test_terminal_goal_records_completion(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._get_goal("do the thing")
        loop._record_terminal_goal(
            "completed", evidence=["tests passed", "docs updated"]
        )
        store = GoalStore(str(tmp_path / "v5state" / "goals"))
        goal = store.load("goal_testsession")
        assert goal.status == RunState.GOAL_COMPLETED
        assert "tests passed" in goal.completion_evidence
        assert goal.is_terminal() is True

    def test_recovery_history_recorded(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._get_goal("research it")
        asyncio.run(
            loop._recovery_for_failure(
                exc=RuntimeError("search backend down"),
                component_type="tool",
                component_id="web_search",
                operation="execute",
            )
        )
        store = GoalStore(str(tmp_path / "v5state" / "goals"))
        goal = store.load("goal_testsession")
        assert len(goal.recovery_history) >= 1
        assert goal.recovery_history[0]["strategy"]


class TestCheckpointFailureSurfaced:
    def test_checkpoint_save_failure_is_visible(self, tmp_path, monkeypatch):
        events = []

        class _Sink:
            def __call__(self, event):
                events.append(event)

        loop, v5_state = build_loop(tmp_path, monkeypatch)
        loop.work_event_sink = _Sink()
        loop._checkpoint_save = lambda phase: (_ for _ in ()).throw(
            RuntimeError("disk full")
        )
        asyncio.run(loop._transition_to(v5_state.ACTING, reason="act"))
        assert any(
            event.get("event_type") == "reliability.checkpoint_failed"
            for event in events
        )


class TestRecoveryEvents:
    def test_tool_failure_emits_recovery_event(self, tmp_path, monkeypatch):
        events = []

        class _Sink:
            def __call__(self, event):
                events.append(event)

        loop, _ = build_loop(tmp_path, monkeypatch)
        loop.work_event_sink = _Sink()
        loop._get_goal("do it")
        result = asyncio.run(
            loop._recovery_for_failure(
                exc=RuntimeError("boom"),
                component_type="tool",
                component_id="web_search",
                operation="execute",
                failure_class=FailureClass.TOOL_EXECUTION,
            )
        )
        assert result is not None
        recovery_events = [
            event for event in events
            if event.get("event_type") == "reliability.recovery"
        ]
        assert recovery_events
        assert recovery_events[0]["component_id"] == "web_search"

    def test_repeated_failure_changes_strategy(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        first = asyncio.run(
            loop._recovery_for_failure(
                exc=RuntimeError("boom"),
                component_type="tool",
                component_id="web_search",
                operation="execute",
            )
        )
        second = asyncio.run(
            loop._recovery_for_failure(
                exc=RuntimeError("boom"),
                component_type="tool",
                component_id="web_search",
                operation="execute",
            )
        )
        third = asyncio.run(
            loop._recovery_for_failure(
                exc=RuntimeError("boom"),
                component_type="tool",
                component_id="web_search",
                operation="execute",
            )
        )
        assert first.verdict.value == "recovered"
        assert first.attempts == 1
        assert first.strategy == "retry_with_backoff"
        assert second.attempts == 2
        assert third.verdict.value == "blocked_non_recoverable"
        assert third.strategy == "bounded_retries_exhausted"
        assert third.previous_strategies == ["retry_with_backoff", "retry_with_backoff"]


class TestStallDetection:
    def test_stall_hint_and_budget(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEXUS_LOOP_MAX_STALL_HINTS", "1")
        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._ensure_reliability()
        loop._progress_tracker = ProgressTracker()
        loop._stall_hint_count = 0
        for _ in range(4):
            loop._progress_record(
                "tool_call", signature="web_search:{'q':'x'}", status="success"
            )
        signal, hint = loop._stall_check_and_hint()
        assert signal is not None
        assert signal.kind == "repeated_tool_call"
        assert hint is not None
        assert "STALL_DETECTED" in hint
        signal, hint = loop._stall_check_and_hint()
        assert signal is not None
        assert hint is None

    def test_progress_recording(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._ensure_reliability()
        loop._progress_record("state_change", signature="state:acting", status="ok")
        for _ in range(4):
            loop._progress_record(
                "tool_call", signature="web_search:{'q':'x'}", status="success"
            )
        signal, hint = loop._stall_check_and_hint()
        assert signal is not None
        assert signal.kind == "repeated_tool_call"


class TestReliabilitySnapshot:
    def test_snapshot_fields(self, tmp_path, monkeypatch):
        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._get_goal("mission")
        snapshot = loop.reliability_snapshot()
        assert snapshot["state"] == "initializing"
        assert snapshot["goal"]["goal_id"] == "goal_testsession"
        assert "quarantined" in snapshot

    def test_recovery_result_consumption_persists_intermediate_status_and_advice(
        self, tmp_path, monkeypatch
    ):
        from reliability.recovery import RecoveryResult, RecoveryVerdict

        loop, _ = build_loop(tmp_path, monkeypatch)
        loop._ensure_reliability()
        run_context = start_run_context(
            root=tmp_path,
            session_id="testsession",
            run_id="run-1",
            task_id=None,
            prompt="probe",
            provider="openai",
            model="gpt-4o-mini",
            max_tokens=10,
            voice_mode=False,
            lease_seconds=900,
        )
        loop._current_run_context = run_context
        result = RecoveryResult(
            verdict=RecoveryVerdict.BLOCKED_NON_RECOVERABLE,
            strategy="quarantine",
            next_action="replace the failing component and retry",
        )
        loop._consume_recovery_result(result)
        assert loop._last_recovery_advice == "replace the failing component and retry"
        snapshot = loop.reliability_snapshot()
        assert snapshot["recovery_advice"] == "replace the failing component and retry"
        from nexus.run_context import load_run_context

        persisted = load_run_context(tmp_path, "testsession", "run-1")
        assert persisted.get("status") == "blocked"
        run_context.finish("cancelled", "run.cancelled", "test teardown")