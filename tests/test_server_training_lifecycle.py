import pytest


class _Process:
    pid = 4321

    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode


@pytest.mark.asyncio
async def test_training_endpoint_validates_steps(monkeypatch):
    import apps.api as server

    class Request:
        async def json(self):
            return {"steps": "not-a-number"}

    with pytest.raises(Exception) as raised:
        await server.train_local_engine(Request())
    assert getattr(raised.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_training_endpoint_starts_with_durable_run_status(monkeypatch, tmp_path):
    import subprocess
    import apps.api as server

    process = _Process()
    monkeypatch.setattr(server, "_active_train_process", None)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_write_training_status", lambda payload: setattr(server, "_last_training_status", payload))

    class Request:
        async def json(self):
            return {"steps": 12}

    result = await server.train_local_engine(Request())

    assert result["status"] == "started"
    assert result["steps"] == 12
    assert result["run_id"]
    assert server._last_training_status["status"] == "training"
    assert server._last_training_status["pid"] == 4321


@pytest.mark.asyncio
async def test_training_endpoint_respects_live_cross_process_owner(monkeypatch, tmp_path):
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "_active_train_process", None)
    monkeypatch.setattr(server, "_training_pid_is_alive", lambda pid: True)
    server._write_training_status({"status": "training", "run_id": "other", "pid": 999, "steps": 8})

    class Request:
        async def json(self):
            return {"steps": 12}

    result = await server.train_local_engine(Request())

    assert result["status"] == "running"
    assert result["run_id"] == "other"
    assert result["pid"] == 999


def test_training_status_marks_orphaned_process_after_restart(monkeypatch, tmp_path):
    import json
    import apps.api as server

    monkeypatch.setattr(server, "_PROJECT_ROOT", str(tmp_path))
    status_path = tmp_path / "configure" / "self_improvement_status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"status": "training", "run_id": "r1"}), encoding="utf-8")
    monkeypatch.setattr(server, "_active_train_process", None)

    result = server.train_status()

    assert result["status"] == "orphaned"
    assert result["is_running"] is False
