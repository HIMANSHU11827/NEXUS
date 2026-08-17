"""NEXUS Plugin Runtime."""
from .manager import (
    CRASH_LOOP_THRESHOLD,
    HookRegistry,
    PluginContext,
    PluginManager,
    PluginRecord,
    PluginStage,
    PluginToolAdapter,
)
from .trust import (
    LEGACY_DEFAULT_CAPABILITIES,
    check_capability,
    resolve_capabilities,
)

__all__ = [
    "PluginManager",
    "PluginContext",
    "PluginRecord",
    "PluginStage",
    "HookRegistry",
    "PluginToolAdapter",
    "CRASH_LOOP_THRESHOLD",
    "LEGACY_DEFAULT_CAPABILITIES",
    "check_capability",
    "resolve_capabilities",
]
