import json

import nexus.lifecycle.managers.persistence as persistence


def test_lifecycle_persistence_round_trip_reports_durable_status(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_state_dir", lambda: tmp_path)

    assert persistence.save_state("worker/../state", {"stage": "ready"})
    assert persistence.load_state("worker/../state") == {"stage": "ready"}
    status = persistence.persistence_status("worker/../state")
    assert status["available"] is True
    assert status["operation"] == "load"
    assert (tmp_path / "worker___state.json").exists()


def test_lifecycle_persistence_surfaces_corrupt_read_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_state_dir", lambda: tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    assert persistence.load_state("broken") is None
    status = persistence.persistence_status("broken")
    assert status["available"] is False
    assert status["operation"] == "load"
    assert status["error"]


def test_lifecycle_persistence_write_failure_is_explicit_but_nonfatal(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(persistence, "_state_dir", lambda: blocked)

    assert persistence.save_state("worker", {"stage": "ready"}) is False
    status = persistence.persistence_status("worker")
    assert status["available"] is False
    assert status["operation"] == "save"
