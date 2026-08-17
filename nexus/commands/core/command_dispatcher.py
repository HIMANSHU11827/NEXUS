"""Command dispatcher: resolves a command name to its registered handler.

There is exactly one authoritative handler per command name. Aliases are
resolved upstream by the alias resolver so the dispatcher always sees canonical
names. The dispatcher is the single place that knows the handler registry.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from nexus.commands.core.command import CommandRequest, CommandResult, CommandStatus
from nexus.commands.core.command_error import CommandNotFound
from nexus.commands.core.command_handler import CommandHandler


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: Dict[str, CommandHandler] = {}

    def register(self, handler: CommandHandler) -> None:
        if not handler.command:
            raise ValueError("Handler declares no command name")
        if handler.command in self._handlers and \
                type(self._handlers[handler.command]) is not type(handler):
            # Allow re-registration of an identical handler class (idempotent),
            # reject registering two different implementations for one command.
            raise ValueError(
                f"Duplicate handler for command {handler.command!r}: "
                f"{type(self._handlers[handler.command]).__name__} vs "
                f"{type(handler).__name__}"
            )
        self._handlers[handler.command] = handler

    def unregister(self, command: str) -> None:
        self._handlers.pop(command, None)

    def get(self, command: str) -> Optional[CommandHandler]:
        return self._handlers.get(command)

    def has(self, command: str) -> bool:
        return command in self._handlers

    @property
    def commands(self) -> List[str]:
        return sorted(self._handlers)

    async def dispatch(self, request: CommandRequest) -> CommandResult:
        handler = self._handlers.get(request.command)
        if handler is None:
            raise CommandNotFound(
                f"No handler registered for command {request.command!r}"
            )
        return await handler.handle(request)
