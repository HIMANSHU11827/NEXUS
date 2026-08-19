"""Bridge between legacy ``nexus.commands.CommandRegistry`` and the new
authoritative ``CommandBus``.

On first ``get_bus()`` call the bridge auto-registers every legacy command
as a ``CommandHandler`` on the bus, so all surfaces (API, TUI, Web, Gateway,
main-agent) flow through one pipeline with middleware, alias resolution,
timeout enforcement, and lifecycle events.

The bridge is lazy and one-shot: it runs once per process and is idempotent.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from nexus.command_system.core.command import (
    CommandContext as BusCommandContext,
    CommandRequest,
    CommandResult as BusCommandResult,
    CommandStatus,
)
from nexus.command_system.core.command_bus import CommandBus
from nexus.command_system.core.command_handler import CommandHandler

logger = logging.getLogger(__name__)

_BRIDGE_BOOTSTRAPPED = False


class _LegacyCommandHandler(CommandHandler):
    """Wraps a single legacy ``nexus.commands.Command`` as a bus handler."""

    def __init__(self, legacy_cmd: Any) -> None:
        self._legacy = legacy_cmd
        self.command = legacy_cmd.name
        self.description = legacy_cmd.description or ""
        self.required_permissions = []

    async def handle(self, request: CommandRequest) -> BusCommandResult:
        # Translate bus request → legacy CommandContext
        ctx = _translate_request_to_legacy_ctx(request)

        try:
            legacy_result = await self._legacy.execute(ctx)
        except Exception as exc:
            logger.error(
                "Legacy command %r failed: %s", self.command, exc, exc_info=True,
            )
            return BusCommandResult.fail(
                f"{type(exc).__name__}: {exc}",
                status=CommandStatus.FAILURE,
                command_id=request.id,
            )

        # Translate legacy CommandResult → bus CommandResult
        return _translate_legacy_result(legacy_result, command_id=request.id)


def _translate_request_to_legacy_ctx(request: CommandRequest) -> Any:
    """Convert a bus ``CommandRequest`` into a legacy ``CommandContext``.

    Passes through all extra fields from options (loop, shell, runtime_settings,
    etc.) so legacy command handlers get the context they expect.
    """
    from nexus.commands import CommandContext

    extra: Dict[str, Any] = dict(request.options) if request.options else {}

    # Pack positional args as the legacy "args" string
    if request.args and "args" not in extra:
        extra["args"] = " ".join(str(a) for a in request.args)

    # Extract known CommandContext fields from options
    loop = extra.pop("loop", None)
    shell = extra.pop("shell", None)
    mode = extra.pop("mode", None)
    provider = extra.pop("provider", None)
    model = extra.pop("model", None)
    thinking = extra.pop("thinking", None)

    return CommandContext(
        session_id=request.context.session_id or "default",
        loop=loop,
        shell=shell,
        mode=mode,
        provider=provider,
        model=model,
        thinking=thinking,
        extra=extra,
    )


def _translate_legacy_result(
    legacy_result: Any, command_id: Optional[str] = None,
) -> BusCommandResult:
    """Convert a legacy ``CommandResult`` into a bus ``CommandResult``."""
    if hasattr(legacy_result, "success") and legacy_result.success:
        status = CommandStatus.SUCCESS
    else:
        status = CommandStatus.FAILURE

    output = getattr(legacy_result, "output", None) or ""
    formatted = getattr(legacy_result, "formatted", None) or ""
    error = getattr(legacy_result, "error", None) or None

    data = {
        "output": output,
        "formatted": formatted,
    }

    return BusCommandResult(
        status=status,
        data=data,
        error=error,
        message=formatted or output or error,
        command_id=command_id,
    )


def bootstrap_bus(bus: CommandBus) -> None:
    """Register all legacy commands on the bus.  Call once per process.

    This is automatically called by ``get_bus()`` on first access.
    """
    global _BRIDGE_BOOTSTRAPPED
    if _BRIDGE_BOOTSTRAPPED:
        return
    _BRIDGE_BOOTSTRAPPED = True

    try:
        from nexus.commands import get_registry
        legacy_registry = get_registry()
    except Exception as exc:
        logger.warning("Cannot load legacy command registry: %s", exc)
        return

    registered = 0
    skipped = 0
    for cmd in legacy_registry.list():
        try:
            handler = _LegacyCommandHandler(cmd)
            bus.register(handler)
            registered += 1
        except ValueError as exc:
            # Duplicate registration — skip silently
            skipped += 1
        except Exception as exc:
            logger.debug("Could not register legacy command %r: %s", cmd.name, exc)
            skipped += 1

    # Import ALL aliases from the legacy registry automatically
    alias_count = 0
    try:
        for cmd in legacy_registry.list():
            for alias_name in getattr(cmd, 'aliases', []):
                if alias_name and bus.dispatcher.has(cmd.name):
                    try:
                        bus.alias(alias_name, cmd.name)
                        alias_count += 1
                    except Exception:
                        pass
    except Exception:
        pass

    # Additional common aliases
    extra_aliases = {
        "bash": "run",
        "shell": "run",
        "cls": "clear",
        "quit": "exit",
        "q": "exit",
        "h": "help",
        "ls": "files",
        "dir": "files",
        "cd": "pwd",
        "hive-team": "hiveteam",
        "roadmap": "plans",
    }
    for alias, canonical in extra_aliases.items():
        if bus.dispatcher.has(canonical):
            try:
                bus.alias(alias, canonical)
                alias_count += 1
            except Exception:
                pass

    logger.info(
        "Command bus bridge: registered %d legacy commands, %d aliases, %d skipped",
        registered, alias_count, skipped,
    )


def patched_get_bus() -> CommandBus:
    """Drop-in replacement for ``command_system.get_bus()`` that auto-bootstraps."""
    from nexus.command_system import get_bus as _original_get_bus

    bus = _original_get_bus()
    bootstrap_bus(bus)
    return bus
