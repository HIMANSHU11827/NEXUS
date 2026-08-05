"""Tests for V5 phase-based model routing and the episodic memory stream."""

import datetime
import json
import math
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from orchestrators.v5.core import NexusLoopV5
from memory import MemoryManager

_PHASES = ("plan", "verify", "act", "gather", "output")


def _make_loop(tmp_path, monkeypatch=None):
    """Construct a V5 loop in a temp dir with routing env vars cleared."""
    if monkeypatch is not None:
        monkeypatch.delenv("NEXUS_MODEL_PLAN", raising=False)
        monkeypatch.delenv("NEXUS_MODEL_FAST", raising=False)
    return NexusLoopV5(root_dir=str(tmp_path), session_id="episodic_test")


def _iso(age_seconds, now):
    return datetime.datetime.fromtimestamp(
        now - age_seconds, datetime.timezone.utc
    ).isoformat()


# ─── Phase-based model routing ───────────────────────────────────────


def test_select_model_phase_empty_without_config(tmp_path, monkeypatch):
    """No routing configured -> every phase returns the default model."""
    loop = _make_loop(tmp_path, monkeypatch)
    for phase in _PHASES:
        assert loop._select_model_for_phase(phase) == ""
    assert loop._select_model_for_phase("bogus") == ""
    assert loop._select_model_for_phase(None) == ""


def test_select_model_phase_env_strong_model(tmp_path, monkeypatch):
    """NEXUS_MODEL_PLAN routes plan/verify to the strong model."""
    monkeypatch.setenv("NEXUS_MODEL_PLAN", "strong-model")
    loop = _make_loop(tmp_path)
    assert loop._select_model_for_phase("plan") == "strong-model"
    assert loop._select_model_for_phase("verify") == "strong-model"
    assert loop._select_model_for_phase("act") == ""
    assert loop._select_model_for_phase("gather") == ""
    assert loop._select_model_for_phase("output") == ""


def test_select_model_phase_env_fast_model(tmp_path, monkeypatch):
    """NEXUS_MODEL_FAST routes act/gather/output to the fast model."""
    monkeypatch.setenv("NEXUS_MODEL_FAST", "fast-model")
    loop = _make_loop(tmp_path)
    assert loop._select_model_for_phase("act") == "fast-model"
    assert loop._select_model_for_phase("gather") == "fast-model"
    assert loop._select_model_for_phase("output") == "fast-model"
    assert loop._select_model_for_phase("plan") == ""
    assert loop._select_model_for_phase("verify") == ""


async def test_safe_model_call_phase_unrouted_uses_plain_call(tmp_path, monkeypatch):
    """Unrouted phase calls _safe_model_call exactly once with no override."""
    loop = _make_loop(tmp_path, monkeypatch)
    calls = []

    async def fake_safe(messages, **kwargs):
        calls.append((messages, kwargs))
        return "plain-result"

    monkeypatch.setattr(loop, "_safe_model_call", fake_safe)
    messages = [{"role": "user", "content": "hello"}]
    result = await loop._safe_model_call_phase(messages, phase="plan")
    assert result == "plain-result"
    assert len(calls) == 1
    assert calls[0][0] is messages
    assert "model" not in calls[0][1]


async def test_safe_model_call_phase_routed_passes_model(tmp_path, monkeypatch):
    """Routed phase passes the selected model into _safe_model_call."""
    monkeypatch.setenv("NEXUS_MODEL_PLAN", "strong-model")
    loop = _make_loop(tmp_path)
    calls = []

    async def fake_safe(messages, **kwargs):
        calls.append((messages, kwargs))
        return "routed-result"

    monkeypatch.setattr(loop, "_safe_model_call", fake_safe)
    messages = [{"role": "user", "content": "hello"}]
    result = await loop._safe_model_call_phase(messages, phase="plan")
    assert result == "routed-result"
    assert len(calls) == 1
    assert calls[0][0] is messages
    assert calls[0][1].get("model") == "strong-model"


# ─── Episodic memory stream ──────────────────────────────────────────


def test_load_episodic_empty_when_replay_missing(tmp_path, monkeypatch):
    """Missing replay file -> []."""
    loop = _make_loop(tmp_path, monkeypatch)
    assert loop._load_episodic() == []
    assert loop._load_episodic(limit=10) == []


def test_load_episodic_newest_first_and_prefetch(tmp_path, monkeypatch):
    """Entries load newest-first and prefetch ranks failures on top."""
    loop = _make_loop(tmp_path, monkeypatch)
    replay_dir = tmp_path / ".nexus_v5"
    replay_dir.mkdir()
    now = time.time()
    entries = [
        {
            "timestamp": _iso(7200, now),
            "input": "old failed run",
            "success": False,
            "n_failed": 1,
            "error": "timeout",
            "plan_steps": 2,
        },
        {
            "timestamp": _iso(100, now),
            "input": "recent chat",
            "success": True,
            "n_failed": 0,
            "plan_steps": 0,
        },
    ]
    with open(replay_dir / "replays.jsonl", "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")

    loaded = loop._load_episodic()
    assert len(loaded) == 2
    assert loaded[0]["input"] == "recent chat"
    assert loaded[1]["input"] == "old failed run"

    digests = loop._prefetch_episodic(limit=5)
    assert len(digests) == 2
    by_input = {d["input"]: d for d in digests}
    assert by_input["old failed run"]["outcome"] == "failure"
    assert by_input["recent chat"]["outcome"] == "success"
    assert by_input["old failed run"]["score"] > by_input["recent chat"]["score"]
    assert all(isinstance(d["score"], float) for d in digests)
    assert all(d["ts"] for d in digests)


def test_episodic_score_recency_range(tmp_path, monkeypatch):
    """Score is finite 0..1 and older identical entries score lower."""
    loop = _make_loop(tmp_path, monkeypatch)
    now = time.time()
    base = {"input": "fix bug", "success": True, "n_failed": 0, "n_actions": 1, "plan_steps": 3}
    newer = dict(base, timestamp=_iso(3600, now))
    older = dict(base, timestamp=_iso(172800, now))
    s_new = loop._episodic_score(newer, now=now)
    s_old = loop._episodic_score(older, now=now)
    assert math.isfinite(s_new) and math.isfinite(s_old)
    assert 0.0 <= s_new <= 1.0
    assert 0.0 <= s_old <= 1.0
    assert s_new > s_old


def test_episodic_score_failure_importance(tmp_path, monkeypatch):
    """Failure entries score above identical successful ones."""
    loop = _make_loop(tmp_path, monkeypatch)
    now = time.time()
    ts = _iso(0, now)
    ok = {"timestamp": ts, "input": "chat", "success": True, "n_failed": 0}
    bad = {"timestamp": ts, "input": "run tool", "success": False, "n_failed": 2, "error": "boom"}
    assert loop._episodic_score(bad, now=now) > loop._episodic_score(ok, now=now)


def test_episodic_score_defensive(tmp_path, monkeypatch):
    """Malformed entries score 0.0 and never raise."""
    loop = _make_loop(tmp_path, monkeypatch)
    assert loop._episodic_score(None) == 0.0
    assert loop._episodic_score("not a dict") == 0.0
    assert loop._episodic_score([1, 2, 3]) == 0.0


# ─── MemoryManager episodic prefetch ─────────────────────────────────


def test_memory_manager_prefetch_episodic_missing(tmp_path):
    """MemoryManager returns [] safely when replays.jsonl is absent."""
    manager = MemoryManager(root_dir=str(tmp_path), session_id="episodic_test")
    assert manager._prefetch_episodic() == []
    assert manager.get("episodic") == ""


def test_memory_manager_prefetch_episodic_with_replays(tmp_path):
    """MemoryManager populates the episodic store from replays.jsonl."""
    replay_dir = tmp_path / ".nexus_v5"
    replay_dir.mkdir()
    now = time.time()
    entries = [
        {"timestamp": _iso(600, now), "input": "failed deploy", "success": False, "n_failed": 1},
        {"timestamp": _iso(3600, now), "input": "small talk", "success": True, "n_failed": 0},
    ]
    with open(replay_dir / "replays.jsonl", "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")

    manager = MemoryManager(root_dir=str(tmp_path), session_id="episodic_test")
    digests = manager._prefetch_episodic(limit=5)
    assert len(digests) == 2
    by_input = {d["input"]: d for d in digests}
    assert by_input["failed deploy"]["outcome"] == "failure"
    assert by_input["small talk"]["outcome"] == "success"
    assert by_input["failed deploy"]["score"] > by_input["small talk"]["score"]
    assert "failed deploy" in manager.get("episodic")
