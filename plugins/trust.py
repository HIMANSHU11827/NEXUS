"""Trust policy for installing executable third-party plugin source."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, FrozenSet, Optional


class PluginInstallDisabled(PermissionError):
    pass


# ── Capability allowlist ────────────────────────────────────────────────────
# A plugin declares (from its metadata manifest) the capabilities it may use.
# ``PluginRecord.capabilities`` gates what a plugin may register or do.  There
# is no unrestricted default: external-resource capabilities (network / files /
# mcp) are DENIED unless an operator explicitly grants them in the manifest.
# The legacy default below only opens the in-process integration surface
# (tools / hooks / cli), preserving how existing bundled plugins behave.

CAPABILITY_TOOLS = "tools"      # register tools into the live tool registry
CAPABILITY_HOOKS = "hooks"      # register lifecycle hook callbacks
CAPABILITY_CLI = "cli"          # register CLI subcommands
CAPABILITY_NETWORK = "network"  # granted network access (bookkeeping)
CAPABILITY_FILES = "files"      # granted filesystem access (bookkeeping)
CAPABILITY_MCP = "mcp"          # granted MCP server access (bookkeeping)

#: Every capability the trust model understands.  Anything else is dropped.
KNOWN_CAPABILITIES = frozenset({
    CAPABILITY_TOOLS,
    CAPABILITY_HOOKS,
    CAPABILITY_CLI,
    CAPABILITY_NETWORK,
    CAPABILITY_FILES,
    CAPABILITY_MCP,
})

#: Legacy default for plugins that do not declare a capability list: the
#: in-process integration surface only.  External resources stay denied until
#: an operator explicitly grants them.
LEGACY_DEFAULT_CAPABILITIES = frozenset({
    CAPABILITY_TOOLS,
    CAPABILITY_HOOKS,
    CAPABILITY_CLI,
})


def resolve_capabilities(meta: Any, default: Optional[FrozenSet[str]] = None) -> FrozenSet[str]:
    """Return the granted capability allowlist for a plugin's metadata.

    Fails closed: an explicit ``capabilities`` list (or a ``permissions`` map
    carrying ``capabilities``) wins and is intersected with ``KNOWN_CAPABILITIES``;
    a declared-but-all-unknown list grants nothing.  When the manifest declares
    no capability list, the legacy default (in-process integration only) is
    granted so existing bundled plugins keep working.
    """
    if not isinstance(meta, dict):
        return frozenset(default if default is not None else LEGACY_DEFAULT_CAPABILITIES)
    declared = meta.get("capabilities")
    if declared is None:
        permissions = meta.get("permissions")
        if isinstance(permissions, dict):
            declared = permissions.get("capabilities")
    if isinstance(declared, (list, tuple, set)):
        granted = frozenset(str(cap).strip() for cap in declared if str(cap).strip())
        return granted & KNOWN_CAPABILITIES
    if isinstance(declared, str) and declared.strip():
        return frozenset({declared.strip()}) & KNOWN_CAPABILITIES
    return frozenset(default if default is not None else LEGACY_DEFAULT_CAPABILITIES)


def check_capability(granted: FrozenSet[str], required: str) -> bool:
    """True when ``required`` is present in the granted capability set."""
    return required in granted


def require_unverified_install_opt_in() -> None:
    """Fail closed unless an operator explicitly accepts unverified source risk."""
    if os.environ.get("NEXUS_ALLOW_UNVERIFIED_PLUGIN_INSTALL", "").strip() != "1":
        raise PluginInstallDisabled(
            "Remote plugin installation is disabled: downloaded plugins are executable code "
            "and NEXUS cannot verify a signature or pinned checksum. Install reviewed source "
            "manually, or set NEXUS_ALLOW_UNVERIFIED_PLUGIN_INSTALL=1 to accept this risk."
        )


def is_user_plugin_load_allowed() -> bool:
    """Return True only when operators explicitly allow user plugin execution."""
    return os.environ.get("NEXUS_ALLOW_USER_PLUGIN_LOAD", "").strip() == "1"


def is_bundled_plugin_dir(plugin_dir: str, bundled_dir: str) -> bool:
    """Check whether a plugin path lives under the reviewed bundled plugin tree."""
    try:
        plugin_path = Path(plugin_dir).resolve()
        bundled_path = Path(bundled_dir).resolve()
        return bundled_path == plugin_path or bundled_path in plugin_path.parents
    except OSError:
        return False
