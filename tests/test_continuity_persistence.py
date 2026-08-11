import asyncio
import json
import os

from memory import MemoryManager
from memory.continuity import inspect_continuity
from nexus.run_context import start_run_context
from queue.store import TaskQueue
from orchestrators.v5.grounding import V5ContextGrounding


def test_restart_recalls_unfinished_run_and_error(tmp_path):
    context = start_run_context(
        root=str(tmp_path), session_id="s1", run_id="r1",
        prompt="Finish the migration", provider="test",
    )
    context.finish("failed", "run.failed", error="database unavailable")

    snapshot = inspect_continuity(str(tmp_path), "s1")
    assert snapshot.available is True
    assert snapshot.task == "Finish the migration"
    assert snapshot.error == "database unavailable"
    assert "Progress after this evidence is unknown" in snapshot.as_prompt()


def test_newest_successful_run_suppresses_older_failure(tmp_path):
    older = start_run_context(
        root=str(tmp_path), session_id="s1", run_id="old",
        prompt="Old unfinished task", provider="test",
    )
    older.finish("failed", "run.failed", error="old error")
    newer = start_run_context(
        root=str(tmp_path), session_id="s1", run_id="new",
        prompt="New completed task", provider="test",
    )
    newer.finish("completed", "run.completed")

    snapshot = inspect_continuity(str(tmp_path), "s1")
    assert snapshot.available is False


def test_checkpoint_is_continuation_evidence_without_claiming_completion(tmp_path):
    path = tmp_path / ".nexus_v5" / "checkpoints" / "turn_phase.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "session": "s1", "turn_id": "turn-1", "phase": "tools",
        "context_summary": "Investigate the failing import",
        "ts": 10,
    }), encoding="utf-8")

    snapshot = inspect_continuity(str(tmp_path), "s1")
    assert snapshot.source == "checkpoint"
    assert snapshot.task == "Investigate the failing import"
    assert "completed" not in snapshot.as_prompt().lower()


def test_queue_task_survives_new_queue_instance_and_is_session_scoped(tmp_path):
    db = str(tmp_path / "queue.db")
    first = TaskQueue(db_path=db)
    task_id = first.enqueue("Continue the report", session_id="s1")
    TaskQueue(db_path=db).enqueue("Other session", session_id="s2")

    rows = TaskQueue(db_path=db).list_unfinished(session_id="s1")
    assert [row["id"] for row in rows] == [task_id]
    assert rows[0]["payload"]["task_desc"] == "Continue the report"


def test_memory_manager_surfaces_durable_queue_continuity(tmp_path):
    queue = TaskQueue(root=str(tmp_path))
    queue.enqueue("Continue queued work", session_id="s1")

    manager = MemoryManager(str(tmp_path), session_id="s1")
    try:
        snapshot = manager.continuity()
    finally:
        manager.shutdown()

    assert snapshot.available is True
    assert snapshot.source == "task_queue"
    assert snapshot.task == "Continue queued work"


def test_no_durable_evidence_means_no_offer(tmp_path):
    snapshot = inspect_continuity(str(tmp_path), "new")
    assert snapshot.available is False
    assert snapshot.as_prompt() == ""


def test_completed_checkpoint_is_not_continuation_evidence(tmp_path):
    path = tmp_path / ".nexus_v5" / "checkpoints" / "turn_completed.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "session": "s1", "turn_id": "turn-1", "phase": "completed",
        "context_summary": "Already finished task", "ts": 10,
    }), encoding="utf-8")

    snapshot = inspect_continuity(str(tmp_path), "s1")
    assert snapshot.available is False


def test_run_context_reader_uses_safe_session_directory(tmp_path):
    context = start_run_context(
        root=str(tmp_path), session_id="team/alpha", run_id="r1",
        prompt="Continue the migration",
    )
    context.finish("failed", "run.failed", error="blocked")

    snapshot = inspect_continuity(str(tmp_path), "team/alpha")
    assert snapshot.available is True
    assert snapshot.task == "Continue the migration"


def test_run_context_reader_falls_back_to_legacy_session_directory(tmp_path):
    legacy_dir = tmp_path / "logs" / "run_contexts" / "team_alpha"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "legacy.json").write_text(json.dumps({
        "run_id": "legacy",
        "session_id": "team/alpha",
        "status": "failed",
        "prompt_preview": "Resume the legacy task",
        "updated_at": 10,
        "started_at": 9,
    }), encoding="utf-8")

    snapshot = inspect_continuity(str(tmp_path), "team/alpha")

    assert snapshot.available is True
    assert snapshot.task == "Resume the legacy task"


def test_v5_grounding_injects_persisted_continuity(tmp_path):
    context = start_run_context(
        root=str(tmp_path), session_id="s1", run_id="r1", prompt="Fix the parser",
    )
    context.finish("failed", "run.failed", error="bad import")
    manager = MemoryManager(str(tmp_path), session_id="s1")
    try:
        loop = V5ContextGrounding()
        loop.root_dir = str(tmp_path)
        loop.session_id = "s1"
        loop._memory_manager = manager
        messages = asyncio.run(loop._ground_context("continue the parser task"))
        contents = "\n".join(message["content"] for message in messages)
        assert "PERSISTED EVIDENCE" in contents
        assert "Fix the parser" in contents
        assert "Progress after this evidence is unknown" in contents
    finally:
        manager.shutdown()


def test_memory_prefetch_includes_continuity_after_restart(tmp_path):
    context = start_run_context(
        root=str(tmp_path), session_id="s1", run_id="r1", prompt="Fix the parser"
    )
    context.finish("cancelled", "run.cancelled")
    manager = MemoryManager(str(tmp_path), session_id="s1")
    try:
        result = asyncio.run(manager.prefetch_all("continue"))
        assert "Fix the parser" in result.session_history
        assert "PERSISTED EVIDENCE" in result.session_history
    finally:
        manager.shutdown()
