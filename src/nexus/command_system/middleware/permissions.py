"""Permission enforcement middleware.

If the resolved handler declares ``required_permissions``, the request context
must carry each token (or the special ``*`` wildcard) or the command is
rejected before reaching the handler. This is the single enforcement point for
command-level permissions; surfaces do not re-implement it.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Set

from nexus.command_system.core.command import CommandResult, CommandStatus
from nexus.command_system.core.command_context import CommandInvocation
from nexus.command_system.core.command_pipeline import CommandMiddleware


class PermissionMiddleware(CommandMiddleware):
    name = "permissions"

    def __init__(self, get_permissions=None) -> None:
        # Optional callable(request) -> Set[str] for dynamic permission lookup.
        self._get_permissions = get_permissions

    async def process(
        self,
        invocation: CommandInvocation,
        call_next: Callable[[CommandInvocation], Awaitable[CommandResult]],
    ) -> CommandResult:
        req = invocation.request
        handler = invocation.middleware_data.get("handler")
        required = getattr(handler, "required_permissions", []) or []
        if not required:
            return await call_next(invocation)

        if self._get_permissions is not None:
            granted = self._get_permissions(req)
        else:
            granted = set(req.context.permissions)
        granted: Set[str] = set(granted)
        if "*" in granted:
            return await call_next(invocation)
        missing = [p for p in required if p not in granted]
        if missing:
            return CommandResult.reject(
                f"missing permissions: {', '.join(missing)}",
                command_id=req.id,
            )
        return await call_next(invocation)
