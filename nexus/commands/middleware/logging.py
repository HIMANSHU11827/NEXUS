"""Concrete logging + tracing middleware."""

from __future__ import annotations

from typing import Awaitable, Callable, List

from nexus.commands.core.command import CommandRequest, CommandResult
from nexus.commands.core.command_context import CommandInvocation
from nexus.commands.core.command_pipeline import CommandMiddleware


class LoggingMiddleware(CommandMiddleware):
    name = "logging"

    def __init__(self, sink=None) -> None:
        self._sink = sink or print

    async def process(
        self,
        invocation: CommandInvocation,
        call_next: Callable[[CommandInvocation], Awaitable[CommandResult]],
    ) -> CommandResult:
        req: CommandRequest = invocation.request
        self._sink(f"[command] -> {req.command} src={req.context.source}")
        result = await call_next(invocation)
        self._sink(f"[command] <- {req.command} {result.status.value}")
        return result
