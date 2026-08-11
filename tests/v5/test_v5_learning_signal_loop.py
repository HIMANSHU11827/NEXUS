"""Closed in-loop learning: per-turn signals must be collected AND injected.

`orchestrators/v5/learning.py` had a full per-turn learning-signal collector
(`_collect_turn_signals` -> `runtime.failures` / `runtime.learnings` +
replays.jsonl) but it had ZERO callers anywhere in the codebase, and the
signals it wrote were never read back into the prompt. So the loop was
write-only: past tool failures and reflections never influenced future
behavior -- exactly the mission's "learning -> but no future application".

These tests pin both halves closed without standing up the whole runtime:
1. A turn result containing a failed action is recorded into
   `runtime.failures` when `_collect_turn_signals` runs.
2. `learning_signals_digest` renders those signals as a model-readable block
   (the read half that was missing).
3. `_collect_turn_signals` is actually invoked from the live turn path in
   `core.py` (not just defined) -- verified against the source.
4. The injected digest reaches the context summary the model sees, via the
   same code path `_merge_memory_context` uses.
"""

import re

import pytest

from orchestrators.v5.learning import V5Learning


def _loop_with_runtime():
    """A minimal V5Learning stand-in with a real runtime object."""
    loop = V5Learning.__new__(V5Learning)
    loop.session_id = "learn-test"
    loop._current_turn_id = "t1"
    loop.logger = __import__("logging").getLogger("test-learn")

    class _RT:
        failures = []
        learnings = []

    loop.runtime = _RT()
    return loop


def _fake_result_with_failure():
    return {
        "success": False,
        "actions": [
            {
                "name": "terminal",
                "description": "rm -rf important_dir",
                "success": False,
                "error": "permission denied: read-only filesystem",
            }
        ],
        "reflection": {
            "root_causes": ["the directory was mounted read-only"],
            "improvements": ["check mount flags before recursive delete"],
            "counterfactuals": ["use a non-destructive move instead"],
        },
    }


@pytest.mark.asyncio
async def test_collect_turn_signals_records_failures_and_learnings():
    """The per-turn collector must actually populate runtime.failures and
    runtime.learnings from a turn result that contains a failed action."""
    loop = _loop_with_runtime()
    result = _fake_result_with_failure()

    await loop._collect_turn_signals(None, result, None)

    assert len(loop.runtime.failures) == 1, loop.runtime.failures
    assert loop.runtime.failures[0]["type"] == "tool_failure"
    assert "permission denied" in loop.runtime.failures[0]["error"]
    # Reflections are deduplicated and capped.
    assert len(loop.runtime.learnings) == 3, loop.runtime.learnings
    assert all(l["type"] == "reflection" for l in loop.runtime.learnings)


def test_learning_signals_digest_renders_collected_state():
    """The read half: digest must surface collected failures/reflections so
    the model can avoid repeating known-bad actions."""
    loop = _loop_with_runtime()
    loop.runtime.failures.append({
        "type": "tool_failure",
        "description": "rm -rf important_dir",
        "error": "permission denied",
    })
    loop.runtime.learnings.append({
        "type": "reflection",
        "signal": "check mount flags before recursive delete",
    })

    digest = loop.learning_signals_digest()
    assert "Known tool failures" in digest
    assert "rm -rf important_dir" in digest
    assert "Past reflections" in digest
    assert "check mount flags" in digest


def test_digest_is_empty_when_nothing_collected():
    loop = _loop_with_runtime()
    assert loop.learning_signals_digest() == ""


def test_collector_is_wired_into_the_live_turn_path():
    """The collector must be CALLED from core.py's turn finalization, not
    merely defined -- otherwise the signals stay write-only."""
    import orchestrators.v5.core as core_mod

    text = open(core_mod.__file__, encoding="utf-8", errors="ignore").read()
    # The call site sits right after the existing replay-log call and mirrors
    # its defensive `getattr(..., None)` + `callable` guard.
    assert "_collect_turn_signals" in text, "collector referenced somewhere"
    # It must be AWAITED inside the turn path (not just the def in learning.py).
    assert re.search(
        r"await\s+collect\(perceived,\s*result,\s*turn\)", text
    ) or "await collect(perceived, result, turn)" in text, (
        "collector is not awaited in the live turn path"
    )


def test_learning_digest_is_injected_after_memory_merge():
    """The same code path that merges memory must also append the learning
    digest to the context summary the model receives."""
    import orchestrators.v5.core as core_mod

    text = open(core_mod.__file__, encoding="utf-8", errors="ignore").read()
    # The injection must follow the direct-loop memory merge. The merge helper
    # owns channel selection and budgeting, so this test intentionally pins
    # the integration boundary instead of its internal list implementation.
    direct_loop_idx = text.find('ctx = turn.metadata.get("_memory_context")')
    merge_idx = text.find(
        "context_summary = self._merge_memory_context(", direct_loop_idx
    )
    assert merge_idx != -1, "memory merge block not found"
    learn_idx = text.find("learning_signals_digest")
    assert learn_idx != -1 and learn_idx > merge_idx, (
        "learning digest must be injected after the memory merge"
    )
    assert "[LEARNING]" in text, "injected block must be tagged [LEARNING]"
    assert "[SELF-EVOLUTION]" in text, "evolution block must be tagged [SELF-EVOLUTION]"


def test_replay_is_logged_exactly_once_per_turn(monkeypatch, tmp_path):
    """The reviewer caught a real regression: `_collect_turn_signals` calls
    `_log_turn_replay` internally, so the live turn path must NOT also call
    it directly -- otherwise the replay JSONL is written twice per turn."""
    import orchestrators.v5.core as core_mod
    text = open(core_mod.__file__, encoding="utf-8", errors="ignore").read()
    direct_calls = text.count("log_replay = getattr(self, \"_log_turn_replay\", None)")
    assert direct_calls == 0, (
        f"replay is logged directly {direct_calls} time(s) in core.py; "
        "_collect_turn_signals already logs it once"
    )
    # And collection still happens (which logs the replay a single time).
    assert "await collect(perceived, result, turn)" in text


@pytest.mark.asyncio
async def test_runtime_failures_are_deduped_and_capped():
    """Concern C: runtime.failures must not grow without bound. A repeatedly
    failing tool must not flood the bounded digest window, and the stored
    list must be capped (mirroring _LEARNINGS_CAP) so long-lived sessions do
    not accumulate unboundedly."""
    loop = _loop_with_runtime()
    # Same failed action repeats many times across turns.
    for _ in range(50):
        result = {
            "success": False,
            "actions": [
                {
                    "name": "terminal",
                    "description": "rm -rf important_dir",
                    "success": False,
                    "error": "permission denied: read-only filesystem",
                }
            ],
        }
        await loop._collect_turn_signals(None, result, None)
    # Deduped: only ONE distinct failure stored despite 50 identical turns.
    assert len(loop.runtime.failures) == 1, loop.runtime.failures
    # And a distinct second failure still records.
    result2 = {
        "success": False,
        "actions": [
            {
                "name": "web_fetch",
                "description": "fetch https://dead.example",
                "success": False,
                "error": "DNS resolution failed",
            }
        ],
    }
    await loop._collect_turn_signals(None, result2, None)
    assert len(loop.runtime.failures) == 2, loop.runtime.failures
    from orchestrators.v5.learning import _LEARNINGS_CAP
    assert len(loop.runtime.failures) <= _LEARNINGS_CAP


@pytest.mark.asyncio
async def test_collect_turn_signals_writes_exactly_one_replay_line(tmp_path):
    """Regression guard: the replay JSONL must actually be written to disk
    (not silently swallowed). A prior bug moved the write off the event loop
    via asyncio.to_thread but forgot to import asyncio, so every write raised
    NameError inside the guarded block and nothing was ever persisted. This
    test fails loudly if that regresses again."""
    import orchestrators.v5.learning as learning_mod
    loop = _loop_with_runtime()
    loop.root_dir = str(tmp_path)
    result = _fake_result_with_failure()
    await loop._collect_turn_signals(None, result, None)
    replay = tmp_path / ".nexus_v5" / "replays.jsonl"
    assert replay.exists(), "replay JSONL was not written to disk"
    lines = [l for l in replay.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, f"expected exactly 1 replay line, got {len(lines)}"
    entry = __import__("json").loads(lines[0])
    assert entry["success"] is False
    assert entry["n_failed"] >= 1


@pytest.mark.asyncio
async def test_distinct_tool_failures_persist_to_failure_memory(tmp_path):
    """Close the durable failure-memory dead-end: FailureMemory.record() had
    ZERO callers, so MemoryManager._prefetch_failures always returned empty
    (no preventive vaccines). A distinct failed tool action must now land in
    the durable failure_memory.jsonl."""
    loop = _loop_with_runtime()
    loop.root_dir = str(tmp_path)
    result = {
        "success": False,
        "actions": [
            {
                "name": "terminal",
                "description": "rm -rf important_dir",
                "success": False,
                "error": "permission denied: read-only filesystem",
            }
        ],
    }
    await loop._collect_turn_signals(None, result, None)
    fm_path = tmp_path / "workspace" / "failure_memory.jsonl"
    assert fm_path.exists(), "failure memory was not persisted"
    import json
    lines = [l for l in fm_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, f"expected 1 durable record, got {len(lines)}"
    rec = json.loads(lines[0])
    assert rec["error"] == "permission denied: read-only filesystem"


@pytest.mark.asyncio
async def test_repeated_failure_not_redundantly_persisted(tmp_path):
    """A repeated identical failure must dedupe against the durable store
    (bound the vaccine window). 50 identical failed turns -> 1 durable line."""
    loop = _loop_with_runtime()
    loop.root_dir = str(tmp_path)
    for _ in range(50):
        result = {
            "success": False,
            "actions": [
                {
                    "name": "terminal",
                    "description": "rm -rf important_dir",
                    "success": False,
                    "error": "permission denied: read-only filesystem",
                }
            ],
        }
        await loop._collect_turn_signals(None, result, None)
    fm_path = tmp_path / "workspace" / "failure_memory.jsonl"
    lines = [l for l in fm_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, f"expected dedupe to 1 line, got {len(lines)}"


@pytest.mark.asyncio
async def test_failure_vaccine_surfaces_only_after_recording(tmp_path):
    """Closed-loop proof: MemoryManager._prefetch_failures must return an
    empty vaccine BEFORE any failure is recorded, and a non-empty
    PREVENTIVE VACCINES block AFTER a distinct tool failure is persisted
    through the V5 collector. This pins the full
    record -> durable store -> read -> inject path (not just the write)."""
    import json
    from memory import MemoryManager
    loop = _loop_with_runtime()
    loop.root_dir = str(tmp_path)

    # Before: no failure recorded -> no vaccine.
    mm_before = MemoryManager(str(tmp_path))
    assert mm_before._prefetch_failures("do something") == ""

    # Record a distinct failure through the collector.
    result = {
        "success": False,
        "actions": [
            {
                "name": "terminal",
                "description": "rm -rf important_dir",
                "success": False,
                "error": "permission denied: read-only filesystem",
            }
        ],
    }
    await loop._collect_turn_signals(None, result, None)

    # After: the recorded failure is surfaced as a vaccine.
    mm_after = MemoryManager(str(tmp_path))
    vac = mm_after._prefetch_failures("do something")
    assert "PREVENTIVE VACCINES" in vac, vac
    assert "permission denied" in vac
