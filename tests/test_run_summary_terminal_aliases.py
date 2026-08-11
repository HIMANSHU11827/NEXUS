import json


def test_server_and_gui_run_summaries_recognize_timeout_and_cancel_aliases(tmp_path, monkeypatch):
    import gui.api as gui_api
    import server

    event_dir = tmp_path / "events"
    event_dir.mkdir()
    payload = [
        {"event_id": "timeout", "event_type": "run.timed_out", "run_id": "r1", "status": "timed_out"},
        {"event_id": "cancel", "event_type": "run.cancelled", "run_id": "r2", "status": "canceled"},
    ]
    (event_dir / "s.jsonl").write_text("\n".join(json.dumps(item) for item in payload) + "\n", encoding="utf-8")

    monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(event_dir))
    monkeypatch.setattr(gui_api, "_WORK_EVENTS_DIR", str(event_dir))
    monkeypatch.setattr(server, "_WORK_EVENT_CACHE", {})
    monkeypatch.setattr(gui_api, "_WORK_EVENT_CACHE", {})

    assert server.work_event_run_summary("s", "r1")["terminal_event"] == "run.timed_out"
    assert gui_api.work_event_run_summary("s", "r1")["terminal_event"] == "run.timed_out"
    assert server.work_event_run_summary("s", "r2")["terminal_event"] == "run.cancelled"
    assert gui_api.work_event_run_summary("s", "r2")["terminal_event"] == "run.cancelled"
