from nexus.task_workflow import complete_task_workflow, start_task_workflow


def test_start_task_workflow_reuses_resume_snapshot():
    calls = []

    result = start_task_workflow(
        "session",
        "continue",
        "turn-2",
        prompt_requests_resume=lambda prompt: True,
        latest_snapshot=lambda session: {"content": "plan", "turn_id": "turn-1"},
        append_todo_events=lambda *args, **kwargs: calls.append((args, kwargs)),
        clear_plan=lambda: calls.append("clear"),
    )

    assert result == "plan"
    assert calls[0][0] == ("session", "plan", "turn-2")
    assert calls[0][1] == {"resumed_from_turn_id": "turn-1"}


def test_complete_task_workflow_normalizes_failure_and_preserves_adapter_contract():
    events = [{
        "kind": "todo",
        "phase_index": 1,
        "title": "Research",
        "task": "do work",
        "items": ["check sources"],
        "status": "running",
        "turn_id": "turn-1",
    }]
    appended = []

    complete_task_workflow(
        "session",
        "do work",
        "turn-1",
        "error",
        safe_session_id=lambda value: value,
        list_events=lambda session, turn: events,
        append_event=lambda session, event: appended.append(event) or event,
        write_plan=lambda content: "workspace/todo.md",
    )

    assert appended == [{**events[0], "status": "failed"}]
