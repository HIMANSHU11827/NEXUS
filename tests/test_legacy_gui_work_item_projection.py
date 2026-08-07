import importlib

from nexus.work_items import create_work_item, load_work_item


def test_legacy_gui_append_projects_runtime_task_event(tmp_path, monkeypatch):
    legacy_api = importlib.import_module("gui.api")
    monkeypatch.setattr(legacy_api, "_ROOT", str(tmp_path))
    monkeypatch.setattr(legacy_api, "_WORK_EVENTS_DIR", str(tmp_path / "events"))
    legacy_api._WORK_EVENT_SEQUENCES.clear()
    legacy_api._WORK_EVENT_CACHE.clear()

    create_work_item(
        root=str(tmp_path), session_id="legacy-session", task_id="task-legacy",
        title="Legacy task", status="approved",
    )
    legacy_api.append_work_event(
        "legacy-session",
        {
            "event_id": "legacy-run-start",
            "event_type": "run.started",
            "run_id": "legacy-run",
            "task_id": "task-legacy",
            "status": "running",
        },
    )

    item = load_work_item(str(tmp_path), "legacy-session", "task-legacy")
    assert item is not None
    assert item.status == "running"
    assert item.run_id == "legacy-run"
