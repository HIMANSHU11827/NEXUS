"""Tests for reliability.goal: durable GoalState persistence."""

import time

from reliability.goal import GoalState, GoalStep, GoalStore
from reliability.states import RunState


def make_goal(**kwargs):
    goal = GoalState.create("research topic X and implement it")
    goal.parsed_objective = "research and implement"
    goal.definition_of_done = "working implementation with tests"
    goal.verification_criteria = ["tests pass", "docs updated"]
    goal.plan = [
        GoalStep(id="s1", description="research", tool="web_search", status="completed"),
        GoalStep(id="s2", description="implement", tool="modifying", status="pending"),
    ]
    for key, value in kwargs.items():
        setattr(goal, key, value)
    return goal


class TestGoalState:
    def test_recount_steps(self):
        goal = make_goal()
        goal.recount_steps()
        assert goal.completed_steps == 1
        assert goal.pending_steps == 1

    def test_touch_increments_version(self):
        goal = make_goal()
        before = goal.version
        time.sleep(0.01)
        goal.touch(progress=True)
        assert goal.version == before + 1
        assert goal.last_progress_at >= goal.created_at

    def test_is_terminal(self):
        goal = make_goal()
        assert goal.is_terminal() is False
        goal.status = RunState.GOAL_COMPLETED
        assert goal.is_terminal() is True
        goal.status = RunState.BLOCKED_NON_RECOVERABLE
        assert goal.is_terminal() is False

    def test_round_trip(self):
        goal = make_goal()
        restored = GoalState.from_dict(goal.to_dict())
        assert restored.goal_id == goal.goal_id
        assert restored.user_request == goal.user_request
        assert len(restored.plan) == 2
        assert restored.plan[0].status == "completed"
        assert restored.plan[1].tool == "modifying"
        assert restored.verification_criteria == goal.verification_criteria

    def test_from_dict_tolerant(self):
        restored = GoalState.from_dict({"user_request": "hi"})
        assert restored.user_request == "hi"
        assert restored.goal_id

    def test_step_round_trip(self):
        step = GoalStep(id="s9", description="do", tool="terminal", params={"cmd": "ls"}, attempts=2)
        restored = GoalStep.from_dict(step.to_dict())
        assert restored.params == {"cmd": "ls"}
        assert restored.attempts == 2


class TestGoalStore:
    def test_save_load(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        goal = make_goal()
        store.save(goal)
        loaded = store.load(goal.goal_id)
        assert loaded is not None
        assert loaded.user_request == goal.user_request
        assert loaded.plan_version == goal.plan_version

    def test_missing_goal(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        assert store.load("does_not_exist") is None

    def test_update_with_mutator(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        goal = make_goal()
        store.save(goal)
        updated = store.update(goal.goal_id, lambda g: g.plan[1].__setattr__("status", "active"))
        assert updated is not None
        assert updated.plan[1].status == "active"
        assert updated.version == goal.version + 1

    def test_list_active_excludes_terminal(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        active = make_goal()
        done = make_goal()
        done.status = RunState.GOAL_COMPLETED
        blocked = make_goal()
        blocked.status = RunState.BLOCKED_NON_RECOVERABLE
        for goal in (active, done, blocked):
            store.save(goal)
        ids = store.active_goal_ids()
        assert active.goal_id in ids
        assert done.goal_id not in ids
        assert blocked.goal_id in ids

    def test_record_recovery(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        goal = make_goal()
        store.save(goal)
        store.record_recovery(
            goal.goal_id,
            failure_id="f1",
            strategy="backoff_retry",
            verdict="recovered",
            detail="ok",
            attempt_count=2,
        )
        loaded = store.load(goal.goal_id)
        assert len(loaded.recovery_history) == 1
        assert loaded.recovery_history[0]["strategy"] == "backoff_retry"

    def test_record_blocker(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        goal = make_goal()
        store.save(goal)
        store.record_blocker(
            goal.goal_id, failure_id="f1", reason="no creds", next_action="provide api key"
        )
        loaded = store.load(goal.goal_id)
        assert loaded.blockers[0]["next_action"] == "provide api key"

    def test_delete(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        goal = make_goal()
        store.save(goal)
        store.delete(goal.goal_id)
        assert store.load(goal.goal_id) is None

    def test_corrupt_goal_tolerated(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        goal = make_goal()
        store.save(goal)
        path = tmp_path / "goals" / f"{goal.goal_id}.json"
        path.write_text("{broken", encoding="utf-8")
        assert store.load(goal.goal_id) is None
        assert store.list_active() == []