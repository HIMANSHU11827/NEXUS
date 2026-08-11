import lifecycle.persistence as persistence
from lifecycle.supervisor import ComponentSupervisor, LifecycleStage


def test_supervisor_stats_expose_persistence_health(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(persistence, "_state_dir", lambda: blocked)

    supervisor = ComponentSupervisor(persist_key="health-test")
    supervisor.register("worker", "Worker")
    supervisor.mark_stage("worker", LifecycleStage.INITIALIZING)
    stats = supervisor.get_stats()

    assert "persistence" in stats
    assert stats["persistence"]["available"] is False
    assert stats["persistence"]["operation"] == "save"


def test_supervisor_stats_report_disabled_persistence():
    stats = ComponentSupervisor(persist=False).get_stats()

    assert stats["persistence"]["available"] is True
    assert stats["persistence"]["operation"] == "disabled"
