"""Command handler contract and base implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from nexus.commands.core.command import CommandRequest, CommandResult


class CommandHandler(ABC):
    """A handler implements exactly one command name (dotted)."""

    #: Canonical command this handler serves, e.g. ``task.list``.
    command: str = ""
    #: Human-readable description used by help/discovery.
    description: str = ""
    #: Permission tokens required to invoke (checked by middleware if present).
    required_permissions: List[str] = []

    @abstractmethod
    async def handle(self, request: CommandRequest) -> CommandResult:
        """Execute the command and return a result."""
        raise NotImplementedError

    async def can_handle(self, request: CommandRequest) -> bool:
        return request.command == self.command

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<{type(self).__name__} command={self.command!r}>"
