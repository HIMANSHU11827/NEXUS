"""Canonical, validated runtime event envelope for NEXUS adapters and stores."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

EVENT_TYPES = frozenset(
    """run.started run.status run.completed run.failed run.cancelled
conversation.created conversation.updated message.started message.delta message.completed message.failed
assistant.progress
plan.started plan.updated plan.completed plan.failed phase.started phase.updated phase.completed phase.failed
plan.step.started plan.step.updated plan.step.completed plan.step.failed
tool.started tool.delta tool.completed tool.failed command.started command.stdout command.stderr command.completed command.failed
file.read file.created file.edited file.diff search.started search.result search.completed search.failed
web.started web.result web.completed web.failed test.started test.output test.completed test.failed
subagent.started subagent.status subagent.result subagent.failed subagent.completed handoff.started handoff.completed
approval.requested guardrail.blocked agent.thinking agent.completed
memory.updated skill.used skill.created skill.updated error retry status.changed
checkpoint.created checkpoint.started checkpoint.completed checkpoint.failed checkpoint.restored checkpoint.deleted""".split()
)
EVENT_STATUSES = frozenset({"pending", "running", "success", "failed", "blocked", "skipped", "cancelled"})


def canonical_status(value: Any) -> str:
    status = str(value or "running").lower()
    aliases = {
        "queued": "pending", "done": "success", "completed": "success", "ok": "success",
        "error": "failed", "failure": "failed", "aborted": "cancelled",
    }
    status = aliases.get(status, status)
    if status not in EVENT_STATUSES:
        raise ValueError(f"Unsupported event status: {value!r}")
    return status


def infer_event_type(event: Dict[str, Any], status: str) -> str:
    explicit = str(event.get("event_type") or "")
    if explicit in EVENT_TYPES:
        return explicit
    kind = str(event.get("kind") or event.get("type") or "tool").lower()
    stage = str(event.get("stage") or "").lower()
    stream = str(event.get("stream") or "").lower()
    action = str(event.get("action") or "").lower()
    tool = str(event.get("tool") or event.get("name") or "").lower()
    if stage == "planning" or kind in {"todo", "planning_artifact"}:
        base = "plan"
    elif stage == "memory":
        return "memory.updated"
    elif kind == "command":
        if event.get("append") or event.get("chunk"):
            return "command.stderr" if stream == "stderr" else "command.stdout"
        base = "command"
    elif kind == "file":
        if tool == "reading" or "read" in action:
            return "file.read"
        if tool == "creating" or "create" in action or "write" in action:
            return "file.created"
        if tool == "deleting" or "delete" in action or "remove" in action:
            return "file.edited"
        if event.get("diff") or event.get("patch"):
            return "file.diff"
        return "file.edited"
    elif kind == "search":
        base = "web" if "web" in tool else "search"
        if event.get("append") or event.get("sources"):
            return f"{base}.result"
    elif kind == "test":
        if event.get("append") or event.get("chunk"):
            return "test.output"
        base = "test"
    elif kind in {"hive", "subagent"}:
        base = "subagent"
    elif kind == "skill":
        return "skill.used"
    elif kind in {"error", "retry"}:
        return kind
    elif stage:
        return "status.changed"
    else:
        base = "tool"
    suffix = "started" if status in {"pending", "running"} else "completed" if status == "success" else "failed"
    return f"{base}.{suffix}"


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    run_id: str
    conversation_id: str
    type: str
    title: str
    status: str
    timestamp: float
    sequence: int
    payload: Dict[str, Any] = field(default_factory=dict)
    parent_run_id: Optional[str] = None
    parent_id: Optional[str] = None
    duration_ms: Optional[float] = None
    display: Dict[str, Any] = field(default_factory=dict)
    related_files: List[str] = field(default_factory=list)
    related_command: Optional[str] = None
    related_tool: Optional[str] = None
    related_skill: Optional[str] = None
    related_subagent: Optional[str] = None
    exit_code: Optional[int] = None
    error: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"Unsupported event type: {self.type!r}")
        if self.status not in EVENT_STATUSES:
            raise ValueError(f"Unsupported event status: {self.status!r}")
        if not self.event_id or not self.run_id or not self.conversation_id:
            raise ValueError("event_id, run_id, and conversation_id are required")
        if self.sequence < 1:
            raise ValueError("sequence must be positive")

    @classmethod
    def from_work_event(cls, event: Dict[str, Any], conversation_id: str, sequence: int) -> "CanonicalEvent":
        status = canonical_status(event.get("status"))
        run_id = str(event.get("run_id") or event.get("turn_id") or conversation_id)
        event_id = str(event.get("event_id") or event.get("id") or f"evt_{uuid.uuid4().hex}")
        path = event.get("path")
        related_files = list(event.get("related_files") or ([str(path)] if path else []))
        error_value = (event.get("error") or event.get("stderr")) if status == "failed" else event.get("error")
        error = error_value if isinstance(error_value, dict) else ({"message": str(error_value)} if error_value else None)
        known = {
            "id", "event_id", "run_id", "turn_id", "session_id", "conversation_id", "parent_run_id", "parent_id",
            "event_type", "type", "title", "status", "created_at", "timestamp", "sequence", "duration_ms", "display",
            "related_files", "related_command", "related_tool", "related_skill", "related_subagent", "exit_code", "error",
        }
        nested_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        extra_payload = {k: v for k, v in event.items() if k not in known}
        return cls(
            event_id=event_id, run_id=run_id, conversation_id=conversation_id,
            parent_run_id=event.get("parent_run_id"), parent_id=event.get("parent_id"),
            type=infer_event_type(event, status), title=str(event.get("title") or event.get("action") or "Work event"),
            status=status, timestamp=float(event.get("timestamp") or event.get("created_at") or time.time()), sequence=sequence,
            duration_ms=event.get("duration_ms"), payload={**extra_payload, **nested_payload},
            display=dict(event.get("display") or {}), related_files=related_files,
            related_command=event.get("related_command") or event.get("command"),
            related_tool=event.get("related_tool") or event.get("tool"), related_skill=event.get("related_skill"),
            related_subagent=event.get("related_subagent"), exit_code=event.get("exit_code"), error=error,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
