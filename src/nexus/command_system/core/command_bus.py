"""The central Command Bus - the single entry point for all command execution.

Flow (authoritative, one implementation):

    CommandRequest  ->  [middleware chain]  ->  dispatcher  ->  CommandResult

The bus:
* resolves aliases (so callers may use ``task ls`` or ``tasks``),
* runs the middleware pipeline (auth, authz, permissions, validation,
  rate-limit, logging, tracing, retries, idempotency, error handling),
* dispatches to the canonical handler,
* enforces a per-command timeout,
* emits command lifecycle events.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Dict, List, Optional

from nexus.command_system.core.command import CommandRequest, CommandResult, CommandStatus
from nexus.command_system.core.command_context import CommandInvocation
from nexus.command_system.core.command_dispatcher import CommandDispatcher
from nexus.command_system.core.command_error import CommandNotFound, CommandTimeout
from nexus.command_system.core.command_events import (
    EVENT_DISPATCHED,
    EVENT_FAILURE,
    EVENT_RECEIVED,
    EVENT_SUCCESS,
    CommandEvent,
)
from nexus.command_system.core.command_pipeline import MiddlewareChain
from nexus.command_system.routing.alias_resolver import AliasResolver


class CommandBus:
    def __init__(self) -> None:
        self.dispatcher = CommandDispatcher()
        self.middleware = MiddlewareChain()
        self.aliases = AliasResolver()
        self._listeners: List[Callable[[CommandEvent], None]] = []

    # -- subscription -----------------------------------------------------
    def on_event(self, listener: Callable[[CommandEvent], None]) -> None:
        self._listeners.append(listener)

    def _emit(self, event: CommandEvent) -> None:
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - listener must not break the bus
                pass

    # -- registration -----------------------------------------------------
    def register(self, handler) -> None:
        self.dispatcher.register(handler)

    def alias(self, alias: str, canonical: str) -> None:
        self.aliases.add(alias, canonical)

    # -- execution --------------------------------------------------------
    async def execute(self, request: CommandRequest) -> CommandResult:
        # 1. alias resolution
        request.command = self.aliases.resolve(request.command)
        self._emit(CommandEvent(EVENT_RECEIVED, request.command, request.id,
                                source=request.context.source))

        invocation = CommandInvocation(request=request, started_at=time.time())
        # Resolve the handler once and attach it so middleware (e.g. permission
        # enforcement) can inspect required_permissions without re-dispatching.
        invocation.middleware_data["handler"] = self.dispatcher.get(request.command)

        async def terminal(inv: CommandInvocation) -> CommandResult:
            self._emit(CommandEvent(EVENT_DISPATCHED, inv.request.command,
                                    inv.request.id, source=inv.request.context.source))
            try:
                result = await asyncio.wait_for(
                    self.dispatcher.dispatch(inv.request),
                    timeout=inv.request.timeout,
                )
            except asyncio.TimeoutError:
                raise CommandTimeout(
                    f"Command {inv.request.command!r} timed out"
                ) from None
            except CommandNotFound:
                raise
            return result

        try:
            result = await self.middleware.run(invocation, terminal)
        except CommandNotFound as exc:
            result = CommandResult.fail(str(exc), CommandStatus.NOT_FOUND,
                                        command_id=request.id)
        except CommandTimeout as exc:
            result = CommandResult.fail(str(exc), CommandStatus.TIMEOUT,
                                        command_id=request.id)
        except Exception as exc:  # noqa: BLE001 - never let the bus crash
            result = CommandResult.fail(f"{type(exc).__name__}: {exc}",
                                        command_id=request.id)
        finally:
            invocation.stopped_at = time.time()

        result.command_id = result.command_id or request.id
        if result.elapsed_ms is None:
            result.elapsed_ms = round(
                (invocation.stopped_at - invocation.started_at) * 1000, 2
            )

        if result.is_success():
            self._emit(CommandEvent(EVENT_SUCCESS, request.command, request.id,
                                    elapsed_ms=result.elapsed_ms))
        else:
            self._emit(CommandEvent(EVENT_FAILURE, request.command, request.id,
                                    elapsed_ms=result.elapsed_ms,
                                    detail=result.error))
        return result

    # convenience sync-bridge helper for non-async callers
    def execute_sync(self, request: CommandRequest) -> CommandResult:
        return asyncio.get_event_loop().run_until_complete(self.execute(request))
