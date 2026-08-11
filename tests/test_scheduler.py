import time
import json

from tasks.scheduler import NexusTaskScheduler


def _wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_scheduler_persists_pending_jobs_across_restart(tmp_path):
    state = tmp_path / "scheduler.json"
    first = NexusTaskScheduler(lambda _desc: None, state_path=str(state), poll_seconds=0.05)
    try:
        first.schedule("later", "continue work", 60)
    finally:
        first.stop()

    calls = []
    second = NexusTaskScheduler(calls.append, state_path=str(state), poll_seconds=0.01)
    try:
        assert second.list_tasks()[0]["name"] == "later"
        second.scheduled_tasks[0]["run_at"] = time.time() - 1
        assert _wait_until(lambda: calls == ["continue work"])
        assert second.list_tasks() == []
    finally:
        second.stop()


def test_scheduler_retries_then_marks_success(tmp_path):
    calls = []

    def runner(desc):
        calls.append(desc)
        if len(calls) == 1:
            raise RuntimeError("transient")

    scheduler = NexusTaskScheduler(runner, state_path=str(tmp_path / "scheduler.json"), poll_seconds=0.01)
    try:
        scheduler.schedule("retry", "retry me", 0, retry_delay_seconds=0.01)
        assert _wait_until(lambda: calls == ["retry me", "retry me"])
        assert scheduler.list_tasks() == []
    finally:
        scheduler.stop()


def test_scheduler_recovers_orphaned_running_task_after_restart(tmp_path):
    state = tmp_path / "scheduler.json"
    state.write_text(json.dumps({
        "version": 1,
        "tasks": [{
            "task_id": "orphan",
            "name": "orphaned",
            "task_desc": "resume this",
            "run_at": time.time() + 3600,
            "running": True,
            "executed": False,
            "status": "running",
            "attempts": 1,
            "max_attempts": 3,
        }],
    }), encoding="utf-8")
    calls = []
    scheduler = NexusTaskScheduler(calls.append, state_path=str(state), poll_seconds=0.01)
    try:
        assert _wait_until(lambda: calls == ["resume this"])
        assert scheduler.list_tasks() == []
    finally:
        scheduler.stop()


def test_scheduler_state_path_without_parent_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scheduler = NexusTaskScheduler(lambda _desc: None, state_path="scheduler.json", poll_seconds=0.05)
    try:
        scheduler.schedule("local", "persist locally", 60)
        assert (tmp_path / "scheduler.json").is_file()
    finally:
        scheduler.stop()
