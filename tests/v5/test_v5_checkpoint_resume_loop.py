"""Closed checkpoint -> resume loop.

Before these tests, the checkpoint loop was open in three separate places:

1. ``_checkpoint_resume`` had ZERO callers anywhere in the repo (not even a
   test). Checkpoints were written every state transition and read only as
   read-only "evidence" text pasted into the prompt.
2. ``_checkpoint_save`` recorded ``memory_len`` and ``turn_history_len`` --
   integer COUNTS, not content -- and pulled plan/actions/mental_state only
   from ``runtime.last_result``. The canonical direct loop returns no
   ``plan``/``mental_state``, so a restarted process restored nothing while
   still reporting ``resumed_from_checkpoint``: a resume that silently no-ops.
3. The turn's actual outcome (``verification``/``success``/``error``) was
   never persisted, so a restarted process could not tell finished work from
   work that still needed continuing.

These tests pin the loop closed: state written before a restart must be
readable AND actually restored into a fresh instance after it.
"""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nexus.main_agent.core import NexusLoopV5, V5LoopState, V5TurnContext


def test_checkpoint_save_does_not_block_async_state_transition(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-heartbeat")
    loop.runtime.current_turn = V5TurnContext(
        turn_id="turn-heartbeat", session_id="ckpt-heartbeat", user_input="work"
    )

    def slow_checkpoint(*args, **kwargs):
        time.sleep(0.08)
        return None

    loop._checkpoint_save = slow_checkpoint

    async def run_with_heartbeat():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            await loop._transition_to(V5LoopState.ACTING)
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        return ticks

    assert asyncio.run(run_with_heartbeat()) >= 4


def _seed(loop, *, plan, actions, memory, last_result=None):
    rt = loop.runtime
    rt.plan = plan
    rt.actions = actions
    rt.memory = memory
    if last_result is not None:
        rt.last_result = last_result


def test_checkpoint_persists_state_content_not_just_counts(tmp_path):
    """A checkpoint must carry the real plan/actions, not len() of them."""
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-content")
    _seed(
        loop,
        plan=[{"step": "build the widget"}],
        actions=[{"tool": "terminal", "success": True}],
        memory=[{"role": "user", "content": "the original mission"}],
    )

    path = loop._checkpoint_save(turn_id="run-1", phase="executing")
    assert path, "checkpoint was not written"

    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    assert saved["plan"] == [{"step": "build the widget"}]
    assert saved["actions"] == [{"tool": "terminal", "success": True}]


def test_resume_restores_state_into_a_fresh_process(tmp_path):
    """The headline behaviour: state must survive a restart, not just be
    re-readable. A second NexusLoopV5 over the same root stands in for a
    restarted process."""
    first = NexusLoopV5(str(tmp_path), session_id="ckpt-restart")
    _seed(
        first,
        plan=[{"step": "finish the migration"}],
        actions=[{"tool": "terminal", "success": True}],
        memory=[{"role": "user", "content": "migrate the database"}],
    )
    first._checkpoint_save(turn_id="run-42", phase="executing")

    # Simulated restart: a brand-new instance starts with empty state.
    second = NexusLoopV5(str(tmp_path), session_id="ckpt-restart")
    assert second.runtime.plan == []
    assert second.runtime.memory == []

    resumed = second._checkpoint_resume("run-42")

    assert resumed, "resume returned nothing"
    assert resumed["resumed_from_checkpoint"]
    assert second.runtime.plan == [{"step": "finish the migration"}]
    assert second.runtime.actions == [{"tool": "terminal", "success": True}]
    assert second.runtime.memory == [
        {"role": "user", "content": "migrate the database"}
    ]


def test_resume_rejects_checkpoint_from_another_session(tmp_path):
    first = NexusLoopV5(str(tmp_path), session_id="session-a")
    _seed(
        first,
        plan=[{"step": "private session work"}],
        actions=[{"tool": "terminal", "success": True}],
        memory=[{"role": "user", "content": "private context"}],
    )
    first._checkpoint_save(turn_id="colliding-turn", phase="executing")

    second = NexusLoopV5(str(tmp_path), session_id="session-b")
    assert second._checkpoint_resume("colliding-turn") == {}
    assert second.runtime.plan == []
    assert second.runtime.actions == []
    assert second.runtime.memory == []


def test_concurrent_checkpoint_writers_leave_valid_snapshot(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="checkpoint-concurrency")
    _seed(loop, plan=[{"step": "concurrent"}], actions=[], memory=[])

    with ThreadPoolExecutor(max_workers=6) as pool:
        paths = list(pool.map(
            lambda phase: loop._checkpoint_save("same-turn", phase),
            [f"phase-{index}" for index in range(24)],
        ))

    assert all(paths)
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["turn_id"] == "same-turn"


def test_resume_restores_bounded_turn_history(tmp_path):
    first = NexusLoopV5(str(tmp_path), session_id="ckpt-history")
    first.runtime.turn_history = [V5TurnContext(
        turn_id="turn-1",
        session_id="ckpt-history",
        user_input="inspect the repository",
        input_type="text",
        metadata={"verified": True},
        state=V5LoopState.COMPLETED,
    )]
    first._checkpoint_save(turn_id="run-history", phase="completed")

    second = NexusLoopV5(str(tmp_path), session_id="ckpt-history")
    resumed = second._checkpoint_resume("run-history")

    assert resumed["turn_history"][0]["turn_id"] == "turn-1"
    assert len(second.runtime.turn_history) == 1
    assert second.runtime.turn_history[0].user_input == "inspect the repository"
    assert second.runtime.turn_history[0].metadata == {"verified": True}
    assert second.runtime.turn_history[0].state == V5LoopState.COMPLETED.value


def test_resume_restores_the_prior_outcome_so_progress_can_be_evaluated(tmp_path):
    """A resumed process must know whether the interrupted turn actually
    succeeded and was verified -- otherwise it cannot decide between
    continuing, replanning and stopping."""
    first = NexusLoopV5(str(tmp_path), session_id="ckpt-outcome")
    first.runtime.last_result = {
        "success": False,
        "error": "tests still failing",
        "response": "Two tests remain red.",
        "verification": {"success": False, "evidence_ok": False, "failed_actions": 2},
        "actions": [{"tool": "terminal", "success": False}],
    }
    first._checkpoint_save(turn_id="run-7", phase="verifying")

    second = NexusLoopV5(str(tmp_path), session_id="ckpt-outcome")
    resumed = second._checkpoint_resume("run-7")

    assert resumed["success"] is False
    assert resumed["error"] == "tests still failing"
    assert resumed["verification"]["failed_actions"] == 2
    # And it is rehydrated as real runtime state, not just returned.
    assert second.runtime.last_result["verification"]["failed_actions"] == 2
    assert second.runtime.last_result["success"] is False


def test_resume_of_a_missing_checkpoint_is_a_safe_noop(tmp_path):
    """Resume must degrade quietly: no checkpoint means no restore and no
    exception, so a first-ever run is never blocked by the resume path."""
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-missing")

    assert loop._checkpoint_resume("no-such-run") == {}
    assert loop.runtime.plan == []


def test_resume_survives_a_corrupted_checkpoint_file(tmp_path):
    """A truncated or corrupt checkpoint must not crash a restart."""
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-corrupt")
    _seed(loop, plan=[{"step": "x"}], actions=[], memory=[])
    path = Path(loop._checkpoint_save(turn_id="run-bad", phase="executing"))

    path.write_text("{ this is not valid json", encoding="utf-8")

    assert loop._checkpoint_resume("run-bad") == {}


def test_checkpoint_directory_is_bounded_for_long_running_sessions(tmp_path):
    """Checkpoints are written on every state transition and are never
    cleared in production (`_checkpoint_clear` has no callers). Measured at
    ~34KB/file that is ~134MB per 1000 turns of unbounded growth, so the
    directory must self-prune to the newest N."""
    from nexus.main_agent.checkpoint import MAX_CHECKPOINT_FILES

    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-bound")
    _seed(loop, plan=[{"step": "x"}], actions=[], memory=[])

    overshoot = MAX_CHECKPOINT_FILES + 25
    for turn in range(overshoot):
        loop._checkpoint_save(turn_id=f"run-{turn}", phase="executing")

    files = list((Path(tmp_path) / ".nexus_v5" / "checkpoints").glob("*.json"))
    assert len(files) <= MAX_CHECKPOINT_FILES, (
        f"checkpoint directory grew unbounded: {len(files)} files"
    )

    # Pruning must remove the OLDEST, so the most recent turn still resumes.
    latest = loop._checkpoint_load(f"run-{overshoot - 1}")
    assert latest, "newest checkpoint was pruned"
    assert latest["plan"] == [{"step": "x"}]


def test_checkpoint_list_reads_underscore_phase_from_payload(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-phase")
    _seed(loop, plan=[], actions=[], memory=[])
    loop._checkpoint_save(turn_id="run_with_underscores", phase="timed_out")

    entry = loop._checkpoint_list(limit=1)[0]

    assert entry["turn_id"] == "run_with_underscores"
    assert entry["phase"] == "timed_out"


def test_checkpoint_paths_hash_raw_identity_and_do_not_collide(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-identity")
    _seed(loop, plan=[], actions=[], memory=[])

    first = loop._checkpoint_save(turn_id="run/a", phase="timed/out")
    second = loop._checkpoint_save(turn_id="run_a", phase="timed_out")

    assert first and second and first != second
    assert loop._checkpoint_load("run/a", "timed/out")["turn_id"] == "run/a"
    assert loop._checkpoint_load("run_a", "timed_out")["turn_id"] == "run_a"


def test_explicit_checkpoint_load_rejects_payload_identity_mismatch(tmp_path):
    loop = NexusLoopV5(str(tmp_path), session_id="ckpt-identity-check")
    _seed(loop, plan=[], actions=[], memory=[])
    path = Path(loop._checkpoint_save(turn_id="expected", phase="executing"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["turn_id"] = "different"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert loop._checkpoint_load("expected", "executing") == {}
