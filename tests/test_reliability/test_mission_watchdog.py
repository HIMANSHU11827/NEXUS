"""Tests for reliability.mission_watchdog — mission heartbeat / stuck recovery.

RED->GREEN: these assert the contract described in the P0-3 gap
("a live lease must not hide a permanently stalled milestone; the watchdog
requeues exactly once and records why").
"""

import os
import tempfile

from reliability.goal import GoalState, GoalStep, GoalStore
from reliability.states import RunState
from reliability.mission_watchdog import (
    MissionWatchdog,
    StuckStep,
    DEFAULT_STALL_TIMEOUT_S,
)


def make_goal(clock, *, stalled_s=0.0, step_status="active"):
    goal = GoalState.create("ship the report")
    goal.status = RunState.EXECUTING
    goal.last_progress_at = clock() - stalled_s
    goal.plan = [
        GoalStep(id="s1", description="write report", status=step_status),
    ]
    return goal


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class TestFindStuck:
    def test_active_step_past_timeout_is_stuck(self):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S + 10)
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        stuck = wd.find_stuck_steps(goal)
        assert len(stuck) == 1
        assert stuck[0].step_id == "s1"
        assert stuck[0].stalled_for_s >= DEFAULT_STALL_TIMEOUT_S

    def test_recent_progress_is_not_stuck(self):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=5.0)
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        assert wd.find_stuck_steps(goal) == []

    def test_terminal_goal_never_stuck(self):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=10_000)
        goal.status = RunState.GOAL_COMPLETED
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        assert wd.find_stuck_steps(goal) == []

    def test_completed_step_not_stuck(self):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=10_000, step_status="completed")
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        assert wd.find_stuck_steps(goal) == []


class TestRecoverExactlyOnce:
    def test_requeue_sets_step_pending_and_records_reason(self):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S + 10)
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        stuck = wd.find_stuck_steps(goal)[0]
        action = wd.recover_step(goal, stuck, requeue=False)
        assert action.action == "requeued"
        assert action.recovered is True
        assert goal.plan[0].status == "pending"
        assert any(
            r.get("kind") == "watchdog_requeue" for r in goal.recovery_history
        )

    def test_second_recovery_is_skipped_not_duplicated(self):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S + 10)
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        s1 = wd.find_stuck_steps(goal)[0]
        a1 = wd.recover_step(goal, s1, requeue=False)
        s2 = StuckStep(
            goal_id=goal.goal_id,
            step_id="s1",
            last_progress_at=clock() - 9999,
            stalled_for_s=9999,
            goal_state="executing",
            reason="still stuck",
        )
        a2 = wd.recover_step(goal, s2, requeue=False)
        assert a1.action == "requeued"
        assert a2.action == "skipped_already_recovered"
        assert a2.recovered is False

    def test_exactly_once_survives_restart_via_ledger(self, tmp_path):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S + 10)
        ledger = str(tmp_path / "ledger.json")
        wd1 = MissionWatchdog(
            clock=clock,
            stall_timeout_s=DEFAULT_STALL_TIMEOUT_S,
            ledger_path=ledger,
        )
        stuck = wd1.find_stuck_steps(goal)[0]
        wd1.recover_step(goal, stuck, requeue=False)

        # New watchdog instance simulates a process restart reading the ledger.
        wd2 = MissionWatchdog(
            clock=clock,
            stall_timeout_s=DEFAULT_STALL_TIMEOUT_S,
            ledger_path=ledger,
        )
        stuck2 = StuckStep(
            goal_id=goal.goal_id,
            step_id="s1",
            last_progress_at=clock() - 9999,
            stalled_for_s=9999,
            goal_state="executing",
            reason="still stuck after restart",
        )
        action = wd2.recover_step(goal, stuck2, requeue=False)
        assert action.action == "skipped_already_recovered"
        assert goal.plan[0].status == "pending"  # not reset a 2nd time


class TestRecoverStoreFailure:
    def test_store_update_failure_does_not_burn_budget_or_false_report(self, tmp_path):
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S + 10)
        ledger = str(tmp_path / "ledger.json")

        class FailStore:
            def update(self, goal_id, mutator):
                raise RuntimeError("disk full")

        wd = MissionWatchdog(
            store=FailStore(),
            clock=clock,
            stall_timeout_s=DEFAULT_STALL_TIMEOUT_S,
            ledger_path=ledger,
        )
        stuck = wd.find_stuck_steps(goal)[0]
        action = wd.recover_step(goal, stuck, requeue=True)
        # Must NOT claim success; step must remain active (not silently lost).
        assert action.action == "requeue_failed"
        assert action.recovered is False
        assert goal.plan[0].status == "active"
        # Ledger must NOT be incremented, so a later healthy recovery still works.
        wd2 = MissionWatchdog(
            store=None,
            clock=clock,
            stall_timeout_s=DEFAULT_STALL_TIMEOUT_S,
            ledger_path=ledger,
        )
        stuck2 = StuckStep(
            goal_id=goal.goal_id, step_id="s1",
            last_progress_at=clock() - 9999, stalled_for_s=9999,
            goal_state="executing", reason="still stuck",
        )
        a2 = wd2.recover_step(goal, stuck2, requeue=False)
        assert a2.action == "requeued"  # budget preserved -> can still recover
        assert goal.plan[0].status == "pending"

    def test_sweep_requeues_stuck_goal_from_store(self, tmp_path):
        clock = FakeClock()
        store = GoalStore(root_dir=str(tmp_path / "goals"))
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S + 10)
        store.save(goal)

        wd = MissionWatchdog(
            store=store,
            clock=clock,
            stall_timeout_s=DEFAULT_STALL_TIMEOUT_S,
        )
        actions = wd.sweep()
        assert len(actions) == 1
        assert actions[0].action == "requeued"

        reloaded = store.load(goal.goal_id)
        assert reloaded.plan[0].status == "pending"


class TestFindStuckBoundaryAndPerStep:
    def test_exactly_at_timeout_is_stuck(self):
        # >= boundary: a step stalled exactly at the timeout must be flagged.
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S)
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        assert len(wd.find_stuck_steps(goal)) == 1

    def test_per_step_progress_used_over_goal(self):
        # A heartbeating goal (recent goal-level progress) but one wedged step
        # (stale per-step last_progress_at) must still be flagged on that step.
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=5.0)  # goal progressed recently
        goal.plan[0].last_progress_at = clock() - (DEFAULT_STALL_TIMEOUT_S + 10)
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        stuck = wd.find_stuck_steps(goal)
        assert len(stuck) == 1
        assert stuck[0].step_id == "s1"

    def test_blocked_non_recoverable_goal_not_swept(self):
        # An acceptance-rejected goal is resumable by design, not a stalled
        # runner -- the watchdog must not treat it as stuck.
        clock = FakeClock()
        goal = make_goal(clock, stalled_s=10_000)
        goal.status = RunState.BLOCKED_NON_RECOVERABLE
        wd = MissionWatchdog(clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S)
        assert wd.find_stuck_steps(goal) == []


class TestCrossProcessLedger:
    def test_recovery_uses_durable_ledger_path(self, tmp_path):
        # Exercises the cross-process lock path (file-based ledger). The lock
        # must not raise and exactly-once must still hold across "restarts".
        clock = FakeClock()
        ledger = str(tmp_path / "watchdog_ledger.json")
        goal = make_goal(clock, stalled_s=DEFAULT_STALL_TIMEOUT_S + 10)

        wd1 = MissionWatchdog(
            clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S, ledger_path=ledger
        )
        a1 = wd1.recover_step(goal, wd1.find_stuck_steps(goal)[0], requeue=False)
        assert a1.action == "requeued"

        wd2 = MissionWatchdog(
            clock=clock, stall_timeout_s=DEFAULT_STALL_TIMEOUT_S, ledger_path=ledger
        )
        a2 = wd2.recover_step(
            goal,
            StuckStep(
                goal_id=goal.goal_id, step_id="s1",
                last_progress_at=clock() - 9999, stalled_for_s=9999,
                goal_state="executing", reason="post-restart",
            ),
            requeue=False,
        )
        assert a2.action == "skipped_already_recovered"
        assert goal.plan[0].status == "pending"
