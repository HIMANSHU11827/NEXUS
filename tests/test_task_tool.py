import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from tools.task.scripts.task import TaskTool
from nexus.work_items import load_work_item, project_work_item_event


def test_missing_update_id_is_safe_noop(tmp_path):
    tool = TaskTool(str(tmp_path))
    result = asyncio.run(tool.execute(action="update", status="completed"))

    assert result.success is True
    assert result.metadata["skipped"] is True
    assert "no task id" in result.output.lower()
    assert not (tmp_path / ".nexus" / "tasks" / "tasks.json").exists()


def test_missing_delete_id_never_deletes_all_tasks(tmp_path):
    tool = TaskTool(str(tmp_path))
    asyncio.run(tool.execute(action="create", id="task-1", title="Keep me"))

    result = asyncio.run(tool.execute(action="delete"))
    plan = (tmp_path / "todo.md").read_text(encoding="utf-8")

    assert result.success is True
    assert result.metadata["skipped"] is True
    assert "[task-1] Keep me" in plan


def test_task_create_list_update_and_status_share_planning_todo(tmp_path):
    tool = TaskTool(str(tmp_path))

    created = asyncio.run(tool.execute(action="create", title="Inspect the system"))
    listed = asyncio.run(tool.execute(action="list"))
    updated = asyncio.run(tool.execute(action="update", id="task-1", status="completed"))
    current = asyncio.run(tool.execute(action="status", id="task-1"))

    assert created.success is True
    assert "task-1" in created.output
    assert listed.metadata["source"] == "todo.md"
    assert "Inspect the system" in listed.output
    assert updated.success is True
    assert "completed" in current.output
    assert "[x] [task-1] Inspect the system" in (tmp_path / "todo.md").read_text(encoding="utf-8")


def test_concurrent_task_creates_preserve_both_plan_updates(tmp_path):
    def create(title):
        return asyncio.run(TaskTool(str(tmp_path)).execute(action="create", title=title))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("First concurrent task", "Second concurrent task")))

    assert all(result.success for result in results)
    plan = (tmp_path / "todo.md").read_text(encoding="utf-8")
    assert "First concurrent task" in plan
    assert "Second concurrent task" in plan


def test_unknown_task_id_remains_a_real_failure(tmp_path):
    tool = TaskTool(str(tmp_path))
    asyncio.run(tool.execute(action="create", title="Known task"))

    result = asyncio.run(tool.execute(action="update", id="task-999", status="completed"))

    assert result.success is False
    assert "task-999" in result.error


def test_task_tool_reads_and_updates_a_plan_created_by_planning(tmp_path):
    (tmp_path / "todo.md").write_text(
        "TODO LIST\n\nTASK NAME: Existing plan\nPLAN TYPE: Simple\n\n"
        "1. [ ] Inspect the code\n2. [ ] Run focused tests\n",
        encoding="utf-8",
    )
    tool = TaskTool(str(tmp_path))

    listed = asyncio.run(tool.execute(action="list"))
    updated = asyncio.run(tool.execute(action="update", id="task-2", status="completed"))

    assert "task-1: [pending] Inspect the code" in listed.output
    assert updated.success is True
    assert "2. [x] [task-2] Run focused tests" in (tmp_path / "todo.md").read_text(encoding="utf-8")


def test_legacy_json_tasks_are_migrated_to_the_planning_todo(tmp_path):
    legacy_path = tmp_path / ".nexus" / "tasks" / "tasks.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps([{"id": "legacy-1", "title": "Old task", "status": "completed"}]), encoding="utf-8")

    result = asyncio.run(TaskTool(str(tmp_path)).execute(action="list"))

    assert result.success is True
    assert "legacy-1: [completed] Old task" in result.output
    assert "[x] [legacy-1] Old task" in (tmp_path / "todo.md").read_text(encoding="utf-8")


def test_task_completion_does_not_override_active_projected_run(tmp_path):
    tool = TaskTool(str(tmp_path))
    asyncio.run(tool.execute(action="create", id="task-a", title="Run-owned task", session_id="s4"))
    project_work_item_event(
        root=str(tmp_path), session_id="s4",
        event={
            "event_id": "task-start",
            "event_type": "run.started",
            "task_id": "task-a",
            "run_id": "run-a",
        },
    )

    result = asyncio.run(tool.execute(action="update", id="task-a", status="completed", session_id="s4"))
    item = load_work_item(str(tmp_path), "s4", "task-a")

    assert result.success is True
    assert item is not None
    assert item.status == "running"


def test_task_persistence_does_not_block_event_loop(tmp_path, monkeypatch):
    tool = TaskTool(str(tmp_path))
    original = tool._execute_sync

    def slow_persistence(*args, **kwargs):
        import time

        time.sleep(0.08)
        return original(*args, **kwargs)

    monkeypatch.setattr(tool, "_execute_sync", slow_persistence)

    async def run_with_heartbeat():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            result = await tool.execute(action="create", title="Heartbeat task")
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        return result, ticks

    result, ticks = asyncio.run(run_with_heartbeat())
    assert result.success is True
    assert ticks >= 4
