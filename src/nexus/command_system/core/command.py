"""Core command contracts: the universal request/result types.

Every surface - CLI, TUI, API, web, desktop, mobile, gateway, main agent, Hive,
workflows, automation, internal services - expresses intent as a ``CommandRequest``
and receives a ``CommandResult``. There is exactly one command bus and one
implementation per command; no surface re-implements command business logic.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CommandStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    REJECTED = "rejected"     # auth/permission/validation rejection
    NOT_FOUND = "not_found"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class CommandContext:
    """Who/what issued the command and the ambient session."""

    source: str = "internal"          # cli | tui | api | telegram | main_agent | ...
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    request_id: Optional[str] = None
    permissions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandRequest:
    """Universal, typed command request.

    ``command`` is a dotted name (e.g. ``task.list``, ``goal.create``). ``args``
    carries positional arguments; ``options`` carries named options. Surfaces
    translate their own syntax into this single shape.
    """

    command: str
    args: List[Any] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)
    context: CommandContext = field(default_factory=CommandContext)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    timeout: Optional[float] = None

    def as_dotted(self) -> str:
        return self.command

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "command": self.command,
            "args": self.args,
            "options": self.options,
            "context": {
                "source": self.context.source,
                "user_id": self.context.user_id,
                "session_id": self.context.session_id,
                "agent_id": self.context.agent_id,
                "request_id": self.context.request_id,
                "permissions": self.context.permissions,
            },
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommandRequest":
        ctx = data.get("context", {}) or {}
        return cls(
            command=data["command"],
            args=data.get("args", []),
            options=data.get("options", {}),
            context=CommandContext(
                source=ctx.get("source", "internal"),
                user_id=ctx.get("user_id"),
                session_id=ctx.get("session_id"),
                agent_id=ctx.get("agent_id"),
                request_id=ctx.get("request_id"),
                permissions=ctx.get("permissions", []),
            ),
            id=data.get("id", uuid.uuid4().hex),
            timeout=data.get("timeout"),
        )


@dataclass
class CommandResult:
    status: CommandStatus
    data: Any = None
    error: Optional[str] = None
    message: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    command_id: Optional[str] = None
    elapsed_ms: Optional[float] = None

    def is_success(self) -> bool:
        return self.status in (CommandStatus.SUCCESS, CommandStatus.PARTIAL)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "message": self.message,
            "events": self.events,
            "metadata": self.metadata,
            "command_id": self.command_id,
            "elapsed_ms": self.elapsed_ms,
        }

    @classmethod
    def ok(cls, data: Any = None, message: Optional[str] = None,
           command_id: Optional[str] = None) -> "CommandResult":
        return cls(CommandStatus.SUCCESS, data=data, message=message,
                   command_id=command_id)

    @classmethod
    def fail(cls, error: str, status: CommandStatus = CommandStatus.FAILURE,
             command_id: Optional[str] = None) -> "CommandResult":
        return cls(status, error=error, command_id=command_id)

    @classmethod
    def reject(cls, reason: str, command_id: Optional[str] = None) -> "CommandResult":
        return cls(CommandStatus.REJECTED, error=reason, command_id=command_id)
