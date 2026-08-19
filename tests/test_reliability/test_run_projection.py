"""Tests for reliability.run_projection -- the unified durable run projection.

RED->GREEN: these assert the contract described in the P0-2 gap
('Prevents V5, queue, and Hive from disagreeing about progress; restart/replay
shows identical goal/step/attempt state across surfaces.').
"""

from reliability.goal import GoalState, GoalStep
from reliability.run_projection import (
    RunProjection,
    RunProjectionStore,
    build_projection,
    reconcile,
)
from reliability.states import RunState


def make_goal(*, status=RunState.EXECUTING):
    goal = GoalState.create("implement feature X with tests")
    goal.status = status
    goal.plan = [
        GoalStep(id="s1", description="research", status="completed", attempts=1),
        GoalStep(id="s2", description="implement", status="active", attempts=2),
    ]
    return goal


class TestBuildProjection:
    def test_build_from_two_steps(self):
        goal = make_goal()
        proj = build_projection(goal, run_id="run-1", source_surface="v5")
        assert proj.goal_id == goal.goal_id
        assert proj.run_id == "run-1"
        assert proj.source_surface == "v5"
        assert proj.canonical_status == RunState.EXECUTING
        assert len(proj.step_states) == 2
        assert proj.step_states[0] == {
            "step_id": "s1",
            "status": "completed",
            "attempts": 1,
        }
        assert proj.step_states[1] == {
            "step_id": "s2",
            "status": "active",
            "attempts": 2,
        }

    def test_build_uses_goal_version_and_progress_time(self):
        goal = make_goal()
        goal.version = 7
        goal.last_progress_at = 1234.5
        proj = build_projection(goal, run_id="run-1", source_surface="hive")
        assert proj.version == 7
        assert proj.last_progress_at == 1234.5
        assert proj.source_surface == "hive"

    def test_build_tolerates_none_goal(self):
        proj = build_projection(None, run_id="run-x", source_surface="queue")
        assert isinstance(proj, RunProjection)
        assert proj.step_states == []
        assert proj.canonical_status == RunState.INITIALIZING


class TestReconcile:
    def _proj(self, *, run_id="run-1", goal_id="g1", surface="v5",
              status=RunState.EXECUTING, steps=None, version=1):
        return RunProjection(
            goal_id=goal_id,
            run_id=run_id,
            canonical_status=status,
            step_states=steps if steps is not None else [],
            version=version,
            source_surface=surface,
        )

    def test_reconcile_picks_more_progressed_step_and_reports(self):
        a = self._proj(
            surface="v5",
            status=RunState.EXECUTING,
            steps=[{"step_id": "s1", "status": "completed", "attempts": 2}],
        )
        b = self._proj(
            surface="queue",
            status=RunState.EXECUTING,
            steps=[{"step_id": "s1", "status": "active", "attempts": 1}],
        )
        result = reconcile([a, b])
        s1 = next(s for s in result.step_states if s["step_id"] == "s1")
        # completed is more progressed than active -> wins.
        assert s1["status"] == "completed"
        assert s1["attempts"] == 2
        assert any("step s1" in d for d in result.disagreements)

    def test_reconcile_terminal_wins_over_stale_executing(self):
        executing = self._proj(
            surface="v5",
            status=RunState.EXECUTING,
            steps=[
                {"step_id": "s1", "status": "completed", "attempts": 1},
                {"step_id": "s2", "status": "completed", "attempts": 1},
            ],
            version=9,
        )
        completed = self._proj(
            surface="queue",
            status=RunState.GOAL_COMPLETED,
            steps=[],
            version=1,
        )
        result = reconcile([executing, completed])
        assert result.canonical_status == RunState.GOAL_COMPLETED
        assert result.run_id == "run-1"

    def test_reconcile_prefers_more_completed_when_no_terminal(self):
        few = self._proj(
            surface="v5",
            status=RunState.EXECUTING,
            steps=[{"step_id": "s1", "status": "completed", "attempts": 1}],
        )
        many = self._proj(
            surface="hive",
            status=RunState.EXECUTING,
            steps=[
                {"step_id": "s1", "status": "completed", "attempts": 1},
                {"step_id": "s2", "status": "completed", "attempts": 1},
            ],
            version=1,
        )
        result = reconcile([few, many])
        # both non-terminal -> the one with more completed steps wins the status
        # (still EXECUTING), and merged step_states contain both steps.
        assert result.canonical_status == RunState.EXECUTING
        assert len(result.step_states) == 2

    def test_never_raise_on_empty(self):
        result = reconcile([])
        assert isinstance(result, RunProjection)
        assert result.canonical_status == RunState.INITIALIZING
        assert result.disagreements  # explains why it is empty

    def test_never_raise_on_malformed(self):
        # garbage entries must be skipped, not raised.
        result = reconcile([None, "not-a-projection", 42])
        assert isinstance(result, RunProjection)
        assert result.canonical_status == RunState.INITIALIZING


class TestRunProjectionStore:
    def test_round_trip(self, tmp_path):
        store = RunProjectionStore(str(tmp_path / "proj"))
        goal = make_goal()
        proj = build_projection(goal, run_id="run-1", source_surface="v5")
        store.save(proj)
        loaded = store.load("run-1", "v5")
        assert loaded is not None
        assert loaded.step_states == proj.step_states
        assert loaded.canonical_status == proj.canonical_status
        assert loaded.goal_id == proj.goal_id

    def test_missing_run_returns_none(self, tmp_path):
        store = RunProjectionStore(str(tmp_path / "proj"))
        assert store.load("nope", "v5") is None

    def test_record_surface_state_heartbeat(self, tmp_path):
        store = RunProjectionStore(str(tmp_path / "proj"))
        stored = store.record_surface_state(
            "run-2",
            goal_id="g2",
            surface="queue",
            canonical_status="executing",  # legacy V5 string
            step_states=[
                {"step_id": "s1", "status": "active", "attempts": 3},
            ],
            version=4,
        )
        assert stored.canonical_status == RunState.EXECUTING
        loaded = store.load("run-2", "queue")
        assert loaded is not None
        assert loaded.source_surface == "queue"
        assert loaded.step_states[0]["attempts"] == 3
        assert loaded.version == 4

    def test_corrupt_projection_tolerated(self, tmp_path):
        store = RunProjectionStore(str(tmp_path / "proj"))
        proj = build_projection(make_goal(), run_id="run-3", source_surface="v5")
        store.save(proj)
        path = tmp_path / "proj" / "run-3__v5.json"
        path.write_text("{broken", encoding="utf-8")
        assert store.load("run-3", "v5") is None

    def test_surfaces_keyed_separately_and_reconciled(self, tmp_path):
        """CRITICAL fix: each surface persists under (run_id, surface) so
        concurrent heartbeats don't clobber each other; load_reconciled
        merges them the way reconcile() expects."""
        store = RunProjectionStore(str(tmp_path / "proj"))
        store.record_surface_state(
            "run-9", goal_id="g9", surface="v5", canonical_status="executing",
            step_states=[{"step_id": "s1", "status": "completed", "attempts": 1}],
        )
        store.record_surface_state(
            "run-9", goal_id="g9", surface="queue", canonical_status="executing",
            step_states=[{"step_id": "s1", "status": "active", "attempts": 3}],
        )
        # Each surface survives independently (no overwrite).
        assert store.load("run-9", "v5").step_states[0]["attempts"] == 1
        assert store.load("run-9", "queue").step_states[0]["attempts"] == 3
        # And the reconciled view merges across surfaces (max attempts).
        merged = store.load_reconciled("run-9")
        assert merged is not None
        assert merged.source_surface == "reconciled"
        assert merged.step_states[0]["attempts"] == 3


class TestReconcileIdentityGuard:
    """Guard: reconcile must NOT merge projections from different goals."""

    def _proj(self, goal_id, run_id, status=RunState.EXECUTING, surface="v5"):
        return RunProjection(
            goal_id=goal_id,
            run_id=run_id,
            canonical_status=status,
            step_states=[],
            source_surface=surface,
        )

    def test_different_goals_refused(self):
        a = self._proj("goal-A", "run-1", RunState.GOAL_COMPLETED)
        b = self._proj("goal-B", "run-1", RunState.EXECUTING)
        merged = reconcile([a, b])
        assert merged.goal_id == ""
        assert any("distinct goal/run" in d for d in merged.disagreements)

    def test_same_goal_run_reconciled(self):
        a = self._proj("goal-A", "run-1", RunState.EXECUTING, "v5")
        b = self._proj("goal-A", "run-1", RunState.EXECUTING, "queue")
        merged = reconcile([a, b])
        assert merged.goal_id == "goal-A"
        assert merged.run_id == "run-1"
