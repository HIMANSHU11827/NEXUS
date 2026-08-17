"""Authoritative central command system.

Public surface: :class:`CommandBus`, :class:`CommandRequest`, :class:`CommandResult`,
:class:`CommandHandler`, the alias resolver, and routing/parsing helpers. All
surfaces route through one bus; there is one handler per command.
"""

from nexus.commands.core.command import (
    CommandContext,
    CommandRequest,
    CommandResult,
    CommandStatus,
)
from nexus.commands.core.command_bus import CommandBus
from nexus.commands.core.command_context import CommandInvocation
from nexus.commands.core.command_dispatcher import CommandDispatcher
from nexus.commands.core.command_error import (
    CommandBusError,
    CommandError,
    CommandNotFound,
    CommandRejected,
    CommandTimeout,
)
from nexus.commands.core.command_events import (
    EVENT_DISPATCHED,
    EVENT_FAILURE,
    EVENT_RECEIVED,
    EVENT_REJECTED,
    EVENT_SUCCESS,
    CommandEvent,
)
from nexus.commands.core.command_handler import CommandHandler
from nexus.commands.core.command_pipeline import CommandMiddleware, MiddlewareChain
from nexus.commands.routing.alias_resolver import AliasResolver

__all__ = [
    "CommandBus",
    "CommandRequest",
    "CommandResult",
    "CommandStatus",
    "CommandContext",
    "CommandHandler",
    "CommandDispatcher",
    "CommandInvocation",
    "CommandMiddleware",
    "MiddlewareChain",
    "AliasResolver",
    "CommandEvent",
    "EVENT_RECEIVED",
    "EVENT_DISPATCHED",
    "EVENT_SUCCESS",
    "EVENT_FAILURE",
    "EVENT_REJECTED",
    "CommandError",
    "CommandNotFound",
    "CommandRejected",
    "CommandTimeout",
    "CommandBusError",
]
