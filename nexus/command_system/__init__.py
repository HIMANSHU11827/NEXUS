"""Authoritative central command system (lives at ``nexus.command_system``).

NOTE ON NAMING: the legacy module ``nexus/commands.py`` is the live 152-command
catalog used by the running TUI/server. To avoid shadowing it, the new
authoritative bus + contracts live here at ``nexus.command_system``. Both can
coexist: legacy code imports ``nexus.commands`` (the catalog); new code imports
``nexus.command_system`` (the bus). A future migration can route legacy commands
through this bus, but that is not done here to avoid breaking the running system.

All surfaces route through one bus; there is one handler per command.
"""

from nexus.command_system.core.command import (
    CommandContext,
    CommandRequest,
    CommandResult,
    CommandStatus,
)
from nexus.command_system.core.command_bus import CommandBus
from nexus.command_system.core.command_context import CommandInvocation
from nexus.command_system.core.command_dispatcher import CommandDispatcher
from nexus.command_system.core.command_error import (
    CommandBusError,
    CommandError,
    CommandNotFound,
    CommandRejected,
    CommandTimeout,
)
from nexus.command_system.core.command_events import (
    EVENT_DISPATCHED,
    EVENT_FAILURE,
    EVENT_RECEIVED,
    EVENT_REJECTED,
    EVENT_SUCCESS,
    CommandEvent,
)
from nexus.command_system.core.command_handler import CommandHandler
from nexus.command_system.core.command_pipeline import CommandMiddleware, MiddlewareChain
from nexus.command_system.routing.alias_resolver import AliasResolver

# Single authoritative bus instance for the running process.
_DEFAULT_BUS = CommandBus()


def get_registry():
    """Bridge for the pre-existing test: return the authoritative command bus."""
    return _DEFAULT_BUS


def get_bus() -> CommandBus:
    return _DEFAULT_BUS


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
    "get_registry",
    "get_bus",
]
