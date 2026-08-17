"""Command-system error types."""

from __future__ import annotations


class CommandError(Exception):
    """Base class for command-system errors."""


class CommandNotFound(CommandError):
    """No handler is registered for the command."""


class CommandRejected(CommandError):
    """Command rejected by middleware (auth/permission/validation/rate-limit)."""


class CommandTimeout(CommandError):
    """Handler exceeded its allotted time."""


class CommandBusError(CommandError):
    """Internal bus failure."""
