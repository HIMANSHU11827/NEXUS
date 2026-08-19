"""Tests for reliability.acceptance: milestone acceptance verifier.

RED -> GREEN: these tests prove the verifier cannot falsely mark a goal
complete. Unmet criteria block the goal (BLOCKED_NON_RECOVERABLE) and list
what is missing; only evidence-backed acceptance flips it to GOAL_COMPLETED.
"""

from reliability.acceptance import (
    ACCEPTANCE_MARKER_PREFIX,
    AcceptanceResult,
    MilestoneAcceptanceVerifier,
)
from reliability.goal import GoalState, GoalStep, GoalStore
from reliability.states import RunState


def make_goal(**kwargs):
    goal = GoalState.create("research topic X and implement it")
    goal.parsed_objective = "research and implement"
    goal.definition_of_done = "working implementation with tests"
    goal.verification_criteria = ["tests pass", "docs updated"]
    goal.plan = [
        GoalStep(
            id="s1",
            description="research",
            tool="web_search",
            status="completed",
            evidence=["searched the web"],
        ),
        GoalStep(
            id="s2",
            description="implement",
            tool="modifying",
            status="pending",
            evidence=["implemented the feature"],
        ),
    ]
    goal.evidence = ["overall evidence present"]
    goal.completion_evidence = []
    for key, value in kwargs.items():
        setattr(goal, key, value)
    return goal


class TestRejection:
    def test_unmet_criteria_blocks(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal()
        # Strip every trace of evidence so no criterion can match.
        goal.evidence = []
        goal.completion_evidence = []
        for step in goal.plan:
            step.evidence = []

        result = verifier.mark_completed_if_verified(goal)

        assert result.accepted is False
        assert goal.status == RunState.BLOCKED_NON_RECOVERABLE
        assert set(result.missing) == {"tests pass", "docs updated"}
        assert any(
            r.get("kind") == "acceptance_rejected" for r in goal.recovery_history
        )

    def test_rejection_lists_partial_missing(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal()
        goal.evidence = []
        goal.completion_evidence = []
        for step in goal.plan:
            step.evidence = []
        # Provide evidence for only one of the two criteria.
        goal.evidence = ["tests pass"]

        result = verifier.verify(goal)

        assert result.accepted is False
        assert result.missing == ["docs updated"]
        assert result.satisfied == ["tests pass"]
        assert goal.status != RunState.GOAL_COMPLETED


class TestAcceptance:
    def test_all_criteria_satisfied_accepts(self):
        verifier = MilestoneAcceptanceVerifier()
        # "tests pass" matches goal.evidence; "docs updated" is a substring of
        # the completion_evidence entry.
        goal = make_goal(
            evidence=["tests pass reported by runner"],
            completion_evidence=["docs updated in README"],
        )

        result = verifier.mark_completed_if_verified(goal)

        assert result.accepted is True
        assert goal.status == RunState.GOAL_COMPLETED
        assert any(
            e.startswith(ACCEPTANCE_MARKER_PREFIX) for e in goal.completion_evidence
        )

    def test_case_insensitive_match(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(
            evidence=["TESTS PASS"],
            completion_evidence=["DOCS UPDATED in changelog"],
        )
        result = verifier.verify(goal)
        assert result.accepted is True

    def test_step_evidence_counts(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(
            evidence=[],
            completion_evidence=[],
        )
        # Move the evidence onto the step objects.
        goal.plan[0].evidence = ["tests pass on ci"]
        goal.plan[1].evidence = ["docs updated via docstring"]
        result = verifier.verify(goal)
        assert result.accepted is True


class TestPersistence:
    def test_persists_accepted_state(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(
            evidence=["tests pass reported by runner"],
            completion_evidence=["docs updated in README"],
        )
        store.save(goal)

        verifier.mark_completed_if_verified(goal, store=store)

        loaded = store.load(goal.goal_id)
        assert loaded is not None
        assert loaded.status == RunState.GOAL_COMPLETED
        assert any(
            e.startswith(ACCEPTANCE_MARKER_PREFIX) for e in loaded.completion_evidence
        )

    def test_persists_rejected_state(self, tmp_path):
        store = GoalStore(str(tmp_path / "goals"))
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal()
        goal.goal_id = "goal_blocked_persist"
        goal.evidence = []
        goal.completion_evidence = []
        for step in goal.plan:
            step.evidence = []
        store.save(goal)

        verifier.mark_completed_if_verified(goal, store=store)

        loaded = store.load("goal_blocked_persist")
        assert loaded is not None
        assert loaded.status == RunState.BLOCKED_NON_RECOVERABLE
        assert any(
            r.get("kind") == "acceptance_rejected" for r in loaded.recovery_history
        )
        # The rejected goal must NOT be silently marked complete on disk.
        assert loaded.status != RunState.GOAL_COMPLETED


class TestEmptyCriteria:
    def test_empty_criteria_all_completed(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(verification_criteria=[])
        for step in goal.plan:
            step.status = "completed"

        result = verifier.verify(goal)

        assert result.accepted is True

    def test_empty_criteria_incomplete_steps_rejected(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(verification_criteria=[])
        # s2 remains "pending" from make_goal.

        result = verifier.verify(goal)

        assert result.accepted is False
        assert "not-all-steps-completed" in result.missing

    def test_empty_criteria_terminal_failed_rejected(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(verification_criteria=[])
        for step in goal.plan:
            step.status = "completed"
        goal.status = RunState.FAILED

        result = verifier.verify(goal)

        assert result.accepted is False
        assert "status-terminal-failed" in result.missing


class TestGuard:
    def test_verify_none_goal(self):
        verifier = MilestoneAcceptanceVerifier()
        result = verifier.verify(None)
        assert isinstance(result, AcceptanceResult)
        assert result.accepted is False

    def test_verify_malformed_goal(self):
        verifier = MilestoneAcceptanceVerifier()

        class Bad:  # no goal-like attributes at all
            pass

        result = verifier.verify(Bad())
        assert isinstance(result, AcceptanceResult)
        assert result.accepted is False

    def test_mark_malformed_goal_never_raises(self):
        verifier = MilestoneAcceptanceVerifier()
        events = []

        class Bad:
            pass

        result = verifier.mark_completed_if_verified(Bad(), sink=events.append)
        assert isinstance(result, AcceptanceResult)
        assert result.accepted is False
        # A single mission.acceptance event was still emitted.
        assert len(events) == 1
        assert events[0]["event_type"] == "mission.acceptance"
        assert events[0]["accepted"] is False

    def test_criteria_non_iterable_never_raises(self):
        verifier = MilestoneAcceptanceVerifier()

        class Weird:
            verification_criteria = 42  # not a list
            plan = None
            evidence = None
            completion_evidence = None
            status = RunState.EXECUTING

        result = verifier.verify(Weird())
        assert isinstance(result, AcceptanceResult)
        # Empty criteria path: no plan steps => not all completed => rejected.
        assert result.accepted is False


class TestMatchingStrictness:
    """Guards against the false-positive substring match bug.

    A naive ``criterion in evidence`` check accepted 'done' on 'abandOned'
    and 'api' on 'rApiD'. Matching must be whole-word only.
    """

    def test_substring_overlap_does_not_falsely_satisfy(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(
            verification_criteria=["done", "api integrated"],
            evidence=[],
            completion_evidence=[],
        )
        for step in goal.plan:
            step.evidence = ["the work was abandOned", "we used rApiD cache"]
        result = verifier.verify(goal)
        assert result.accepted is False
        assert "done" in result.missing
        assert "api integrated" in result.missing

    def test_whole_word_match_satisfies(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(
            verification_criteria=["api integrated", "tests pass"],
            evidence=[],
            completion_evidence=[],
        )
        for step in goal.plan:
            step.evidence = ["the API integrated cleanly", "the tests pass now"]
        result = verifier.verify(goal)
        assert result.accepted is True

    def test_blank_criterion_is_never_auto_satisfied(self):
        verifier = MilestoneAcceptanceVerifier()
        goal = make_goal(
            verification_criteria=["", "real work"],
            evidence=["real work done"],
            completion_evidence=[],
        )
        result = verifier.verify(goal)
        # The empty criterion must count as missing, not silently pass.
        assert "" in result.missing
        assert result.accepted is False
