from nexus.events import CanonicalEvent, canonical_status


def test_timed_out_is_a_canonical_terminal_status():
    assert canonical_status("timed_out") == "timed_out"

    event = CanonicalEvent.from_work_event(
        {
            "event_type": "run.timed_out",
            "event_id": "evt_timeout",
            "run_id": "run_timeout",
            "status": "timed_out",
            "title": "Run timed out",
        },
        "conversation_timeout",
        1,
    )

    assert event.type == "run.timed_out"
    assert event.status == "timed_out"
