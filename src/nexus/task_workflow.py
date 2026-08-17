"""Shared task/workflow lifecycle contract for runtime adapters.

The server and legacy GUI keep their own event storage and filesystem roots,
but they must agree on how a chat run resumes and finalizes a visible plan.
This module contains that adapter-neutral state machine; callers inject the
small storage/event functions required by their surface.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List


def start_task_workflow(
    session_id: str,
    prompt: str,
    turn_id: str,
    *,
    prompt_requests_resume: Callable[[str], bool],
    latest_snapshot: Callable[[str], Dict[str, Any]],
    append_todo_events: Callable[..., None],
    clear_plan: Callable[[], None],
) -> str:
    """Prepare one chat attempt and return resumable task context, if any."""
    if prompt_requests_resume(prompt):
        snapshot = latest_snapshot(session_id)
        content = str(snapshot.get("content") or "")
        if content:
            append_todo_events(
                session_id,
                content,
                turn_id,
                resumed_from_turn_id=str(snapshot.get("turn_id") or ""),
            )
            return content
    clear_plan()
    return ""


def complete_task_workflow(
    session_id: str,
    prompt: str,
    turn_id: str,
    status: str = "done",
    *,
    safe_session_id: Callable[[str], str],
    list_events: Callable[[str, str], List[Dict[str, Any]]],
    append_event: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    write_plan: Callable[[str], str],
) -> None:
    """Finalize task phases using canonical done/failed/cancelled semantics."""
    sid = safe_session_id(session_id)
    events = list_events(sid, turn_id)
    todo_events = [
        event for event in events
        if event.get("kind") == "todo" and event.get("phase_index") is not None
    ]
    if not todo_events:
        return

    todo_events.sort(key=lambda event: int(event.get("phase_index") or 0))
    final_status = {"error": "failed", "failure": "failed"}.get(
        str(status or "done").lower(), str(status or "done").lower()
    )
    if final_status != "done":
        for event in todo_events:
            if str(event.get("status") or "").lower() in {"running", "working"}:
                event["status"] = final_status
                append_event(sid, event)
        return

    updated_events: List[Dict[str, Any]] = []
    for event in todo_events:
        items = event.get("items") or []
        event["checked_items"] = list(items)
        event["status"] = "done"
        updated_events.append(event)

    prompt_text = todo_events[0].get("task", "Agent Workspace Plan")
    lines = ["## TODO List", "", f"Task: {prompt_text}", ""]
    for event in todo_events:
        index = event.get("phase_index")
        title = event.get("title")
        items = event.get("items") or []
        lines.append(f"- [x] Phase {index}: {title}")
        for item in items:
            lines.append(f"  - [x] {item}")

    todo_content = "\n".join(lines).strip() + "\n"
    todo_rel_path = write_plan(todo_content)
    updated_events.append({
        "kind": "file",
        "type": "file",
        "action": "Edit file",
        "title": "todo.md",
        "task": prompt_text,
        "target": todo_rel_path,
        "path": todo_rel_path,
        "preview": todo_content,
        "status": "done",
        "turn_id": turn_id,
        "phase": f"Phase {len(todo_events)}: {todo_events[-1].get('title')}",
        "phase_index": len(todo_events),
        "role": "planning_artifact",
    })
    for event in updated_events:
        append_event(sid, event)
