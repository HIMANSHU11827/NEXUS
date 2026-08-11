import json

from orchestrators.v5.run_evidence import (
    build_hermes_trajectory,
    build_run_evidence,
    write_run_evidence,
)
from orchestrators.v5.events import V5EventEmitter


def test_canonical_event_summaries_exclude_payload_and_bound_history():
    emitter = V5EventEmitter()
    emitter._stream_events = [
        {"id": "evt-1", "event_type": "tool.completed", "status": "success",
         "payload": {"secret": "must-not-leak"}, "tool": "terminal"},
    ]
    summaries = emitter.canonical_event_summaries()
    assert summaries == [{
        "event_id": "evt-1", "type": "tool.completed", "status": "success",
        "sequence": 0, "parent_id": "", "related_tool": "terminal",
    }]
    assert "payload" not in summaries[0]
from orchestrators.v5.events import V5EventEmitter, summarize_work_event, summarize_work_events


def test_run_evidence_is_bounded_and_redacted(tmp_path):
    evidence = build_run_evidence(
        {
            "turn_id": "turn-1",
            "success": True,
            "provider_attempts": [
                {"provider_id": "openai", "model": "gpt-test", "status": "failed",
                 "reason": "Bearer secret-token-value"},
                {"provider_id": "gemini", "model": "gemini-test", "status": "success"},
            ],
            "actions": [{"name": "terminal", "success": True, "verified": True,
                         "result": "large output should not be persisted"}],
            "verification": {"success": True, "evidence_ok": True,
                            "anomalies": ["Bearer verification-secret"]},
            "canonical_event_ids": ["verification-turn-1", "run-turn-1"],
            "replay_path": "/workspace/.nexus_v5/replays.jsonl",
            "replay_logged": True,
            "canonical_events": [
                {"event_id": "evt-1", "type": "tool.completed", "status": "success", "sequence": 3,
                 "payload": {"secret": "should-not-be-copied"}},
            ],
            "checkpoint_paths": [".nexus_v5/checkpoints/turn-1-act.json"],
            "error": "https://x.test/?api_key=sk-secret-value",
        },
        session_id="session-1",
    )
    path = write_run_evidence(str(tmp_path), evidence)
    loaded = json.loads(open(path, encoding="utf-8").read())
    assert loaded["selected"]["provider"] == "gemini"
    assert loaded["tools"] == [{"name": "terminal", "success": True, "verified": True}]
    assert loaded["trace"]["canonical_event_ids"] == ["verification-turn-1", "run-turn-1"]
    assert loaded["trace"]["replay_path"].endswith("replays.jsonl")
    assert loaded["trace"]["replay"]["logged"] is True
    assert loaded["trace"]["checkpoint_paths"] == [".nexus_v5/checkpoints/turn-1-act.json"]
    assert loaded["trace"]["canonical_events"] == [{
        "event_id": "evt-1", "type": "tool.completed", "status": "success",
        "sequence": 3, "parent_id": "", "related_tool": "",
    }]
    assert loaded["trajectory"]["format"] == "hermes-sharegpt-v1"
    assert loaded["verification"] == {
        "success": True, "evidence_ok": True,
        "anomalies": ["***REDACTED***"],
    }
    assert "secret-token-value" not in json.dumps(loaded)
    assert "sk-secret-value" not in json.dumps(loaded)


def test_run_evidence_uses_safe_fallback_names(tmp_path):
    evidence = build_run_evidence({"turn_id": "", "success": False})
    path = write_run_evidence(str(tmp_path), evidence)
    assert path.endswith(".json")
    assert "provider_run_evidence" in path


def test_event_summary_is_bounded_identity_only_and_stable():
    event = {
        "id": "evt-42",
        "event_type": "tool.completed",
        "status": "success",
        "payload": {"secret": "Bearer super-secret-token"},
        "result": "api_key=top-secret",
        "title": "private task text",
    }
    first = summarize_work_event(event, ordinal=4, run_id="turn-1")
    second = summarize_work_event(event, ordinal=4, run_id="turn-1")
    assert first == second
    assert first["event_id"] == "evt-42"
    assert "payload" not in first and "result" not in first and "title" not in first
    assert "super-secret-token" not in str(first)

    batch = summarize_work_events([{"type": "tool.completed", "payload": {"x": "secret"}}] * 200)
    assert batch["count"] == 200
    assert batch["truncated"] is True
    assert len(batch["events"]) == 128
    assert len({item["event_id"] for item in batch["events"]}) == 128


def test_run_evidence_accepts_emitter_events_without_raw_payloads():
    evidence = build_run_evidence(
        {"turn_id": "turn-1", "success": True, "canonical_event_ids": []},
        events=[
            {"id": "evt-1", "event_type": "tool.completed", "status": "success",
             "payload": {"secret": "sk-live-should-not-persist"},
             "result": "Bearer should-not-persist"},
        ],
    )
    assert evidence["trace"]["canonical_event_ids"] == ["evt-1"]
    assert evidence["trace"]["canonical_events"] == [{
        "event_id": "evt-1", "event_type": "tool.completed", "status": "success",
        "parent_id": "", "tool": "", "kind": "", "part_type": "", "visibility": "",
    }]
    serialized = json.dumps(evidence)
    assert "sk-live-should-not-persist" not in serialized
    assert "Bearer should-not-persist" not in serialized


def test_emitter_terminal_summary_is_bounded_and_payload_free():
    class Runtime:
        work_event_sink = None

    class Emitter(V5EventEmitter):
        runtime = Runtime()
        work_event_sink = None
        session_id = "session-1"
        _current_turn_id = "turn-1"
        _stream_events = []

    emitter = Emitter()

    import asyncio

    async def emit_many():
        for index in range(140):
            await emitter._emit_work_event({
                "event_type": "tool.completed",
                "status": "success",
                "payload": {"secret": "Bearer raw-secret"},
                "result": "raw output",
            })
        await emitter._emit_run_finished("success", payload={"private": "raw payload"})

    asyncio.run(emit_many())
    summary = emitter._stream_events[-1]["payload"]["event_summary"]
    assert summary["count"] == 141
    assert summary["truncated"] is True
    assert len(summary["events"]) == 128
    assert len({item["event_id"] for item in summary["events"]}) == 128
    assert all("payload" not in item and "result" not in item for item in summary["events"])
    assert "raw-secret" not in str(summary)


def test_hermes_trajectory_adapter_preserves_identity_and_redacts_content():
    trajectory = build_hermes_trajectory([
        {"role": "assistant", "content": "I will inspect it", "tool_calls": [{"id": "call-7"}]},
        {"role": "tool", "tool_call_id": "call-7", "content": "Bearer secret-token"},
    ], model="nexus-model", completed=True, user_query="inspect")
    assert trajectory["completed"] is True
    assert trajectory["model"] == "nexus-model"
    assert trajectory["conversations"][0] == {"from": "human", "value": "inspect"}
    assert "<think>" in trajectory["conversations"][1]["value"]
    assert "<tool_call>" in trajectory["conversations"][1]["value"]
    assert "call-7" in trajectory["conversations"][2]["value"]
    assert "secret-token" not in json.dumps(trajectory)


def test_artifact_statuses_resolve_and_link_replay_and_checkpoint(tmp_path):
    replay_dir = tmp_path / ".nexus_v5"
    checkpoint_dir = replay_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    (replay_dir / "replays.jsonl").write_text(json.dumps({
        "entry_id": "replay_session-1_turn-1",
        "turn_id": "turn-1",
        "session_id": "session-1",
        "success": True,
    }) + "\n", encoding="utf-8")
    checkpoint = checkpoint_dir / "turn-1_act.json"
    checkpoint.write_text(json.dumps({
        "turn_id": "turn-1", "phase": "act", "session": "session-1",
    }), encoding="utf-8")

    evidence = build_run_evidence({
        "turn_id": "turn-1",
        "success": True,
        "replay": {
            "path": ".nexus_v5/replays.jsonl",
            "entry_id": "replay_session-1_turn-1",
            "logged": True,
        },
        "checkpoint_paths": [str(checkpoint.relative_to(tmp_path))],
    }, session_id="session-1")
    path = write_run_evidence(str(tmp_path), evidence)
    loaded = json.loads(open(path, encoding="utf-8").read())
    assert loaded["trace"]["replay"]["status"] == "present"
    assert loaded["trace"]["checkpoints"][0]["status"] == "present"
    assert loaded["trace"]["artifact_status"] == "present"


def test_artifact_statuses_distinguish_missing_and_ambiguous_replay(tmp_path):
    replay_dir = tmp_path / ".nexus_v5"
    replay_dir.mkdir()
    (replay_dir / "replays.jsonl").write_text("\n".join(json.dumps({
        "entry_id": "duplicate", "turn_id": "turn-1", "session_id": "session-1",
    }) for _ in range(2)) + "\n", encoding="utf-8")
    evidence = build_run_evidence({
        "turn_id": "turn-1", "success": True,
        "replay": {"path": ".nexus_v5/replays.jsonl", "entry_id": "duplicate"},
        "checkpoint_paths": [".nexus_v5/checkpoints/does-not-exist.json"],
    }, session_id="session-1")
    path = write_run_evidence(str(tmp_path), evidence)
    loaded = json.loads(open(path, encoding="utf-8").read())
    assert loaded["trace"]["replay"]["status"] == "ambiguous"
    assert loaded["trace"]["checkpoints"][0]["status"] == "missing"
    assert loaded["trace"]["artifact_status"] == "ambiguous"


def test_replay_digest_detects_tampering(tmp_path):
    from orchestrators.v5.run_evidence import _replay_record_digest, _replay_status

    replay_path = tmp_path / "replays.jsonl"
    record = {
        "entry_id": "replay-integrity",
        "turn_id": "turn-1",
        "session_id": "session-1",
        "success": True,
    }
    record["record_sha256"] = _replay_record_digest(record)
    record["success"] = False
    replay_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert _replay_status(
        str(replay_path), entry_id="replay-integrity",
        record_sha256=record["record_sha256"], turn_id="turn-1", session_id="session-1",
    ) == "invalid"


def test_trace_exposes_explicit_verifier_replay_checkpoint_joins(tmp_path):
    evidence = build_run_evidence({
        "turn_id": "turn-join", "success": True,
        "verification": {"event_id": "ve-join"},
        "replay": {"path": "missing.jsonl", "entry_id": "replay-join"},
        "checkpoint_paths": ["missing-checkpoint.json"],
    }, session_id="session-join")
    joins = evidence["trace"]["joins"]
    assert joins["session_id"] == "session-join"
    assert joins["turn_id"] == "turn-join"
    assert joins["verifier_event_id"] == "ve-join"
    assert joins["replay_entry_id"] == "replay-join"
