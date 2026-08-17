"""Command lifecycle events emitted by the bus (consumed by nexus.events)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class CommandEvent:
    kind: str            # received | dispatched | success | failure | rejected
    command: str
    command_id: str
    source: Optional[str] = None
    elapsed_ms: Optional[float] = None
    detail: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)


# Event kinds
EVENT_RECEIVED = "command.received"
EVENT_DISPATCHED = "command.dispatched"
EVENT_SUCCESS = "command.success"
EVENT_FAILURE = "command.failure"
EVENT_REJECTED = "command.rejected"
