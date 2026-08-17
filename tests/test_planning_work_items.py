import asyncio

from tools.planning.scripts.planning import PlanningTool
from nexus.work_items import load_work_item, project_work_item_event, reconcile_checklist_work_item


def _run_event(event_type, *, task_id="task-a", run_id="run-a"):
    return {
        "event_id": f"{event_type}-{task_id}",
        "event_type": event_type,
        "task_id": task_id,
        "run_id": run_id,
    }


def test_planner_assigns_stable_ids_and_reuses_them_on_regeneration(tmp_path):
    tool = PlanningTool(str(tmp_path))
    spec = {"plan_type": "simple", "steps": ["Inspect code", "Implement fix", "Run tests"]}

    first = asyncio.run(tool.execute(action="create", goal="Fix the loop", plan_spec=spec, session_id="s1"))
    first_ids = [line.split("] [", 1)[1].split("]", 1)[0] for line in first.output.splitlines() if "] [task_" in line]
    second = asyncio.run(tool.execute(action="create", goal="Fix the loop", plan_spec=spec, session_id="s1"))
    second_ids = [line.split("] [", 1)[1].split("]", 1)[0] for line in second.output.splitlines() if "] [task_" in line]

    assert len(first_ids) == 3
    assert first_ids == second_ids
    assert load_work_item(str(tmp_path), "s1", first_ids[0]) is not None


def test_task_status_reconciliation_updates_work_item(tmp_path):
    tool = PlanningTool(str(tmp_path))
    spec = {"plan_type": "simple", "steps": ["Inspect code", "Implement fix", "Run tests"]}
    created = asyncio.run(tool.execute(action="create", goal="Fix the loop", plan_spec=spec, session_id="s2"))
    task_id = next(line.split("] [", 1)[1].split("]", 1)[0] for line in created.output.splitlines() if "] [task_" in line)

    from tools.task.scripts.task import TaskTool
    updated = asyncio.run(TaskTool(str(tmp_path)).execute(action="update", id=task_id, status="completed", session_id="s2"))
    item = load_work_item(str(tmp_path), "s2", task_id)

    assert updated.success is True
    assert item is not None
    assert item.status == "applied"


def test_planner_checklist_cannot_mark_active_run_applied(tmp_path):
    reconcile_checklist_work_item(
        root=str(tmp_path), session_id="s3", task_id="task-a",
        title="Active task", checklist_status="pending",
    )
    project_work_item_event(
        root=str(tmp_path), session_id="s3",
        event=_run_event("run.started"),
    )

    planner = PlanningTool(str(tmp_path))
    planner._sync_work_items(
        "1. [x] [task-a] Active task",
        "s3",
    )
    item = load_work_item(str(tmp_path), "s3", "task-a")

    assert item is not None
    assert item.status == "running"
    project_work_item_event(
        root=str(tmp_path), session_id="s3",
        event=_run_event("run.failed", task_id="task-a"),
    )
    assert load_work_item(str(tmp_path), "s3", "task-a").status == "failed"


def test_planning_persistence_does_not_block_event_loop(tmp_path, monkeypatch):
    tool = PlanningTool(str(tmp_path))
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
            result = await tool.execute(
                action="create",
                goal="Fix the loop",
                plan_spec={"plan_type": "simple", "steps": [
                    "Inspect code", "Implement fix", "Run tests",
                ]},
                session_id="heartbeat",
            )
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        return result, ticks

    result, ticks = asyncio.run(run_with_heartbeat())
    assert result.success is True
    assert ticks >= 4


def test_planner_accepts_legacy_phase_keys_and_reports_persisted_path(tmp_path):
    tool = PlanningTool(str(tmp_path))
    result = asyncio.run(tool.execute(
        action="create",
        goal="Exercise planning",
        plan_spec={
            "plan_type": "phased",
            "phases": [
                {"name": "Prepare", "tasks": ["Inspect the request"]},
                {"name": "Verify", "tasks": ["Run the planning check"]},
            ],
        },
        session_id="legacy-schema",
    ))

    assert result.success is True
    assert "PHASE 1: Prepare" in result.output
    assert f"Persisted file: {tmp_path / 'todo.md'}" in result.output
