import json
import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from nexus.main_agent.verification_state import VerifierStateStore
from nexus.main_agent.events import V5EventEmitter


def test_missing_store_is_conservatively_unverified(tmp_path):
    state = VerifierStateStore(tmp_path / "state.json").get("session-a", str(tmp_path))
    assert state["status"] == "unverified"
    assert state["verifier_id"] is None


def test_record_then_stale_then_reverify_clears_stale_metadata(tmp_path):
    store = VerifierStateStore(tmp_path / "state.json", max_changed_paths=2)
    passed = store.record_verification("session-a", str(tmp_path), status="passed", verifier_id="opaque-1")
    stale = store.mark_stale("session-a", str(tmp_path), ["src/a.py", "src/b.py", "src/c.py"])
    assert passed["verifier_id"] == stale["verifier_id"] == "opaque-1"
    assert stale["status"] == "stale"
    assert stale["changed_paths"] == ["src/a.py", "src/b.py"]
    refreshed = store.record_verification("session-a", str(tmp_path), status="passed", verifier_id="opaque-2")
    assert refreshed["stale_at"] is None
    assert refreshed["changed_paths"] == []
    assert store.get("session-a", str(tmp_path))["verifier_id"] == "opaque-2"


def test_state_isolated_by_session_and_normalized_root(tmp_path):
    store = VerifierStateStore(tmp_path / "state.json")
    store.record_verification("session-a", str(tmp_path), status="failed")
    assert store.get("session-b", str(tmp_path))["status"] == "unverified"
    assert store.get("session-a", str(tmp_path / "."))["status"] == "failed"


def test_changed_paths_outside_root_are_not_persisted(tmp_path):
    store = VerifierStateStore(tmp_path / "state.json")
    store.record_verification("session-a", str(tmp_path), status="passed")
    state = store.mark_stale("session-a", str(tmp_path), ["../secret.txt", "inside.txt"])
    assert state["changed_paths"] == ["inside.txt"]


def test_retention_bounds_records_and_expired_state(tmp_path):
    path = tmp_path / "state.json"
    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    store = VerifierStateStore(path, max_records=2, retention_seconds=5)
    store.record_verification("old", str(tmp_path), status="passed", verified_at=old)
    store.record_verification("one", str(tmp_path), status="passed")
    store.record_verification("two", str(tmp_path), status="passed")
    assert store.get("old", str(tmp_path))["status"] == "unverified"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["records"]) <= 2


def test_malformed_document_is_unverified_and_repaired_on_write(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not-json", encoding="utf-8")
    store = VerifierStateStore(path)
    assert store.get("session-a", str(tmp_path))["status"] == "unverified"
    store.record_verification("session-a", str(tmp_path), status="passed")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["records"]) == 1


def test_invalid_inputs_fail_closed(tmp_path):
    store = VerifierStateStore(tmp_path / "state.json")
    with pytest.raises(ValueError):
        store.record_verification("", str(tmp_path), status="passed")
    with pytest.raises(ValueError):
        store.record_verification("s", str(tmp_path), status="stale")
    with pytest.raises(ValueError):
        store.record_verification("s", str(tmp_path), status="passed", verified_at="yesterday")


def test_persisted_state_round_trips_and_digest_changes_on_stale(tmp_path):
    path = tmp_path / "state.json"
    first = VerifierStateStore(path)
    first.record_verification("s", str(tmp_path), status="passed", verifier_id="id-1")
    digest_before = first.digest("s", str(tmp_path))
    second = VerifierStateStore(path)
    second.mark_stale("s", str(tmp_path), ["file.py"])
    assert second.get("s", str(tmp_path))["status"] == "stale"
    assert digest_before != second.digest("s", str(tmp_path))


def test_successful_file_mutation_event_marks_state_stale(tmp_path):
    state_path = tmp_path / ".nexus_v5" / "verifier_state.json"
    store = VerifierStateStore(state_path)
    store.record_verification("session-1", str(tmp_path), status="passed")

    class Runtime:
        work_event_sink = None

    class Emitter(V5EventEmitter):
        runtime = Runtime()
        work_event_sink = None
        root_dir = str(tmp_path)
        session_id = "session-1"
        _current_turn_id = "turn-1"
        _stream_events = []
        _tool_started_at = {}

    call = SimpleNamespace(name="modifying", params={"path": "changed.txt"}, call_id="call-1")
    asyncio.run(Emitter()._emit_tool_event(call, status="completed", result="updated"))
    state = VerifierStateStore(state_path).get("session-1", str(tmp_path))
    assert state["status"] == "stale"
    assert state["changed_paths"] == ["changed.txt"]
