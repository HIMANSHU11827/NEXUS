"""Command middleware base + chain runner.

Middleware components run in order before/after the handler, implementing the
cross-cutting concerns from the target architecture: authentication,
authorization, permissions, validation, rate limiting, logging, tracing,
retries, idempotency, and error handling. Each middleware may short-circuit the
invocation (e.g. reject an unauthorized request).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, List, Optional

from nexus.commands.core.command import CommandRequest, CommandResult, CommandStatus
from nexus.commands.core.command_events import EVENT_REJECTED
from nexus.commands.core.command_context import CommandInvocation


class CommandMiddleware(ABC):
    """A single cross-cutting concern in the command pipeline."""

    name: str = "middleware"

    @abstractmethod
    async def process(
        self,
        invocation: CommandInvocation,
        call_next: Callable[[CommandInvocation], Awaitable[CommandResult]],
    ) -> CommandResult:
        """Run the concern, then delegate to ``call_next`` (or short-circuit)."""
        raise NotImplementedError


class MiddlewareChain:
    """Runs an ordered list of middleware around the terminal handler."""

    def __init__(self, middlewares: Optional[List[CommandMiddleware]] = None) -> None:
        self._middlewares: List[CommandMiddleware] = list(middlewares or [])

    def add(self, mw: CommandMiddleware) -> None:
        self._middlewares.append(mw)

    def clear(self) -> None:
        self._middlewares.clear()

    @property
    def middlewares(self) -> List[CommandMiddleware]:
        return list(self._middlewares)

    async def run(
        self,
        invocation: CommandInvocation,
        terminal: Callable[[CommandInvocation], Awaitable[CommandResult]],
    ) -> CommandResult:
        # Build the nested callable: terminal wrapped by each middleware in
        # reverse order so the first registered middleware is outermost.
        call = terminal
        for mw in reversed(self._middlewares):
            call = _wrap(mw, call)
        return await call(invocation)


def _wrap(
    mw: CommandMiddleware,
    call: Callable[[CommandInvocation], Awaitable[CommandResult]],
) -> Callable[[CommandInvocation], Awaitable[CommandResult]]:
    async def inner(inv: CommandInvocation) -> CommandResult:
        return await mw.process(inv, call)
    return inner
