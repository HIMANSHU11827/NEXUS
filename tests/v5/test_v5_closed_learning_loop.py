"""Closed-learning regression tests.

Before these, ``MetaLearningLayer.record_experience`` had no production
caller: ``_meta_learning_optimize`` read ``strategy_performance`` on every
turn, but only the test-suite ever wrote to it. The learning loop therefore
had a live read end and a dead write end, and no amount of real execution
could ever change future behaviour.

These tests assert the loop is genuinely closed:
  experience -> evaluate -> store -> persist -> retrieve -> influence.
"""

import asyncio
import json
from pathlib import Path

from nexus.main_agent.core import NexusLoopV5
from nexus.main_agent.meta import MetaLearningLayer


def _run(coro):
    return asyncio.run(coro)


def test_finished_turn_records_a_real_experience(tmp_path):
    """A completed turn must contribute one experience to the meta store."""
    loop = NexusLoopV5(str(tmp_path), session_id="learn-test")
    meta = loop.meta_learning
    assert meta is not None
    before = len(meta.experience_buffer)

    _run(loop._evolve_record_experience("build the widget", True))

    assert len(meta.experience_buffer) == before + 1
    recorded = meta.experience_buffer[-1]
    assert recorded.context["task"] == "build the widget"
    # Strategy performance is the table _select_strategy actually reads.
    assert recorded.strategy in meta.strategy_performance
    assert meta.strategy_performance[recorded.strategy][-1] == recorded.outcome


def test_outcome_is_graded_by_verification_not_just_success(tmp_path):
    """An unverified success must score lower than a verified one, so a
    strategy that only *looks* finished cannot outrank an evidenced one."""
    loop = NexusLoopV5(str(tmp_path), session_id="grade-test")

    loop._last_run_verified = True
    _run(loop._evolve_record_experience("verified work", True))
    verified_score = loop.meta_learning.experience_buffer[-1].outcome

    loop._last_run_verified = False
    _run(loop._evolve_record_experience("unverified work", True))
    unverified_score = loop.meta_learning.experience_buffer[-1].outcome

    _run(loop._evolve_record_experience("failed work", False))
    failed_score = loop.meta_learning.experience_buffer[-1].outcome

    assert verified_score > unverified_score > failed_score
    assert failed_score == 0.0


def test_recorded_experience_persists_and_is_read_back(tmp_path):
    """The loop must close across process boundaries: what one run learns a
    later run must actually load from disk."""
    loop = NexusLoopV5(str(tmp_path), session_id="persist-test")
    loop._last_run_verified = True
    _run(loop._evolve_record_experience("durable lesson", True))

    state_file = Path(tmp_path) / ".nexus_v5_meta_learning.json"
    assert state_file.exists(), "experience was not persisted to disk"
    saved = json.loads(state_file.read_text())
    assert saved["strategy_performance"], "no strategy performance was written"

    # A fresh layer (simulating a restarted process) must see the lesson.
    reloaded = MetaLearningLayer(str(tmp_path))
    assert reloaded.strategy_performance == saved["strategy_performance"]


def test_recorded_experience_influences_the_next_strategy_choice(tmp_path):
    """Storage is not learning. Prove the stored outcomes actually change what
    ``optimize()`` recommends on a later turn."""
    loop = NexusLoopV5(str(tmp_path), session_id="influence-test")
    meta = loop.meta_learning

    # A fresh store recommends nothing: there is no evidence yet.
    assert "recommended_strategy" not in _run(meta.optimize(loop.runtime))

    # Feed real outcomes: a weak strategy and a strong one.
    for _ in range(3):
        meta.record_experience(_experience("weak_strategy", 0.1))
    for _ in range(3):
        meta.record_experience(_experience("strong_strategy", 1.0))

    recommendation = _run(meta.optimize(loop.runtime))
    assert recommendation["recommended_strategy"] == "strong_strategy"
    assert recommendation["strategy_confidence"] == 1.0


def _experience(strategy: str, outcome: float):
    from datetime import datetime

    from nexus.main_agent.meta import Experience

    return Experience(
        task_id=f"task-{strategy}",
        strategy=strategy,
        outcome=outcome,
        timestamp=datetime.now(),
    )


def test_recording_never_breaks_a_turn(tmp_path):
    """Learning is best-effort: a broken meta store must not fail the run."""
    loop = NexusLoopV5(str(tmp_path), session_id="safe-test")

    class Broken:
        def record_experience(self, _experience):
            raise RuntimeError("meta store is down")

    loop._meta_learning = Broken()
    # Must not raise.
    _run(loop._evolve_record_experience("resilient", True))
