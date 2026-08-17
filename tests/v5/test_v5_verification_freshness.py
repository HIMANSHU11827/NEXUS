import asyncio
import json

from nexus.main_agent.verification import V5Verifier
from nexus.main_agent.run_evidence import build_run_evidence
from nexus.main_agent.verification_state import VerifierStateStore
from nexus.main_agent.verification_events import VerifierEventStore


def test_verification_freshness_detects_referenced_file_edits(tmp_path):
    target = tmp_path / "result.txt"
    target.write_text("first", encoding="utf-8")

    verifier = V5Verifier()
    verifier.root_dir = str(tmp_path)
    result = asyncio.run(verifier._verify_result({
        "success": True,
        "actions": [{"path": "result.txt", "success": True, "output": "written"}],
    }))

    verification = result["verification"]
    assert verification["status"] == "passed"
    assert verification["event_id"].startswith("ve_")
    assert VerifierEventStore(tmp_path / ".nexus_v5" / "verifier_events.sqlite3").list_events(
        "default", str(tmp_path)
    )[0]["event_id"] == verification["event_id"]
    assert verification["freshness"]["status"] == "fresh"
    assert V5Verifier.check_verification_freshness(verification, str(tmp_path)) == "fresh"

    target.write_text("changed", encoding="utf-8")
    assert V5Verifier.check_verification_freshness(verification, str(tmp_path)) == "stale"


def test_verification_without_freshness_is_unverified():
    assert V5Verifier.check_verification_freshness({"success": True}) == "unverified"


def test_run_evidence_keeps_bounded_verifier_freshness():
    evidence = build_run_evidence({
        "turn_id": "turn-1",
        "success": True,
        "verification": {
            "status": "passed",
            "success": True,
            "freshness": {
                "status": "fresh",
                "evidence_id": "abc123",
                "checked_at": 1.0,
                "artifacts": [{"path": "result.txt", "sha256": "a" * 64, "status": "present",
                                "secret": "must not persist"}],
            },
        },
    })
    serialized = json.dumps(evidence)
    assert evidence["verification"]["status"] == "passed"
    assert evidence["verification"]["freshness"]["evidence_id"] == "abc123"
    assert "must not persist" not in serialized


def test_run_evidence_projects_cross_process_stale_state(tmp_path):
    state_path = tmp_path / ".nexus_v5" / "verifier_state.json"
    store = VerifierStateStore(state_path)
    store.record_verification("session-1", str(tmp_path), status="passed", verifier_id="v-1")
    store.mark_stale("session-1", str(tmp_path), ["changed.txt"])
    evidence = build_run_evidence({
        "turn_id": "turn-1", "success": True,
        "verification": {"success": True},
    }, session_id="session-1")
    from nexus.main_agent.run_evidence import write_run_evidence
    path = write_run_evidence(str(tmp_path), evidence)
    loaded = json.loads(open(path, encoding="utf-8").read())
    assert loaded["verification"]["durable_status"] == "stale"
    assert loaded["verification"]["last_edit_at"]
