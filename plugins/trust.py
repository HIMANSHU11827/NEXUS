"""Trust policy for installing executable third-party plugin source."""

from __future__ import annotations

import os
from pathlib import Path


class PluginInstallDisabled(PermissionError):
    pass


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
