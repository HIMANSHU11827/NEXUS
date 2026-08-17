"""Closed learning-evidence loop tests.

Covers the durable, provenance-bearing evidence store
(``orchestrators/v5/learning_evidence.py``):

- verified vs assumption classification (tool exit code -> verified; model
  text -> assumption at most; verified claims refuse without execution
  backing)
- provenance completeness (run_id, tool_name, exit_code, tz-aware created_at)
- retrieval before planning: relevant verified lessons surface, expired and
  superseded records are excluded, the supersession chain is visible
- policy: verified failure nudges bad_tool_count; assumption never changes
  policy
- events: ``learning.evidence`` is a valid canonical type and its payload
  carries evidence_id / claim_source / confidence / run_id
- durability: the JSONL store reloads across fresh instances
- the live-path wiring (no replay re-logging; zero core.py change needed)
"""

import asyncio
import datetime
import json
import logging
from types import SimpleNamespace

import pytest

from nexus.events import EVENT_TYPES, CanonicalEvent, infer_event_type
from nexus.main_agent.learning import V5Learning
from nexus.main_agent.learning_evidence import (
    LearningEvidenceStore,
    V5LearningEvidence,
)
from nexus.main_agent.meta import MetaLearningLayer


def _loop_with_runtime(root_dir=None, turn_id="t1", session_id="evidence-test"):
    """A minimal V5LearningEvidence stand-in with a real runtime object."""
    loop = V5LearningEvidence.__new__(V5LearningEvidence)
    loop.session_id = session_id
    loop._current_turn_id = turn_id
    loop.logger = logging.getLogger("test-evidence")
    if root_dir is not None:
        loop.root_dir = str(root_dir)

    class _RT:
        conversation_id = "conv-1"

    loop.runtime = _RT()
    return loop


def _turn(turn_id="t1", state="COMPLETED"):
    return SimpleNamespace(turn_id=turn_id, state=SimpleNamespace(value=state))


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────
# 1. VERIFIED vs ASSUMPTION CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────


def test_tool_exit_code_records_verified_evidence(tmp_path):
    """A tool action with an int exit code must persist as claim_source
    'verified' (backed by the executor's exit code)."""
    loop = _loop_with_runtime(tmp_path)
    result = {
        "success": False,
        "actions": [
            {
                "name": "terminal",
                "tool": "terminal",
                "call_id": "call_1",
                "success": False,
                "error": "command failed",
                "exit_code": 1,
            }
        ],
    }
    count = _run(loop.collect_evidence(None, result, _turn()))
    assert count == 1
    records = loop._evidence_store().load_all()
    assert len(records) == 1
    record = records[0]
    assert record["claim_source"] == "verified"
    assert record["kind"] == "tool_outcome"
    assert record["provenance"]["exit_code"] == 1
    assert record["polarity"] == "negative"
    assert record["verified_by"] == ["exit_code"]


def test_model_text_alone_records_only_assumption(tmp_path):
    """Reflection text is model output: it must be persisted as an
    assumption, never as verified."""
    loop = _loop_with_runtime(tmp_path)
    result = {
        "success": False,
        "reflection": {
            "root_causes": ["the directory was mounted read-only"],
            "improvements": ["check mount flags before recursive delete"],
        },
    }
    count = _run(loop.collect_evidence(None, result, _turn()))
    assert count >= 1
    records = loop._evidence_store().load_all()
    assert all(r["claim_source"] == "assumption" for r in records)
    assert all(r["kind"] == "reflection" for r in records)
    assert all(r["verified_by"] == [] for r in records)


def test_record_verified_refuses_without_execution_backing(tmp_path):
    """claim_source='verified' without any execution backing must be refused;
    the store must never persist an unbacked claim as verified."""
    store = LearningEvidenceStore(str(tmp_path))
    refused = store.record_verified(
        kind="tool_outcome", statement="terminal works", tool_name="terminal"
    )
    assert refused is None
    assert store.load_all() == []


def test_record_assumption_never_verified(tmp_path):
    store = LearningEvidenceStore(str(tmp_path))
    record = store.record_assumption(
        kind="tool_outcome", statement="terminal probably works",
        tool_name="terminal", confidence=0.4,
    )
    assert record is not None
    assert record["claim_source"] == "assumption"
    assert record["verified_by"] == []
    assert record["confidence"] == 0.4


# ─────────────────────────────────────────────────────────────────────────
# 2. PROVENANCE COMPLETENESS
# ─────────────────────────────────────────────────────────────────────────


def test_provenance_fields_complete(tmp_path):
    loop = _loop_with_runtime(tmp_path, turn_id="t_prov")
    result = {
        "success": True,
        "actions": [
            {
                "name": "terminal",
                "tool": "terminal",
                "call_id": "call_7",
                "success": True,
                "exit_code": 0,
            }
        ],
    }
    _run(loop.collect_evidence(None, result, _turn(turn_id="t_prov")))
    record = loop._evidence_store().load_all()[0]
    assert record["run_id"] == "t_prov"
    assert record["turn_id"] == "t_prov"
    assert record["conversation_id"] == "conv-1"
    provenance = record["provenance"]
    assert set(provenance) == {
        "tool_name", "tool_call_id", "exit_code", "provider_id", "model", "phase"
    }
    assert provenance["tool_name"] == "terminal"
    assert provenance["tool_call_id"] == "call_7"
    assert provenance["exit_code"] == 0
    assert provenance["phase"] == "COMPLETED"
    created = datetime.datetime.fromisoformat(record["created_at"])
    assert created.tzinfo is not None and created.utcoffset() == datetime.timedelta(0)
    assert len(record["evidence_id"]) == 32
    assert record["observed_value"] == 0
    assert record["expected_value"] == 0
    assert record["replayed"] is False


# ─────────────────────────────────────────────────────────────────────────
# 3. RETRIEVAL, EXPIRY AND SUPERSESSION
# ─────────────────────────────────────────────────────────────────────────


def test_retrieval_surfaces_verified_lesson_before_planning(tmp_path):
    loop = _loop_with_runtime(tmp_path)
    result = {
        "success": False,
        "actions": [
            {
                "name": "terminal",
                "tool": "terminal",
                "call_id": "call_1",
                "success": False,
                "error": "permission denied",
                "exit_code": 126,
            }
        ],
    }
    _run(loop.collect_evidence(None, result, _turn()))
    lessons = loop.retrieve_lessons(task_summary="run the build script")
    assert len(lessons) == 1
    assert lessons[0]["record"]["claim_source"] == "verified"
    # The grounding prompt block each planning turn sees:
    prompt = loop._evidence_lessons_prompt(task_summary="run the build script")
    assert "LESSONS FROM VERIFIED OUTCOMES:" in prompt
    assert lessons[0]["record"]["evidence_id"][:8] in prompt
    assert "evidence:" in prompt


def test_retrieval_skips_assumptions_by_default(tmp_path):
    loop = _loop_with_runtime(tmp_path)
    result = {
        "success": False,
        "reflection": {"root_causes": ["the build is broken"]},
    }
    _run(loop.collect_evidence(None, result, _turn()))
    prompt = loop._evidence_lessons_prompt(task_summary="fix the build")
    assert prompt == ""


def test_expired_rule_expiry_excluded_from_retrieval(tmp_path):
    store = LearningEvidenceStore(str(tmp_path))
    expired = store.record_verified(
        kind="failure", statement="deploy tool broken",
        tool_name="deploy", phase="terminal", verified_by=["tool_result"],
        observed_value="boom",
        rule_expiry=(datetime.datetime.now(datetime.timezone.utc)
                     - datetime.timedelta(hours=1)).isoformat(),
    )
    assert expired is not None
    assert store.is_expired(expired) is True
    assert store.retrieve_lessons(task_summary="deploy") == []


def test_superseded_record_excluded_and_chain_visible(tmp_path):
    store = LearningEvidenceStore(str(tmp_path))
    failed = store.record_verified(
        kind="failure", statement="terminal fails to run tests",
        tool_name="terminal", phase="test", verified_by=["tool_result"],
        observed_value="exit 1",
    )
    assert failed is not None
    passed = store.record_verified(
        kind="tool_outcome", statement="terminal exit code 0",
        tool_name="terminal", phase="test", exit_code=0,
        verified_by=["exit_code"], observed_value=0, expected_value=0,
    )
    assert passed is not None
    # The newer verified record tags the chain...
    assert passed["supersedes_evidence_id"] == [failed["evidence_id"]]
    # ...and the old record is durably marked superseded.
    old = store.get(failed["evidence_id"])
    assert old["superseded_by"] == passed["evidence_id"]
    assert store.is_expired(old) is True
    # Retrieval excludes the expired old lesson and surfaces the winner.
    lessons = store.retrieve_lessons(phase="test", task_summary="run tests")
    assert len(lessons) == 1
    assert lessons[0]["record"]["evidence_id"] == passed["evidence_id"]
    assert lessons[0]["supersedes"] == [failed["evidence_id"]]
    assert lessons[0]["record"]["supersedes_evidence_id"] == [failed["evidence_id"]]
    # A same-polarity record must NOT supersede.
    again = store.record_verified(
        kind="tool_outcome", statement="terminal exit code 0 again",
        tool_name="terminal", phase="test", exit_code=0,
        verified_by=["exit_code"], observed_value=0, expected_value=0,
    )
    assert again["supersedes_evidence_id"] == []


def test_retrieval_marks_replayed_for_diagnostics(tmp_path):
    loop = _loop_with_runtime(tmp_path)
    result = {
        "success": False,
        "actions": [
            {
                "name": "web_fetch",
                "tool": "web_fetch",
                "success": False,
                "error": "DNS failure",
                "exit_code": 1,
            }
        ],
    }
    _run(loop.collect_evidence(None, result, _turn()))
    record = loop._evidence_store().load_all()[0]
    assert record["replayed"] is False
    _ = loop._evidence_lessons_prompt(task_summary="fetch a page")
    assert loop._evidence_store().get(record["evidence_id"])["replayed"] is True


# ─────────────────────────────────────────────────────────────────────────
# 4. POLICY NUDGE FROM VERIFIED OUTCOMES ONLY
# ─────────────────────────────────────────────────────────────────────────


def _verified_evidence(kind="failure", tool="terminal", polarity="negative",
                       claim_source="verified", confidence=1.0):
    return {
        "evidence_id": "e" * 32,
        "kind": kind,
        "claim_source": claim_source,
        "confidence": confidence,
        "polarity": polarity,
        "provenance": {
            "tool_name": tool, "tool_call_id": "", "exit_code": 1,
            "provider_id": "test", "model": "m", "phase": "terminal",
        },
    }


def test_verified_failure_nudges_bad_tool_count(tmp_path):
    meta = MetaLearningLayer(str(tmp_path))
    nudges = meta.on_verified_evidence(_verified_evidence())
    assert nudges["tool"] == "terminal"
    assert nudges["bad_tool_count"] == 1
    assert meta.tool_policy["terminal"]["bad_tool_count"] == 1
    # Persisted: a fresh layer sees the nudge.
    reloaded = MetaLearningLayer(str(tmp_path))
    assert reloaded.tool_policy["terminal"]["bad_tool_count"] == 1


def test_verified_success_nudges_good_tool_count(tmp_path):
    meta = MetaLearningLayer(str(tmp_path))
    meta.on_verified_evidence(_verified_evidence(
        kind="tool_outcome", polarity="positive"
    ))
    assert meta.tool_policy["terminal"]["good_tool_count"] == 1
    assert meta.tool_policy["terminal"]["bad_tool_count"] == 0


def test_assumption_never_changes_policy(tmp_path):
    meta = MetaLearningLayer(str(tmp_path))
    assert meta.on_verified_evidence(_verified_evidence(claim_source="assumption")) == {}
    assert meta.tool_policy == {}
    # Directly recorded evidence in the store also never nudges policy:
    loop = _loop_with_runtime(tmp_path)
    result = {"success": False, "reflection": {"root_causes": ["x broke"]}}
    _run(loop.collect_evidence(None, result, _turn()))
    assert meta.on_verified_evidence(
        loop._evidence_store().load_all()[0]
    ) == {}
    assert meta.tool_policy == {}


# ─────────────────────────────────────────────────────────────────────────
# 5. CANONICAL EVENTS
# ─────────────────────────────────────────────────────────────────────────


def test_learning_evidence_is_valid_canonical_event_type():
    assert "learning.evidence" in EVENT_TYPES
    assert "learning.policy" in EVENT_TYPES
    assert infer_event_type({"kind": "learning", "evidence_id": "abc"}, "success") == "learning.evidence"
    assert infer_event_type({"kind": "learning", "bad_tool_count": 1}, "success") == "learning.policy"
    # The canonical envelope accepts it end to end.
    event = CanonicalEvent(
        event_id="evt_1", run_id="run_1", conversation_id="conv_1",
        type="learning.evidence", title="Learning evidence", status="success",
        timestamp=1.0, sequence=1,
        payload={"evidence_id": "abc", "claim_source": "verified", "confidence": 0.9},
    )
    assert event.type == "learning.evidence"


def test_learning_event_payload_carries_identity_fields(tmp_path):
    from nexus.main_agent.events import V5EventEmitter

    class _Loop(V5LearningEvidence, V5EventEmitter):
        pass

    loop = _Loop.__new__(_Loop)
    loop.session_id = "evidence-test"
    loop._current_turn_id = "t_emit"
    loop.logger = logging.getLogger("test-emit")
    loop.runtime = SimpleNamespace(work_event_sink=None, conversation_id="conv-1")
    loop.work_event_sink = None
    captured = []
    loop.work_event_sink = captured.append

    evidence = _verified_evidence(kind="failure", tool="terminal")
    _run(loop._emit_learning_event("learning.evidence", evidence=evidence))
    _run(loop._emit_learning_event(
        "learning.policy", evidence=evidence,
        policy={"tool": "terminal", "good_tool_count": 0, "bad_tool_count": 1},
    ))
    assert len(captured) == 2
    event = captured[0]
    payload = event["payload"]
    assert event["event_type"] == "learning.evidence"
    assert event["kind"] == "learning"
    for key in ("evidence_id", "claim_source", "confidence", "run_id"):
        assert key in payload, f"payload missing {key}"
    assert payload["claim_source"] == "verified"
    assert payload["confidence"] == 1.0
    assert payload["run_id"] == "t_emit"
    # The emitter is canonical-compatible: from_work_event maps it cleanly.
    canonical = CanonicalEvent.from_work_event(event, "conv-1", sequence=1)
    assert canonical.type == "learning.evidence"
    assert canonical.payload["evidence_id"] == evidence["evidence_id"]
    policy_event = captured[1]
    assert policy_event["payload"]["bad_tool_count"] == 1


# ─────────────────────────────────────────────────────────────────────────
# 6. DURABILITY
# ─────────────────────────────────────────────────────────────────────────


def test_store_reloads_across_fresh_instances(tmp_path):
    store_a = LearningEvidenceStore(str(tmp_path))
    record = store_a.record_verified(
        kind="tool_outcome", statement="pytest passes on v5",
        tool_name="pytest", phase="test", exit_code=0,
        verified_by=["exit_code"], observed_value=0, expected_value=0,
    )
    assert record is not None
    # A fresh instance (simulating a restarted process) must see the lesson.
    store_b = LearningEvidenceStore(str(tmp_path))
    records = store_b.load_all()
    assert len(records) == 1
    assert store_b.get(record["evidence_id"]) is not None
    assert records[0]["evidence_id"] == record["evidence_id"]


def test_store_file_survives_and_is_valid_jsonl(tmp_path):
    loop = _loop_with_runtime(tmp_path)
    result = {
        "success": False,
        "actions": [
            {"name": "terminal", "tool": "terminal", "success": False,
             "error": "boom", "exit_code": 2}
        ],
        "verification": {"success": False, "failed_actions": 1, "status": "failed"},
    }
    _run(loop.collect_evidence(None, result, _turn()))
    evidence_file = tmp_path / ".nexus_v5" / "evidence.jsonl"
    assert evidence_file.exists(), "evidence JSONL was not written to disk"
    lines = [l for l in evidence_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2  # tool_outcome + verification
    for line in lines:
        parsed = json.loads(line)
        assert parsed["evidence_id"]
        assert parsed["created_at"]


# ─────────────────────────────────────────────────────────────────────────
# 7. LIVE-PATH WIRING
# ─────────────────────────────────────────────────────────────────────────


def test_evidence_collector_wired_into_turn_signals():
    """collect_evidence must be invoked from the per-turn collector and must
    NOT re-log replays (replays.jsonl stays the property of _log_turn_replay)."""
    import nexus.main_agent.learning as learning_mod

    text = open(learning_mod.__file__, encoding="utf-8", errors="ignore").read()
    assert "collect_evidence" in text
    assert "await collect_evidence(perceived, result, turn)" in text


def test_v5learning_inherits_evidence_mixin():
    """The evidence surface rides on V5Learning (already mixed into
    NexusLoopV5), so the loop gets it with zero core.py wiring change."""
    assert issubclass(V5Learning, V5LearningEvidence)


def test_collect_evidence_does_not_log_replays(tmp_path):
    loop = _loop_with_runtime(tmp_path)
    result = {
        "success": False,
        "actions": [
            {"name": "terminal", "tool": "terminal", "success": False,
             "error": "boom", "exit_code": 2}
        ],
    }
    _run(loop.collect_evidence(None, result, _turn()))
    replay_file = tmp_path / ".nexus_v5" / "replays.jsonl"
    assert not replay_file.exists(), "evidence collection must never log replays"


def test_collect_evidence_never_raises_without_root(tmp_path):
    loop = _loop_with_runtime(root_dir=None)
    assert _run(loop.collect_evidence(None, {"success": True}, _turn())) == 0


def test_grounding_prompt_includes_lessons_section(tmp_path):
    """The grounding mixin appends the lessons block to the stable prompt."""
    from nexus.main_agent.grounding import V5ContextGrounding

    loop = _loop_with_runtime(tmp_path)
    loop.root_dir = str(tmp_path)
    result = {
        "success": False,
        "actions": [
            {"name": "terminal", "tool": "terminal", "success": False,
             "error": "permission denied", "exit_code": 126}
        ],
    }
    _run(loop.collect_evidence(None, result, _turn()))

    class _Loop(V5ContextGrounding):
        def __init__(self):
            self._stable_prompt_cache = "BASE"
            self._stable_prompt_built = True
            self.root_dir = str(tmp_path)

    grounded = _Loop()
    grounded._evidence_lessons_prompt = loop._evidence_lessons_prompt
    prompt = grounded._build_stable_prompt()
    assert prompt.startswith("BASE")
    assert "LESSONS FROM VERIFIED OUTCOMES:" in prompt
    assert "terminal" in prompt
