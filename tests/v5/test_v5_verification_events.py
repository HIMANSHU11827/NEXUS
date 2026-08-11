from orchestrators.v5.verification_events import VerifierEventStore


def test_verifier_event_history_persists_bounded_redacted_events(tmp_path):
    store = VerifierEventStore(tmp_path / "events.sqlite3", max_events=2)
    first = store.record(
        "session-1", str(tmp_path), verifier_id="v-1", status="passed",
        command="pytest --token Bearer secret", exit_code=0,
        output_summary="Bearer output-secret",
    )
    store.record("session-1", str(tmp_path), verifier_id="v-2", status="failed", exit_code=1)
    store.record("session-1", str(tmp_path), verifier_id="v-3", status="passed", exit_code=0)
    events = store.list_events("session-1", str(tmp_path), limit=10)
    assert len(events) == 2
    assert events[0]["verifier_id"] == "v-3"
    assert first["event_id"] not in {event["event_id"] for event in events}
    assert all("secret" not in str(event) for event in events)


def test_verifier_event_history_isolated_by_session_and_root(tmp_path):
    store = VerifierEventStore(tmp_path / "events.sqlite3")
    store.record("session-1", str(tmp_path), verifier_id="v-1", status="passed")
    assert store.list_events("session-2", str(tmp_path)) == []
    other = tmp_path / "other"
    other.mkdir()
    assert store.list_events("session-1", str(other)) == []
