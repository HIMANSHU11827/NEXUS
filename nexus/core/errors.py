"""Core error types for Nexus system coordination."""

from __future__ import annotations


class CoreError(Exception):
    """Base class for all Nexus Core errors."""


class LifecycleError(CoreError):
    """Raised when a lifecycle transition or operation is invalid."""


class StartupError(CoreError):
    """Raised when a startup phase fails."""


class ShutdownError(CoreError):
    """Raised when a shutdown phase fails."""


class DependencyError(CoreError):
    """Raised on dependency resolution or ordering failures."""


class ServiceError(CoreError):
    """Raised on service registration, start, stop, or health failures."""


class GraphError(CoreError):
    """Raised on capability or dependency graph inconsistencies."""


class FatalStartupError(StartupError):
    """A startup failure that must prevent Nexus from running at all."""
