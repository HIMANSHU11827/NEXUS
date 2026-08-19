"""Regression coverage for V5 run lifecycle task identity propagation."""

from types import SimpleNamespace

import pytest

from nexus.main_agent.core import NexusLoopV5


RUN_LIFECYCLE_EVENTS = (
    "run.started",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "run.timed_out",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", RUN_LIFECYCLE_EVENTS)
async def test_run_lifecycle_payload_carries_task_id(event_type, tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path), session_id="task-event-test")
    captured = []
    loop.set_work_event_sink(captured.append)

    await loop._emit_runtime_event(
        event_type,
        "Run",
        "failed" if event_type in {"run.failed", "run.cancelled", "run.timed_out"} else "running",
        event_id="run_turn-1",
        task_id="task-42",
    )

    event = captured[-1]
    assert event["event_type"] == event_type
    assert event["id"] == "run_turn-1"
    assert event["payload"]["task_id"] == "task-42"


@pytest.mark.asyncio
async def test_taskless_run_event_shape_remains_compatible(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path), session_id="taskless-event-test")
    captured = []
    loop.set_work_event_sink(captured.append)

    await loop._emit_runtime_event(
        "run.started",
        "Run started",
        "running",
        event_id="run_turn-2",
        payload={"input_type": "text"},
    )

    event = captured[-1]
    assert event["id"] == "run_turn-2"
    assert event["status"] == "running"
    assert event["payload"] == {"input_type": "text"}
    assert "task_id" not in event["payload"]


@pytest.mark.asyncio
async def test_minimal_v5_run_propagates_task_id_to_start_and_completion(tmp_path):
    loop = NexusLoopV5(root_dir=str(tmp_path), session_id="minimal-task-run")
    captured = []
    loop.set_work_event_sink(captured.append)

    loop.sync_memory = lambda: None
    loop._persist_turn_message = lambda *args, **kwargs: None
    loop._is_trivial_task = lambda _task: True
    async def perceive_input(_turn):
        return _perceived_input()

    async def decide_planning(_perceived):
        return None

    async def inject_hive_context(_perceived):
        return None

    async def run_direct_model_tool_loop(*args, **kwargs):
        return _successful_result()

    loop._perceive_input = perceive_input
    loop._decide_planning = decide_planning
    loop._inject_hive_context = inject_hive_context
    loop._run_direct_model_tool_loop = run_direct_model_tool_loop

    streamed = [
        event async for event in loop._turn_events(
            "hello",
            turn_id="turn-task-1",
            task_id="task-42",
        )
    ]
    lifecycle = {
        event["data"]["event_type"]: event["data"]
        for event in streamed
        if event.get("type") == "status"
        and event.get("data", {}).get("event_type") in {"run.started", "run.completed"}
    }

    assert lifecycle["run.started"]["payload"]["task_id"] == "task-42"
    assert lifecycle["run.completed"]["payload"]["task_id"] == "task-42"
    assert lifecycle["run.started"]["id"] == "run_turn-task-1"
    assert lifecycle["run.completed"]["id"] == "run_turn-task-1"


def _perceived_input():
    return SimpleNamespace(metadata={}, context_summary="")


def _successful_result():
    return {"success": True, "response": "ok", "calls_executed": 0}


@pytest.mark.asyncio
async def test_partial_run_emits_completed_partial_not_bare_failure(tmp_path):
    """A run that ended with verified partial work must be reported as
    run.completed_partial (not plain run.failed), while keeping success=False
    and the failed run-context finish so work items still transition failed."""
    loop = NexusLoopV5(root_dir=str(tmp_path), session_id="partial-run-event")
    captured = []
    loop.set_work_event_sink(captured.append)

    loop.sync_memory = lambda: None
    loop._persist_turn_message = lambda *args, **kwargs: None
    loop._is_trivial_task = lambda _task: True

    async def perceive_input(_turn):
        return _perceived_input()

    async def decide_planning(_perceived):
        return None

    async def inject_hive_context(_perceived):
        return None

    async def run_direct_model_tool_loop(*args, **kwargs):
        return {
            "success": False,
            "partial": True,
            "error": "context exhausted after partial work",
            "response": "partial",
            "calls_executed": 3,
            "verification": {"verified_actions": [{"id": "act-1"}]},
        }

    loop._perceive_input = perceive_input
    loop._decide_planning = decide_planning
    loop._inject_hive_context = inject_hive_context
    loop._run_direct_model_tool_loop = run_direct_model_tool_loop

    streamed = [
        event async for event in loop._turn_events(
            "do the work",
            turn_id="turn-partial-1",
            task_id="task-partial",
        )
    ]
    terminal = [
        event["data"]
        for event in streamed
        if event.get("type") == "status"
        and event.get("data", {}).get("event_type") in {"run.failed", "run.completed_partial"}
    ]

    assert [event["event_type"] for event in terminal] == ["run.completed_partial"]
    payload = terminal[0]["payload"]
    assert payload["success"] is False
    assert payload["partial"] is True
    assert payload["state"] == "failed"
    assert payload["task_id"] == "task-partial"
