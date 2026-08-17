"""Command context carried by the bus during a single request lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from nexus.commands.core.command import CommandContext, CommandRequest, CommandResult


@dataclass
class CommandInvocation:
    """Mutable per-request state threaded through middleware and the handler."""

    request: CommandRequest
    result: Optional[CommandResult] = None
    started_at: float = 0.0
    stopped_at: float = 0.0
    skip_handler: bool = False  # middleware may short-circuit (e.g. reject)
    middleware_data: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "CommandContext",
    "CommandInvocation",
]
