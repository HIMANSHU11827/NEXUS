import asyncio
import inspect

from nexus.control_plane import (
    create_plan_version,
    load_plan,
    project_plan_event,
    ready_steps,
    transition_step,
)
from orchestrators.v5.core import NexusLoopV5


def test_durable_plan_steps_enforce_dependencies_and_project_run_events(tmp_path):
    plan = create_plan_version(
        root=str(tmp_path), session_id="s1", task_id="task-a", title="Ship feature",
        steps=[
            {"step_id": "inspect", "title": "Inspect"},
            {"step_id": "implement", "title": "Implement", "dependencies": ["inspect"]},
        ],
    )
    assert [step.step_id for step in ready_steps(plan)] == ["inspect"]
    try:
        transition_step(root=str(tmp_path), session_id="s1", plan_id=plan.plan_id, step_id="implement", status="running")
    except ValueError as exc:
        assert "dependencies" in str(exc)
    else:
        raise AssertionError("dependent step started before prerequisite")

    assert project_plan_event(root=str(tmp_path), session_id="s1", event={
        "event_id": "started", "event_type": "run.started", "plan_id": plan.plan_id,
        "step_id": "inspect", "run_id": "run-1",
    }) is not None
    completed = project_plan_event(root=str(tmp_path), session_id="s1", event={
        "event_id": "completed", "event_type": "run.completed", "plan_id": plan.plan_id,
        "step_id": "inspect", "run_id": "run-1",
    })
    assert completed is not None
    assert load_plan(str(tmp_path), "s1", plan.plan_id).step("inspect").status == "succeeded"


def test_stream_run_accepts_an_absolute_deadline():
    signature = inspect.signature(NexusLoopV5.stream_run)
    assert "deadline_at" in signature.parameters
