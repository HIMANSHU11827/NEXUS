"""Persistent, validated safety configuration store for NEXUS AI.

This module owns every setting shown on the Settings -> Safety page and is the
single enforcement point the HTTP server and the permission engine consult.

It keeps three independent systems separate and never lets one change the other:

  1. Workspace / project folder  ->  ``runtime.workspace_root``
  2. Permission Mode             ->  ``safety.permission_mode``
  3. Sandbox Mode                ->  ``safety.sandbox_mode``

The module is intentionally standalone (stdlib + yaml only) so both
``server`` and ``permissions`` can import it without a circular import.

Persisted safety settings are validated on write and written atomically. Secrets
are never stored; only counts and sanitised metadata are exposed.
"""

from __future__ import annotations

import copy
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is a hard dependency in practice
    yaml = None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "configure" / "settings.yml"

_LOCK = threading.RLock()
_STATE: Optional[Dict[str, Any]] = None
_STATE_SOURCE_LEGACY = False

# ─────────────────────────────────────────────────────────────────────────────
# Mode catalogues (these are the three *separate* systems; never mixed)
# ─────────────────────────────────────────────────────────────────────────────

PERMISSION_MODES: Dict[str, Dict[str, str]] = {
    "automatic": {
        "label": "Automatic",
        "description": (
            "Nexus automatically allows low-risk actions, asks before risky "
            "actions, and denies critical blocked actions. Mandatory safety "
            "rules always remain active."
        ),
    },
    "ask": {
        "label": "Ask when needed",
        "description": (
            "Safe reads may run automatically. File writes, commands, network "
            "actions, and destructive operations require approval according to "
            "their risk."
        ),
    },
    "read_only": {
        "label": "Read only",
        "description": (
            "Allow reading project files, searching, and indexing. Deny file "
            "creation, modification, deletion, rename, and move, plus "
            "destructive commands."
        ),
    },
    "restricted": {
        "label": "Restricted",
        "description": (
            "Allow only explicitly approved tools and actions. Require approval "
            "for most write, command, network, browser, and MCP actions."
        ),
    },
    "trusted": {
        "label": "Trusted workspace",
        "description": (
            "Allow more actions inside the selected workspace. Continue blocking "
            "critical or system-level actions. Never treat paths outside the "
            "workspace as trusted automatically."
        ),
    },
    "custom": {
        "label": "Custom",
        "description": "Use detailed per-action policies configured by the user.",
    },
    "deny_all": {
        "label": "Deny all tools",
        "description": (
            "Nexus may respond with text only. No command, file, browser, "
            "network, MCP, or external tool execution."
        ),
    },
}

SANDBOX_MODES: Dict[str, Dict[str, Any]] = {
    "no_tools": {
        "label": "No tools",
        "description": "Do not run commands or tools.",
        "filesystem_scope": "None",
        "workspace_access": "None",
        "additional_dir_access": "None",
        "write_access": "None",
        "network_access": "None",
        "env_access": "None",
        "child_process_access": "None",
        "temp_dir_access": "None",
        "system_dir_access": "None",
        "resource_limits": "Not applicable",
        "isolation_level": "Total",
    },
    "read_only": {
        "label": "Read-only sandbox",
        "description": (
            "Commands may inspect approved files. Commands cannot modify "
            "project files. Network access follows the separate network policy."
        ),
        "filesystem_scope": "Workspace + approved directories",
        "workspace_access": "Read only",
        "additional_dir_access": "Read only",
        "write_access": "None",
        "network_access": "Per network policy",
        "env_access": "Minimal (PATH, NEXUS_ROOT)",
        "child_process_access": "Allowed for commands",
        "temp_dir_access": "System temp only",
        "system_dir_access": "None",
        "resource_limits": "CPU + wall-clock limits",
        "isolation_level": "Medium",
    },
    "workspace": {
        "label": "Workspace sandbox",
        "description": (
            "Commands run inside the selected workspace. File access is limited "
            "to the workspace and approved additional directories. Root "
            "protection remains enforced. The selected workspace becomes the "
            "default working directory."
        ),
        "filesystem_scope": "Workspace + approved directories",
        "workspace_access": "Read and write",
        "additional_dir_access": "Approved directories only",
        "write_access": "Workspace only",
        "network_access": "Per network policy",
        "env_access": "Minimal (PATH, NEXUS_ROOT)",
        "child_process_access": "Allowed for commands",
        "temp_dir_access": "System temp only",
        "system_dir_access": "None",
        "resource_limits": "CPU + wall-clock limits",
        "isolation_level": "Medium",
    },
    "restricted": {
        "label": "Restricted sandbox",
        "description": (
            "Commands run with reduced filesystem, process, environment, and "
            "network access. Access is limited according to sandbox "
            "configuration."
        ),
        "filesystem_scope": "Whitelisted roots only",
        "workspace_access": "As configured",
        "additional_dir_access": "As configured",
        "write_access": "As configured",
        "network_access": "As configured",
        "env_access": "Strict allowlist",
        "child_process_access": "Restricted",
        "temp_dir_access": "Scoped temp",
        "system_dir_access": "None",
        "resource_limits": "Strict CPU, memory, wall-clock",
        "isolation_level": "High",
    },
    "isolated_temp": {
        "label": "Isolated temporary sandbox",
        "description": (
            "Commands run in an isolated temporary environment. Project files "
            "are mounted only when explicitly allowed. Temporary changes do not "
            "automatically modify the real project."
        ),
        "filesystem_scope": "Isolated temporary environment",
        "workspace_access": "Mounted when explicitly allowed",
        "additional_dir_access": "Mounted when explicitly allowed",
        "write_access": "Isolated only",
        "network_access": "Per network policy",
        "env_access": "Minimal",
        "child_process_access": "Allowed inside isolation",
        "temp_dir_access": "Dedicated isolated temp",
        "system_dir_access": "None",
        "resource_limits": "CPU, memory, wall-clock",
        "isolation_level": "Very high",
    },
    "custom": {
        "label": "Custom sandbox",
        "description": (
            "User configures filesystem, process, network, environment, and "
            "resource limits."
        ),
        "filesystem_scope": "As configured",
        "workspace_access": "As configured",
        "additional_dir_access": "As configured",
        "write_access": "As configured",
        "network_access": "As configured",
        "env_access": "As configured",
        "child_process_access": "As configured",
        "temp_dir_access": "As configured",
        "system_dir_access": "As configured",
        "resource_limits": "As configured",
        "isolation_level": "As configured",
    },
    "no_sandbox": {
        "label": "No sandbox",
        "description": (
            "Commands run directly on the host system. Requires explicit "
            "confirmation. Mandatory safety and permission checks still apply."
        ),
        "filesystem_scope": "Full host filesystem",
        "workspace_access": "Full",
        "additional_dir_access": "Full",
        "write_access": "Full host",
        "network_access": "Per network policy",
        "env_access": "Full",
        "child_process_access": "Full",
        "temp_dir_access": "Full",
        "system_dir_access": "Full",
        "resource_limits": "None",
        "isolation_level": "None",
    },
}

# New mode -> legacy engine value (the engine used by orchestrators).
PERMISSION_TO_LEGACY = {
    "automatic": "auto",
    "ask": "ask",
    "read_only": "ask",
    "restricted": "ask",
    "trusted": "auto",
    "custom": "ask",
    "deny_all": "ask",
}
LEGACY_TO_PERMISSION = {
    "": "automatic",
    "auto": "automatic",
    "auto_pilot": "automatic",
    "autopilot": "automatic",
    "acceptedits": "automatic",
    "accept": "automatic",
    "ask": "ask",
    "askall": "ask",
    "ask_all": "ask",
    "approve": "ask",
    "approval": "ask",
    "default": "ask",
    "once": "ask",
    "allowlist": "restricted",
    "pre_authorized": "restricted",
    "checklist": "restricted",
    "whitelist": "restricted",
    "plan": "restricted",
    "all": "automatic",  # legacy "allow all" has no exact new-mode equivalent
    "bypass": "automatic",
    "dontask": "automatic",
    "dont_ask": "automatic",
    "noask": "automatic",
}

SANDBOX_TO_LEGACY = {
    "no_tools": "no_sandbox",
    "read_only": "normal",
    "workspace": "normal",
    "restricted": "normal",
    "isolated_temp": "docker",
    "custom": "normal",
    "no_sandbox": "no_sandbox",
}
LEGACY_TO_SANDBOX = {
    "": "no_sandbox",
    "none": "no_sandbox",
    "off": "no_sandbox",
    "no": "no_sandbox",
    "no_sandbox": "no_sandbox",
    "nosandbox": "no_sandbox",
    "simple": "workspace",
    "safe": "workspace",
    "on": "workspace",
    "normal": "workspace",
    "advanced": "isolated_temp",
    "docker": "isolated_temp",
}

# ─────────────────────────────────────────────────────────────────────────────
# Policy catalogues
# ─────────────────────────────────────────────────────────────────────────────

COMMAND_CATEGORIES: List[Dict[str, Any]] = [
    {"id": "safe_commands", "risk": "Safe", "label": "Safe commands", "default": "allow"},
    {"id": "destructive_commands", "risk": "Critical", "label": "Destructive commands", "default": "deny"},
    {"id": "privilege_escalation", "risk": "Critical", "label": "Privilege escalation", "default": "deny"},
    {"id": "system_shutdown", "risk": "Critical", "label": "System shutdown", "default": "deny"},
    {"id": "system_restart", "risk": "Critical", "label": "System restart", "default": "deny"},
    {"id": "disk_formatting", "risk": "Critical", "label": "Disk formatting", "default": "deny"},
    {"id": "partition_changes", "risk": "Critical", "label": "Partition changes", "default": "deny"},
    {"id": "registry_modification", "risk": "High", "label": "Registry modification", "default": "ask"},
    {"id": "boot_configuration", "risk": "Critical", "label": "Boot configuration", "default": "deny"},
    {"id": "user_account_changes", "risk": "Critical", "label": "User-account changes", "default": "deny"},
    {"id": "firewall_changes", "risk": "High", "label": "Firewall changes", "default": "ask"},
    {"id": "security_tool_disabling", "risk": "Critical", "label": "Security-tool disabling", "default": "deny"},
    {"id": "credential_access", "risk": "Critical", "label": "Credential access", "default": "deny"},
    {"id": "process_injection", "risk": "Critical", "label": "Process injection", "default": "deny"},
    {"id": "persistence_creation", "risk": "High", "label": "Persistence creation", "default": "ask"},
    {"id": "scheduled_task_creation", "risk": "High", "label": "Scheduled-task creation", "default": "ask"},
    {"id": "service_creation", "risk": "High", "label": "Service creation", "default": "ask"},
    {"id": "hidden_background_execution", "risk": "High", "label": "Hidden background execution", "default": "ask"},
    {"id": "shell_profile_modification", "risk": "High", "label": "Shell-profile modification", "default": "ask"},
    {"id": "outside_workspace", "risk": "Medium", "label": "Commands outside the selected workspace", "default": "ask"},
    {"id": "path_traversal", "risk": "Critical", "label": "Unsafe path traversal", "default": "deny"},
    {"id": "unresolved_variables", "risk": "Medium", "label": "Unresolved variables", "default": "ask"},
    {"id": "command_chaining", "risk": "Medium", "label": "Command chaining", "default": "ask"},
    {"id": "command_pipelines", "risk": "Medium", "label": "Command pipelines", "default": "ask"},
    {"id": "output_redirection", "risk": "Medium", "label": "Output redirection", "default": "ask"},
    {"id": "detached_processes", "risk": "High", "label": "Detached processes", "default": "ask"},
]

FILE_POLICY_CATEGORIES: List[Dict[str, Any]] = [
    {"id": "read_file", "label": "Read file", "default": "allow"},
    {"id": "create_file", "label": "Create file", "default": "ask"},
    {"id": "modify_file", "label": "Modify file", "default": "ask"},
    {"id": "delete_file", "label": "Delete file", "default": "ask"},
    {"id": "rename_file", "label": "Rename file", "default": "ask"},
    {"id": "move_file", "label": "Move file", "default": "ask"},
    {"id": "copy_file", "label": "Copy file", "default": "ask"},
    {"id": "create_directory", "label": "Create directory", "default": "ask"},
    {"id": "delete_directory", "label": "Delete directory", "default": "ask"},
    {"id": "change_permissions", "label": "Change permissions", "default": "ask"},
    {"id": "bulk_file_changes", "label": "Bulk file changes", "default": "ask"},
    {"id": "modify_binary_files", "label": "Modify binary files", "default": "ask"},
    {"id": "modify_configuration_files", "label": "Modify configuration files", "default": "ask"},
    {"id": "modify_lock_files", "label": "Modify lock files", "default": "ask"},
    {"id": "modify_generated_files", "label": "Modify generated files", "default": "ask"},
    {"id": "modify_git_metadata", "label": "Modify Git metadata", "default": "deny"},
    {"id": "modify_nexus_internal_files", "label": "Modify Nexus internal files", "default": "ask"},
]

FILESYSTEM_OPTIONS: List[Dict[str, Any]] = [
    {"id": "enforce_workspace_root", "label": "Enforce workspace root", "default": True, "kind": "bool"},
    {"id": "allow_additional_dirs", "label": "Allow approved additional directories", "default": True, "kind": "bool"},
    {"id": "read_hidden_files", "label": "Read hidden files", "default": False, "kind": "bool"},
    {"id": "write_hidden_files", "label": "Write hidden files", "default": False, "kind": "bool"},
    {"id": "follow_symlinks", "label": "Follow symbolic links", "default": False, "kind": "bool"},
    {"id": "follow_junctions", "label": "Follow Windows junctions", "default": False, "kind": "bool"},
    {"id": "access_network_drives", "label": "Access network drives", "default": False, "kind": "bool"},
    {"id": "access_removable_drives", "label": "Access removable drives", "default": False, "kind": "bool"},
    {"id": "access_temp_dirs", "label": "Access temporary directories", "default": False, "kind": "bool"},
    {"id": "access_system_dirs", "label": "Access system directories", "default": False, "kind": "bool"},
    {"id": "access_user_profile", "label": "Access user-profile folders", "default": False, "kind": "bool"},
    {"id": "access_outside_roots", "label": "Access outside approved roots", "default": False, "kind": "bool"},
]

SECRET_PROTECTION_OPTIONS: List[Dict[str, Any]] = [
    {"id": "detect_secrets", "label": "Detect secrets", "default": True, "kind": "bool"},
    {"id": "redact_logs", "label": "Redact secrets from logs", "default": True, "kind": "bool"},
    {"id": "redact_model_context", "label": "Redact secrets from model context", "default": True, "kind": "bool"},
    {"id": "block_private_keys", "label": "Block private keys", "default": True, "kind": "bool"},
    {"id": "block_env_files", "label": "Block environment files", "default": True, "kind": "bool"},
    {"id": "block_credential_files", "label": "Block credential files", "default": True, "kind": "bool"},
    {"id": "block_auth_headers", "label": "Block authentication headers", "default": True, "kind": "bool"},
    {"id": "block_cookies", "label": "Block cookies", "default": True, "kind": "bool"},
    {"id": "block_tokens", "label": "Block tokens", "default": True, "kind": "bool"},
    {"id": "block_passwords", "label": "Block passwords", "default": True, "kind": "bool"},
    {"id": "block_cloud_credentials", "label": "Block cloud credentials", "default": True, "kind": "bool"},
    {"id": "block_ssh_credentials", "label": "Block SSH credentials", "default": True, "kind": "bool"},
    {"id": "block_browser_session_data", "label": "Block browser session data", "default": True, "kind": "bool"},
    {"id": "block_database_credentials", "label": "Block database credentials", "default": True, "kind": "bool"},
    {"id": "warn_before_reading_sensitive", "label": "Warn before reading sensitive files", "default": True, "kind": "bool"},
    {"id": "warn_before_modifying_sensitive", "label": "Warn before modifying sensitive files", "default": True, "kind": "bool"},
    {"id": "filter_sensitive_terminal_output", "label": "Filter sensitive terminal output", "default": True, "kind": "bool"},
]

NETWORK_POLICIES = {
    "deny_all": {"label": "Deny all", "default": False},
    "ask": {"label": "Ask for each destination", "default": True},
    "approved_domains": {"label": "Approved domains only", "default": False},
    "browser_only": {"label": "Browser only", "default": False},
    "registries_only": {"label": "Package registries only", "default": False},
    "allow_all": {"label": "Allow all", "default": False},
}

BROWSER_OPTIONS: List[Dict[str, Any]] = [
    {"id": "page_navigation", "label": "Page navigation", "default": "ask"},
    {"id": "form_filling", "label": "Form filling", "default": "ask"},
    {"id": "file_upload", "label": "File upload", "default": "ask"},
    {"id": "file_download", "label": "File download", "default": "ask"},
    {"id": "clipboard_access", "label": "Clipboard access", "default": "ask"},
    {"id": "camera", "label": "Camera", "default": "deny"},
    {"id": "microphone", "label": "Microphone", "default": "deny"},
    {"id": "location", "label": "Location", "default": "deny"},
    {"id": "popups", "label": "Popups", "default": "deny"},
    {"id": "new_tabs", "label": "New tabs", "default": "ask"},
    {"id": "authenticated_sessions", "label": "Authenticated sessions", "default": "ask"},
    {"id": "local_development_urls", "label": "Local development URLs", "default": "allow"},
]

MCP_OPTIONS: List[Dict[str, Any]] = [
    {"id": "allow_servers", "label": "Allow MCP servers", "default": True, "kind": "bool"},
    {"id": "allow_local_servers", "label": "Allow local MCP servers", "default": True, "kind": "bool"},
    {"id": "allow_external_servers", "label": "Allow external MCP servers", "default": False, "kind": "bool"},
    {"id": "allow_read_actions", "label": "Allow MCP read actions", "default": True, "kind": "bool"},
    {"id": "allow_write_actions", "label": "Allow MCP write actions", "default": False, "kind": "bool"},
    {"id": "require_approval_unknown", "label": "Require approval for unknown tools", "default": True, "kind": "bool"},
]

PACKAGE_MANAGERS = ["npm", "pnpm", "yarn", "pip", "uv", "poetry", "cargo", "go", "apt", "brew", "winget"]

PACKAGE_OPTIONS: List[Dict[str, Any]] = [
    {"id": "allow_install", "label": "Allow package installation", "default": "ask"},
    {"id": "require_approval", "label": "Require approval", "default": True, "kind": "bool"},
    {"id": "allow_dev_dependencies", "label": "Allow development dependencies", "default": True, "kind": "bool"},
    {"id": "allow_global_install", "label": "Allow global installation", "default": False, "kind": "bool"},
    {"id": "allow_install_scripts", "label": "Allow install scripts", "default": False, "kind": "bool"},
    {"id": "allow_post_install_scripts", "label": "Allow post-install scripts", "default": False, "kind": "bool"},
    {"id": "allow_native_builds", "label": "Allow native builds", "default": False, "kind": "bool"},
    {"id": "allow_unsigned_packages", "label": "Allow unsigned packages", "default": False, "kind": "bool"},
    {"id": "allow_lock_file_updates", "label": "Allow lock-file updates", "default": True, "kind": "bool"},
    {"id": "allow_upgrades", "label": "Allow upgrades", "default": "ask"},
    {"id": "allow_registry_changes", "label": "Allow registry changes", "default": False, "kind": "bool"},
]

PROCESS_OPTIONS: List[Dict[str, Any]] = [
    {"id": "child_processes", "label": "Child processes", "default": "allow"},
    {"id": "detached_processes", "label": "Detached processes", "default": "ask"},
    {"id": "background_tasks", "label": "Background tasks", "default": "ask"},
    {"id": "long_running_tasks", "label": "Long-running tasks", "default": "ask"},
    {"id": "scheduled_tasks", "label": "Scheduled tasks", "default": "ask"},
    {"id": "services", "label": "Services", "default": "ask"},
    {"id": "process_termination", "label": "Process termination", "default": "ask"},
    {"id": "opening_applications", "label": "Opening applications", "default": "ask"},
    {"id": "shell_chaining", "label": "Shell chaining", "default": "ask"},
    {"id": "command_pipelines", "label": "Command pipelines", "default": "ask"},
    {"id": "redirected_output", "label": "Redirected output", "default": "ask"},
]

DESTRUCTIVE_ACTIONS: List[Dict[str, Any]] = [
    {"id": "file_deletion", "label": "File deletion", "default": True, "kind": "bool"},
    {"id": "directory_deletion", "label": "Directory deletion", "default": True, "kind": "bool"},
    {"id": "bulk_overwrite", "label": "Bulk overwrite", "default": True, "kind": "bool"},
    {"id": "bulk_rename", "label": "Bulk rename", "default": True, "kind": "bool"},
    {"id": "git_clean", "label": "Git clean", "default": True, "kind": "bool"},
    {"id": "git_reset", "label": "Git reset", "default": True, "kind": "bool"},
    {"id": "database_deletion", "label": "Database deletion", "default": True, "kind": "bool"},
    {"id": "database_migration", "label": "Database migration", "default": True, "kind": "bool"},
    {"id": "cache_clearing", "label": "Cache clearing", "default": True, "kind": "bool"},
    {"id": "index_clearing", "label": "Index clearing", "default": True, "kind": "bool"},
    {"id": "package_removal", "label": "Package removal", "default": True, "kind": "bool"},
    {"id": "process_termination", "label": "Process termination", "default": True, "kind": "bool"},
    {"id": "workspace_disconnect", "label": "Workspace disconnect", "default": True, "kind": "bool"},
    {"id": "configuration_reset", "label": "Configuration reset", "default": True, "kind": "bool"},
    {"id": "memory_reset", "label": "Memory reset", "default": True, "kind": "bool"},
    {"id": "credential_removal", "label": "Credential removal", "default": True, "kind": "bool"},
]

CHECKPOINT_OPTIONS: List[Dict[str, Any]] = [
    {"id": "create_before_file_changes", "label": "Create before file changes", "default": True, "kind": "bool"},
    {"id": "create_before_destructive_commands", "label": "Create before destructive commands", "default": True, "kind": "bool"},
    {"id": "create_before_bulk_operations", "label": "Create before bulk operations", "default": True, "kind": "bool"},
    {"id": "require_for_critical_actions", "label": "Require for critical actions", "default": True, "kind": "bool"},
    {"id": "verify_before_execution", "label": "Verify before execution", "default": True, "kind": "bool"},
    {"id": "retention_period_hours", "label": "Retention period (hours)", "default": 168, "kind": "int"},
    {"id": "max_storage_mb", "label": "Maximum storage (MB)", "default": 1024, "kind": "int"},
    {"id": "automatic_cleanup", "label": "Automatic cleanup", "default": True, "kind": "bool"},
]

PRESETS: Dict[str, Dict[str, Any]] = {
    "maximum_protection": {
        "label": "Maximum protection",
        "permission_mode": "restricted",
        "sandbox_mode": "isolated_temp",
        "command_policies": {"destructive_commands": "deny", "privilege_escalation": "deny", "path_traversal": "deny"},
        "file_policies": {"modify_git_metadata": "deny"},
        "network": {"policy": "deny_all"},
        "secret_protection": {"detect_secrets": True, "redact_logs": True},
        "checkpoints": {"create_before_file_changes": True, "require_for_critical_actions": True},
        "description": "Blocks nearly all actions; strictest sandboxing and network isolation.",
    },
    "recommended": {
        "label": "Recommended",
        "permission_mode": "automatic",
        "sandbox_mode": "workspace",
        "command_policies": {"destructive_commands": "deny", "credential_access": "deny"},
        "file_policies": {"modify_git_metadata": "deny"},
        "network": {"policy": "approved_domains"},
        "secret_protection": {"detect_secrets": True, "redact_logs": True},
        "checkpoints": {"create_before_file_changes": True},
        "description": "Balanced protection with autonomous low-risk actions.",
    },
    "development": {
        "label": "Development",
        "permission_mode": "automatic",
        "sandbox_mode": "workspace",
        "command_policies": {"safe_commands": "allow"},
        "network": {"policy": "allow_all"},
        "description": "Faster iteration for trusted development work.",
    },
    "read_only": {
        "label": "Read only",
        "permission_mode": "read_only",
        "sandbox_mode": "read_only",
        "network": {"policy": "deny_all"},
        "description": "Reads and searches only; no writes, no network.",
    },
    "offline": {
        "label": "Offline",
        "permission_mode": "automatic",
        "sandbox_mode": "workspace",
        "network": {"policy": "deny_all"},
        "description": "No network access; local work continues normally.",
    },
    "custom": {
        "label": "Custom",
        "description": "Current per-action policies configured by the user.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EnforcementResult:
    allowed: bool
    decision: str  # allow | ask | deny | block
    reason: str
    policy: str = ""
    risk: str = "unknown"
    requires_approval: bool = False
    category: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────

def project_root() -> Path:
    return _PROJECT_ROOT


def _is_within(parent: str, child: str) -> bool:
    try:
        p = os.path.normcase(os.path.abspath(parent))
        c = os.path.normcase(os.path.abspath(child))
        return os.path.commonpath([p, c]) == p
    except Exception:
        return False


def _canonical(raw: str) -> str:
    return os.path.abspath(os.path.normpath(str(raw or "").strip().strip('"').strip("'")))


# ─────────────────────────────────────────────────────────────────────────────
# Config read / write (atomic)
# ─────────────────────────────────────────────────────────────────────────────

def _load_yaml() -> Dict[str, Any]:
    if yaml is None:
        return {}
    if not _CONFIG_PATH.is_file():
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_yaml(data: Dict[str, Any]) -> bool:
    if yaml is None:
        return False
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = f"{_CONFIG_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=100)
        os.replace(tmp, _CONFIG_PATH)
        return True
    except Exception:
        return False


def workspace_root() -> str:
    """The selected workspace / project folder (separate from safety config)."""
    config = _load_yaml()
    runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
    configured = str(runtime.get("workspace_root") or "").strip()
    return configured or str(_PROJECT_ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────────────

def _bool_defaults(options: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {item["id"]: bool(item.get("default")) for item in options}


def _choice_defaults(options: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {item["id"]: item.get("default") for item in options}


def _default_protected_paths() -> List[Dict[str, Any]]:
    return [
        {"pattern": ".git/**", "reason": "Git internals", "source": "default", "mandatory": True, "read_policy": "allow", "write_policy": "deny", "delete_policy": "deny"},
        {"pattern": ".env", "reason": "Environment secrets", "source": "default", "mandatory": True, "read_policy": "warn", "write_policy": "deny", "delete_policy": "deny"},
        {"pattern": ".env.*", "reason": "Environment secrets", "source": "default", "mandatory": True, "read_policy": "warn", "write_policy": "deny", "delete_policy": "deny"},
        {"pattern": "**/*.pem", "reason": "Private keys", "source": "default", "mandatory": True, "read_policy": "warn", "write_policy": "deny", "delete_policy": "deny"},
        {"pattern": "**/*.key", "reason": "Private keys", "source": "default", "mandatory": True, "read_policy": "warn", "write_policy": "deny", "delete_policy": "deny"},
        {"pattern": "**/.ssh/**", "reason": "SSH credentials", "source": "default", "mandatory": True, "read_policy": "deny", "write_policy": "deny", "delete_policy": "deny"},
        {"pattern": "**/*credential*", "reason": "Credentials", "source": "default", "mandatory": True, "read_policy": "warn", "write_policy": "deny", "delete_policy": "deny"},
        {"pattern": "**/*secret*", "reason": "Secrets", "source": "default", "mandatory": True, "read_policy": "warn", "write_policy": "deny", "delete_policy": "deny"},
    ]


def _default_state() -> Dict[str, Any]:
    return {
        "permission_mode": "automatic",
        "sandbox_mode": "workspace",
        "command_policies": {item["id"]: item["default"] for item in COMMAND_CATEGORIES},
        "file_policies": {item["id"]: item["default"] for item in FILE_POLICY_CATEGORIES},
        "filesystem": _bool_defaults(FILESYSTEM_OPTIONS),
        "secret_protection": _bool_defaults(SECRET_PROTECTION_OPTIONS),
        "network": {
            "policy": "ask",
            "allowlist": [],
            "blocklist": [],
            "block_cloud_metadata": True,
            "block_local_metadata": True,
            "block_private_scanning": True,
            "block_unsafe_redirects": True,
            "block_credential_urls": True,
            "block_unsupported_protocols": True,
        },
        "browser": _choice_defaults(BROWSER_OPTIONS),
        "mcp": _bool_defaults(MCP_OPTIONS),
        "package": {
            "managers": PACKAGE_MANAGERS,
            "policies": _package_defaults(),
        },
        "process": _choice_defaults(PROCESS_OPTIONS),
        "destructive": {"require_approval": True, "require_typed_confirmation": True, "actions": _bool_defaults(DESTRUCTIVE_ACTIONS)},
        "checkpoints": _checkpoint_defaults(),
        "protected_paths": _default_protected_paths(),
        "temp_permissions": [],
        "approval_history": [],
        "safety_events": [],
        "last_saved": None,
    }


def _package_defaults() -> Dict[str, Any]:
    return {item["id"]: item.get("default") for item in PACKAGE_OPTIONS}


def _checkpoint_defaults() -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for item in CHECKPOINT_OPTIONS:
        if item.get("kind") == "int":
            values[item["id"]] = int(item.get("default", 0))
        else:
            values[item["id"]] = bool(item.get("default"))
    return values


# ─────────────────────────────────────────────────────────────────────────────
# Merge / validation
# ─────────────────────────────────────────────────────────────────────────────

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _coerce_policy(value: Any, allowed: List[str]) -> str:
    text = str(value or "").strip()
    return text if text in allowed else allowed[0]


def _validate_state(state: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    defaults = _default_state()

    pm = str(state.get("permission_mode") or "")
    if pm not in PERMISSION_MODES:
        errors.append(f"Invalid permission mode: {pm!r}")
    sm = str(state.get("sandbox_mode") or "")
    if sm not in SANDBOX_MODES:
        errors.append(f"Invalid sandbox mode: {sm!r}")

    for category in COMMAND_CATEGORIES:
        current = state.get("command_policies", {}).get(category["id"])
        if current not in ("allow", "ask", "deny"):
            errors.append(f"Invalid command policy for {category['id']}")
    for category in FILE_POLICY_CATEGORIES:
        current = state.get("file_policies", {}).get(category["id"])
        if current not in ("allow", "ask", "deny", "read_only", "session"):
            errors.append(f"Invalid file policy for {category['id']}")

    net = state.get("network") if isinstance(state.get("network"), dict) else {}
    if net.get("policy") not in NETWORK_POLICIES:
        errors.append(f"Invalid network policy: {net.get('policy')!r}")
    for key in ("allowlist", "blocklist"):
        if not isinstance(net.get(key), list):
            errors.append(f"network.{key} must be a list")

    for protected in state.get("protected_paths") or []:
        if not isinstance(protected, dict) or not str(protected.get("pattern") or "").strip():
            errors.append("Protected path missing a pattern")
        if str(protected.get("read_policy") or "") not in ("allow", "warn", "deny"):
            errors.append(f"Invalid read policy for {protected.get('pattern')}")
        if str(protected.get("write_policy") or "") not in ("allow", "warn", "deny"):
            errors.append(f"Invalid write policy for {protected.get('pattern')}")
        if str(protected.get("delete_policy") or "") not in ("allow", "warn", "deny"):
            errors.append(f"Invalid delete policy for {protected.get('pattern')}")

    for category in FILE_POLICY_CATEGORIES:
        if category["id"] not in defaults["file_policies"]:
            pass

    # Mandatory safety rules are never overridable: re-add any that were dropped.
    mandatory = [rule for rule in defaults["protected_paths"] if rule.get("mandatory")]
    current_paths = list(state.get("protected_paths") or [])
    existing_patterns = {str(rule.get("pattern")) for rule in current_paths if isinstance(rule, dict)}
    for rule in mandatory:
        if str(rule.get("pattern")) not in existing_patterns:
            current_paths.append(copy.deepcopy(rule))
    state["protected_paths"] = current_paths

    return {
        "valid": not errors,
        "errors": errors,
        "state": state if not errors else defaults,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Store API
# ─────────────────────────────────────────────────────────────────────────────

def _load_state_from_disk() -> Dict[str, Any]:
    global _STATE_SOURCE_LEGACY
    defaults = _default_state()
    config = _load_yaml()
    safety = config.get("safety") if isinstance(config.get("safety"), dict) else None
    if safety is None:
        # Migrate from the legacy runtime keys once so the two pages agree.
        runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
        legacy_mode = str(runtime.get("permission_mode") or "auto").strip().lower()
        legacy_tier = str(runtime.get("sandbox_tier") or "normal").strip().lower()
        defaults["permission_mode"] = LEGACY_TO_PERMISSION.get(legacy_mode, "automatic")
        defaults["sandbox_mode"] = LEGACY_TO_SANDBOX.get(legacy_tier, "workspace")
        _STATE_SOURCE_LEGACY = True
        return defaults
    merged = _deep_merge(defaults, safety)
    # Normalise missing fields back to defaults while preserving saved values.
    for category in COMMAND_CATEGORIES:
        merged["command_policies"].setdefault(category["id"], category["default"])
    for category in FILE_POLICY_CATEGORIES:
        merged["file_policies"].setdefault(category["id"], category["default"])
    return merged


def get_state(refresh: bool = False) -> Dict[str, Any]:
    global _STATE
    with _LOCK:
        if _STATE is None or refresh:
            _STATE = _load_state_from_disk()
        return copy.deepcopy(_STATE)


def _persist(state: Dict[str, Any]) -> Dict[str, Any]:
    validation = _validate_state(state)
    if not validation["valid"]:
        return {"ok": False, "errors": validation["errors"], "state": validation["state"]}
    safe_state = validation["state"]
    safe_state.pop("secret_scan", None)
    config = _load_yaml()
    if not isinstance(config.get("safety"), dict):
        config["safety"] = {}
    config["safety"] = safe_state
    # Keep last_saved updated on disk.
    config["safety"]["last_saved"] = time.time()
    if not _save_yaml(config):
        return {"ok": False, "errors": ["Could not write configuration atomically"], "state": safe_state}
    with _LOCK:
        global _STATE
        _STATE = copy.deepcopy(config["safety"])
    return {"ok": True, "errors": [], "state": copy.deepcopy(config["safety"])}


def save(state: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the full safety state (validated, atomic). Never touches workspace root."""
    workspace_before = workspace_root()
    previous = get_state()
    cleaned = _clean_supplied_state(state)
    result = _persist(cleaned)
    result["workspace_unchanged"] = workspace_root() == workspace_before
    result["permission_mode"] = cleaned.get("permission_mode")
    result["sandbox_mode"] = cleaned.get("sandbox_mode")
    result["permission_changed"] = cleaned.get("permission_mode") != previous.get("permission_mode")
    result["sandbox_changed"] = cleaned.get("sandbox_mode") != previous.get("sandbox_mode")
    result["workspace"] = workspace_root()
    if result.get("permission_changed"):
        _record_event("permission_changed", f"Permission mode changed to {cleaned.get('permission_mode')}", risk="low")
    if result.get("sandbox_changed"):
        _record_event("sandbox_changed", f"Sandbox mode changed to {cleaned.get('sandbox_mode')}", risk="low")
    return result


def _clean_supplied_state(state: Dict[str, Any]) -> Dict[str, Any]:
    # Merge against the CURRENT persisted state rather than factory defaults so
    # that partial or stale client payloads never wipe live operational lists
    # (temporary permissions, approvals, events) or user-added protected paths.
    current = get_state()
    if not isinstance(state, dict):
        return current
    merged = _deep_merge(current, state)
    # Never allow the client to smuggle a workspace root change through safety.
    merged.pop("workspace_root", None)
    # Mandatory safety rules are never overridable: always restore them even if
    # the client omits or attempts to remove them.
    mandatory = [copy.deepcopy(rule) for rule in _default_protected_paths() if rule.get("mandatory")]
    existing = {str(rule.get("pattern")) for rule in (merged.get("protected_paths") or []) if isinstance(rule, dict)}
    for rule in mandatory:
        if str(rule.get("pattern")) not in existing:
            merged.setdefault("protected_paths", []).append(rule)
    return merged


def reset() -> Dict[str, Any]:
    defaults = _default_state()
    config = _load_yaml()
    config["safety"] = defaults
    config["safety"]["last_saved"] = time.time()
    if not _save_yaml(config):
        return {"ok": False, "errors": ["Could not reset safety settings"]}
    with _LOCK:
        global _STATE
        _STATE = copy.deepcopy(defaults)
    return {"ok": True, "errors": [], "state": copy.deepcopy(defaults)}


# ─────────────────────────────────────────────────────────────────────────────
# Targeted updates (validated per domain, still keep the three systems separate)
# ─────────────────────────────────────────────────────────────────────────────

def set_permission_mode(mode: str) -> Dict[str, Any]:
    state = get_state()
    mode = str(mode or "").strip().lower().replace(" ", "_")
    if mode not in PERMISSION_MODES:
        return {"ok": False, "errors": [f"Invalid permission mode: {mode!r}"], "mode": state.get("permission_mode")}
    state["permission_mode"] = mode
    result = _persist(state)
    result["mode"] = mode
    result["legacy_mode"] = PERMISSION_TO_LEGACY.get(mode, "auto")
    result["sandbox_mode"] = state.get("sandbox_mode")
    result["workspace"] = workspace_root()
    _record_event("permission_changed", f"Permission mode changed to {mode}", risk="low")
    return result


def sync_permission_from_legacy(mode: str) -> str:
    """Keep the Safety permission mode in step when the legacy /mode API is used.

    Never touches the workspace selection.
    """
    state = get_state()
    new_mode = LEGACY_TO_PERMISSION.get(str(mode or "").strip().lower().replace(" ", "_"), "automatic")
    if state.get("permission_mode") != new_mode:
        state["permission_mode"] = new_mode
        _persist(state)
    return new_mode


def set_sandbox_mode(mode: str) -> Dict[str, Any]:
    state = get_state()
    mode = str(mode or "").strip().lower().replace(" ", "_")
    if mode not in SANDBOX_MODES:
        return {"ok": False, "errors": [f"Invalid sandbox mode: {mode!r}"], "mode": state.get("sandbox_mode")}
    state["sandbox_mode"] = mode
    result = _persist(state)
    result["mode"] = mode
    result["legacy_tier"] = SANDBOX_TO_LEGACY.get(mode, "normal")
    result["permission_mode"] = state.get("permission_mode")
    result["workspace"] = workspace_root()
    _record_event("sandbox_changed", f"Sandbox mode changed to {mode}", risk="low")
    return result


def sync_sandbox_from_legacy(tier: str) -> str:
    """Keep the Safety sandbox mode in step when the legacy /sandbox API is used.

    Never touches the workspace selection.
    """
    state = get_state()
    new_mode = LEGACY_TO_SANDBOX.get(str(tier or "").strip().lower().replace(" ", "_"), "workspace")
    if state.get("sandbox_mode") != new_mode:
        state["sandbox_mode"] = new_mode
        _persist(state)
    return new_mode


def set_command_policies(policies: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    if not isinstance(policies, dict):
        return {"ok": False, "errors": ["command policies must be an object"]}
    merged = dict(state.get("command_policies") or {})
    changed = []
    for category in COMMAND_CATEGORIES:
        if category["id"] in policies:
            value = _coerce_policy(policies[category["id"]], ("allow", "ask", "deny"))
            if value != merged.get(category["id"]):
                merged[category["id"]] = value
                changed.append(category["id"])
    state["command_policies"] = merged
    result = _persist(state)
    result["changed"] = changed
    return result


def set_file_policies(policies: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    if not isinstance(policies, dict):
        return {"ok": False, "errors": ["file policies must be an object"]}
    merged = dict(state.get("file_policies") or {})
    changed = []
    for category in FILE_POLICY_CATEGORIES:
        if category["id"] in policies:
            value = _coerce_policy(policies[category["id"]], ("allow", "ask", "deny", "read_only", "session"))
            if value != merged.get(category["id"]):
                merged[category["id"]] = value
                changed.append(category["id"])
    state["file_policies"] = merged
    result = _persist(state)
    result["changed"] = changed
    return result


def set_filesystem(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    for option in FILESYSTEM_OPTIONS:
        if option["id"] in options:
            state["filesystem"][option["id"]] = bool(options[option["id"]])
    result = _persist(state)
    return result


def set_secret_protection(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    for option in SECRET_PROTECTION_OPTIONS:
        if option["id"] in options:
            state["secret_protection"][option["id"]] = bool(options[option["id"]])
    result = _persist(state)
    return result


def set_network(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    network = state.setdefault("network", {})
    if "policy" in options:
        policy = str(options.get("policy") or "").strip().lower()
        if policy not in NETWORK_POLICIES:
            return {"ok": False, "errors": [f"Invalid network policy: {policy!r}"]}
        network["policy"] = policy
    for key in ("allowlist", "blocklist"):
        if key in options:
            values = options[key]
            if isinstance(values, list):
                network[key] = [str(item).strip() for item in values if str(item).strip()]
    for key in ("block_cloud_metadata", "block_local_metadata", "block_private_scanning", "block_unsafe_redirects", "block_credential_urls", "block_unsupported_protocols"):
        if key in options:
            network[key] = bool(options[key])
    result = _persist(state)
    return result


def set_browser(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    for option in BROWSER_OPTIONS:
        if option["id"] in options:
            state["browser"][option["id"]] = _coerce_policy(options[option["id"]], ("allow", "ask", "deny"))
    result = _persist(state)
    return result


def set_mcp(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    for option in MCP_OPTIONS:
        if option["id"] in options:
            state["mcp"][option["id"]] = bool(options[option["id"]])
    result = _persist(state)
    return result


def set_package(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    policies = state.setdefault("package", {}).setdefault("policies", {})
    if "managers" in options and isinstance(options.get("managers"), list):
        state["package"]["managers"] = [str(m).strip() for m in options["managers"] if str(m).strip()]
    for option in PACKAGE_OPTIONS:
        if option["id"] in options:
            value = options[option["id"]]
            if option.get("kind") == "bool":
                policies[option["id"]] = bool(value)
            else:
                policies[option["id"]] = _coerce_policy(value, ("allow", "ask", "deny"))
    result = _persist(state)
    return result


def set_process(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    for option in PROCESS_OPTIONS:
        if option["id"] in options:
            state["process"][option["id"]] = _coerce_policy(options[option["id"]], ("allow", "ask", "deny"))
    result = _persist(state)
    return result


def set_destructive(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    destructive = state.setdefault("destructive", {})
    if "require_approval" in options:
        destructive["require_approval"] = bool(options["require_approval"])
    if "require_typed_confirmation" in options:
        destructive["require_typed_confirmation"] = bool(options["require_typed_confirmation"])
    for action in DESTRUCTIVE_ACTIONS:
        if action["id"] in options:
            destructive.setdefault("actions", {})[action["id"]] = bool(options[action["id"]])
    result = _persist(state)
    return result


def set_checkpoints(options: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    for option in CHECKPOINT_OPTIONS:
        if option["id"] in options:
            value = options[option["id"]]
            if option.get("kind") == "int":
                try:
                    state["checkpoints"][option["id"]] = max(0, int(value))
                except (TypeError, ValueError):
                    continue
            else:
                state["checkpoints"][option["id"]] = bool(value)
    result = _persist(state)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Protected paths
# ─────────────────────────────────────────────────────────────────────────────

def _match_protected(rel_path: str, entry: Dict[str, Any]) -> bool:
    import fnmatch
    pattern = str(entry.get("pattern") or "").strip().replace("\\", "/")
    if not pattern:
        return False
    rel = str(rel_path or "").replace("\\", "/")
    normalized = rel.lstrip("/")
    candidates = [pattern]
    if pattern.startswith("**/"):
        candidates.append(pattern[3:])
    if pattern.endswith("/**"):
        candidates.append(pattern[:-3])
    for cand in candidates:
        if fnmatch.fnmatch(normalized, cand):
            return True
        if fnmatch.fnmatch(os.path.basename(normalized), cand):
            return True
    return False


def find_protected_path(path: str, action: str = "write") -> Optional[Dict[str, Any]]:
    """Return the strictest matching protected entry for a path, or None."""
    state = get_state()
    root = workspace_root()
    path = _canonical(path)
    try:
        rel = os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        rel = path.replace("\\", "/")
    if rel.startswith(".."):
        rel = path
    best: Optional[Dict[str, Any]] = None
    for entry in state.get("protected_paths") or []:
        if not isinstance(entry, dict):
            continue
        if not _match_protected(rel, entry):
            continue
        policy_key = f"{action}_policy"
        policy = str(entry.get(policy_key) or entry.get("policy") or "warn")
        if best is None:
            best = {**entry, "matched_policy": policy}
            continue
        # Prefer deny over warn over allow.
        rank = {"deny": 3, "warn": 2, "allow": 1}
        if rank.get(str(best.get("matched_policy")), 0) < rank.get(policy, 0):
            best = {**entry, "matched_policy": policy}
    return best


def is_protected_path(path: str, action: str = "write") -> bool:
    return find_protected_path(path, action) is not None


def add_protected_path(entry: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    pattern = str(entry.get("pattern") or "").strip()
    if not pattern:
        return {"ok": False, "errors": ["pattern is required"]}
    paths = state.get("protected_paths") or []
    for existing in paths:
        if isinstance(existing, dict) and existing.get("pattern") == pattern:
            return {"ok": False, "errors": ["That protected path already exists"]}
    paths.append({
        "pattern": pattern,
        "reason": str(entry.get("reason") or "User configured").strip(),
        "source": "user",
        "mandatory": False,
        "read_policy": str(entry.get("read_policy") or "warn"),
        "write_policy": str(entry.get("write_policy") or "deny"),
        "delete_policy": str(entry.get("delete_policy") or "deny"),
    })
    state["protected_paths"] = paths
    result = _persist(state)
    _record_event("protected_path_added", f"Protected path added: {pattern}", risk="low")
    return result


def update_protected_path(pattern: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    paths = state.get("protected_paths") or []
    for entry in paths:
        if isinstance(entry, dict) and entry.get("pattern") == pattern:
            if entry.get("mandatory"):
                return {"ok": False, "errors": ["Mandatory rules cannot be edited"]}
            for key in ("reason", "read_policy", "write_policy", "delete_policy"):
                if key in updates:
                    if key == "reason":
                        entry[key] = str(updates[key] or "").strip() or entry[key]
                    else:
                        entry[key] = _coerce_policy(updates[key], ("allow", "warn", "deny"))
            state["protected_paths"] = paths
            result = _persist(state)
            _record_event("protected_path_updated", f"Protected path updated: {pattern}", risk="low")
            return result
    return {"ok": False, "errors": ["Protected path not found"]}


def remove_protected_path(pattern: str) -> Dict[str, Any]:
    state = get_state()
    paths = state.get("protected_paths") or []
    remaining = []
    removed = False
    for entry in paths:
        if isinstance(entry, dict) and entry.get("pattern") == pattern:
            if entry.get("mandatory"):
                return {"ok": False, "errors": ["Mandatory rules cannot be removed"]}
            removed = True
            continue
        remaining.append(entry)
    if not removed:
        return {"ok": False, "errors": ["Protected path not found"]}
    state["protected_paths"] = remaining
    result = _persist(state)
    _record_event("protected_path_removed", f"Protected path removed: {pattern}", risk="low")
    return result


def reset_protected_paths() -> Dict[str, Any]:
    state = get_state()
    state["protected_paths"] = _default_protected_paths()
    result = _persist(state)
    _record_event("protected_paths_reset", "Protected paths reset to defaults", risk="medium")
    return result


def test_path(path: str) -> Dict[str, Any]:
    """Validate a candidate protected path pattern and test it against disk."""
    raw = str(path or "").strip()
    if not raw:
        return {"ok": False, "errors": ["path is required"]}
    root = workspace_root()
    if os.path.isabs(raw):
        resolved = _canonical(raw)
        inside = _is_within(root, resolved)
    else:
        resolved = os.path.join(root, raw.strip("/\\"))
        inside = True
    matches = []
    for entry in get_state().get("protected_paths") or []:
        if isinstance(entry, dict) and _match_protected(raw, entry):
            matches.append(entry.get("pattern"))
    return {
        "ok": True,
        "errors": [],
        "result": {
            "path": raw,
            "resolved": resolved,
            "exists": os.path.exists(resolved),
            "is_dir": os.path.isdir(resolved),
            "inside_workspace": inside,
            "matches_protected": len(matches),
            "matched_patterns": matches,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Temporary permissions & approvals
# ─────────────────────────────────────────────────────────────────────────────

def _new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def add_temp_permission(entry: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    created = time.time()
    duration = max(60, int(entry.get("duration_seconds") or 0))
    permission = {
        "id": _new_id("tmp"),
        "permission": str(entry.get("permission") or "unknown"),
        "scope": str(entry.get("scope") or "workspace"),
        "workspace": workspace_root(),
        "created_at": created,
        "expires_at": created + duration,
        "task": str(entry.get("task") or ""),
        "source": str(entry.get("source") or "user"),
        "duration_seconds": duration,
    }
    state.setdefault("temp_permissions", []).append(permission)
    result = _persist(state)
    _record_event("temp_permission_created", f"Temporary permission created: {permission['permission']}", risk="medium")
    return result


def revoke_temp_permission(permission_id: str) -> Dict[str, Any]:
    state = get_state()
    permissions = state.get("temp_permissions") or []
    remaining = [p for p in permissions if str(p.get("id")) != str(permission_id)]
    if len(remaining) == len(permissions):
        return {"ok": False, "errors": ["Temporary permission not found"]}
    state["temp_permissions"] = remaining
    result = _persist(state)
    _record_event("temp_permission_revoked", "Temporary permission revoked", risk="medium")
    return result


def extend_temp_permission(permission_id: str, seconds: int = 3600) -> Dict[str, Any]:
    state = get_state()
    for permission in state.get("temp_permissions") or []:
        if str(permission.get("id")) == str(permission_id):
            permission["expires_at"] = max(permission.get("expires_at") or time.time(), time.time()) + max(60, int(seconds or 0))
            result = _persist(state)
            return result
    return {"ok": False, "errors": ["Temporary permission not found"]}


def list_temp_permissions() -> List[Dict[str, Any]]:
    state = get_state()
    now = time.time()
    permissions = []
    for permission in state.get("temp_permissions") or []:
        expires = float(permission.get("expires_at") or 0)
        remaining = max(0, expires - now)
        permissions.append({
            **permission,
            "expired": remaining <= 0,
            "remaining_seconds": int(remaining),
        })
    return sorted(permissions, key=lambda p: p.get("created_at") or 0, reverse=True)


def active_temp_permissions() -> List[Dict[str, Any]]:
    return [p for p in list_temp_permissions() if not p.get("expired")]


def convert_temp_permission(permission_id: str) -> Dict[str, Any]:
    """Convert a temporary permission into a workspace-scoped approval record."""
    state = get_state()
    permissions = state.get("temp_permissions") or []
    for permission in permissions:
        if str(permission.get("id")) == str(permission_id):
            state.setdefault("approval_history", []).append({
                "id": _new_id("appr"),
                "time": time.time(),
                "action": str(permission.get("permission") or ""),
                "tool": "user-granted",
                "workspace": str(permission.get("workspace") or ""),
                "permission": str(permission.get("permission") or ""),
                "decision": "allow",
                "scope": "workspace",
                "temporary": False,
                "source": str(permission.get("source") or "user"),
                "expiration": None,
            })
            state["temp_permissions"] = [p for p in permissions if str(p.get("id")) != str(permission_id)]
            result = _persist(state)
            _record_event("temp_permission_converted", "Temporary permission converted to workspace permission", risk="high")
            return result
    return {"ok": False, "errors": ["Temporary permission not found"]}


def record_approval(entry: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    now = time.time()
    duration = max(60, int(entry.get("duration_seconds") or 0))
    temporary = bool(entry.get("temporary", False))
    record = {
        "id": _new_id("appr"),
        "time": now,
        "action": str(entry.get("action") or ""),
        "tool": str(entry.get("tool") or "unknown"),
        "workspace": workspace_root(),
        "permission": str(entry.get("permission") or ""),
        "decision": str(entry.get("decision") or "allow"),
        "scope": str(entry.get("scope") or "once"),
        "temporary": temporary,
        "source": str(entry.get("source") or "approval_panel"),
        "expiration": (now + duration) if temporary else None,
    }
    state.setdefault("approval_history", []).append(record)
    if len(state["approval_history"]) > 200:
        state["approval_history"] = state["approval_history"][-200:]
    result = _persist(state)
    return result


def revoke_approval(approval_id: str) -> Dict[str, Any]:
    state = get_state()
    history = state.get("approval_history") or []
    remaining = [h for h in history if str(h.get("id")) != str(approval_id)]
    if len(remaining) == len(history):
        return {"ok": False, "errors": ["Approval record not found"]}
    state["approval_history"] = remaining
    result = _persist(state)
    _record_event("approval_revoked", "Approval record revoked", risk="medium")
    return result


def clear_expired_approvals() -> Dict[str, Any]:
    state = get_state()
    now = time.time()
    history = state.get("approval_history") or []
    remaining = [h for h in history if not (h.get("temporary") and h.get("expiration") and float(h.get("expiration") or 0) < now)]
    cleared = len(history) - len(remaining)
    state["approval_history"] = remaining
    result = _persist(state)
    result["cleared"] = cleared
    return result


def list_approvals(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    state = get_state()
    now = time.time()
    history = state.get("approval_history") or []
    results = []
    for record in history:
        active = not (record.get("temporary") and record.get("expiration") and float(record.get("expiration") or 0) < now)
        results.append({**record, "active": active, "remaining_seconds": max(0, int(float(record.get("expiration") or 0) - now)) if record.get("expiration") else None})
    filters = filters or {}
    if filters.get("decision"):
        results = [r for r in results if str(r.get("decision")) == str(filters["decision"])]
    if filters.get("temporary") in (True, False):
        results = [r for r in results if bool(r.get("temporary")) == bool(filters["temporary"])]
    return sorted(results, key=lambda r: r.get("time") or 0, reverse=True)


def pending_approval_count() -> int:
    return 0  # approvals are resolved through the approval broker in runtime


def blocked_action_count() -> int:
    state = get_state()
    return sum(1 for event in state.get("safety_events") or [] if str(event.get("decision")) == "blocked")


# ─────────────────────────────────────────────────────────────────────────────
# Safety events
# ─────────────────────────────────────────────────────────────────────────────

def _record_event(event_type: str, description: str, risk: str = "unknown", decision: str = "none", detail: str = "") -> None:
    try:
        state = get_state()
        events = state.get("safety_events") or []
        events.append({
            "id": _new_id("evt"),
            "time": time.time(),
            "event_type": event_type,
            "action": str(detail or description),
            "tool": "",
            "workspace": workspace_root(),
            "risk": risk,
            "decision": decision,
            "reason": description,
            "status": "recorded",
        })
        if len(events) > 200:
            events = events[-200:]
        state["safety_events"] = events
        config = _load_yaml()
        config["safety"] = state
        _save_yaml(config)
        with _LOCK:
            global _STATE
            _STATE = copy.deepcopy(state)
    except Exception:
        pass


def list_events(limit: int = 100) -> List[Dict[str, Any]]:
    state = get_state()
    events = state.get("safety_events") or []
    safe_limit = max(1, min(int(limit or 100), 200))
    return [dict(event) for event in events[-safe_limit:][::-1]]


def last_safety_event() -> Optional[Dict[str, Any]]:
    events = list_events(limit=1)
    return events[0] if events else None


# ─────────────────────────────────────────────────────────────────────────────
# Secret redaction
# ─────────────────────────────────────────────────────────────────────────────

_SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|token|secret|password|passwd|client[_-]?secret)\s*[=:]\s*[\"']?[^\s,;]+", "key=value"),
    (r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/=-]+", "bearer"),
    (r"\b(?:sk-proj-|sk-)[A-Za-z0-9_-]{8,}\b", "sk-token"),
    (r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b", "github-token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "aws-access-key"),
    (r"\b(?:AIza[0-9A-Za-z_-]{20,})\b", "google-api-key"),
    (r"\b(?:xox[baprs]-)[A-Za-z0-9-]{10,}\b", "slack-token"),
    (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "private-key"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "jwt"),
]


def redact_text(text: str) -> str:
    """Redact secret-looking values from text. Never returns full secret values."""
    result = str(text or "")
    redacted = 0
    for pattern, kind in _SECRET_PATTERNS:
        new_result, count = re.subn(pattern, lambda m: f"[REDACTED:{kind}]", result)
        redacted += count
        result = new_result
    if redacted:
        _bump_scan_counts(redacted=redacted)
    return result


def redaction_scan(text: str) -> Dict[str, Any]:
    """Count redactable matches without exposing their values."""
    result = str(text or "")
    counts: Dict[str, int] = {}
    for pattern, kind in _SECRET_PATTERNS:
        matches = re.findall(pattern, result)
        if matches:
            counts[kind] = len(matches)
    return {"matches": sum(counts.values()), "kinds": counts}


# In-memory secret-scan counters. Kept out of the config file so that routine
# redaction never triggers a disk write; they accumulate for the lifetime of the
# process and reset on restart. Only counts, never values.
_SCAN_COUNTS: Dict[str, Any] = {"blocked": 0, "redacted": 0, "pending": 0, "last_scan": None}


def _bump_scan_counts(redacted: int = 0, blocked: int = 0, pending: int = 0) -> None:
    """Update the aggregate secret-scan counters (counts only, never values)."""
    _SCAN_COUNTS["blocked"] = int(_SCAN_COUNTS.get("blocked") or 0) + blocked
    _SCAN_COUNTS["redacted"] = int(_SCAN_COUNTS.get("redacted") or 0) + redacted
    _SCAN_COUNTS["pending"] = int(_SCAN_COUNTS.get("pending") or 0) + pending
    _SCAN_COUNTS["last_scan"] = time.time()


def secret_counts() -> Dict[str, Any]:
    """Aggregate secret-scan counts. Values are never included."""
    state = get_state()
    pending = len([a for a in (state.get("approval_history") or []) if a.get("status") == "pending"])
    return {
        "protected": len(state.get("protected_paths") or []),
        "blocked": int(_SCAN_COUNTS.get("blocked") or 0),
        "redacted": int(_SCAN_COUNTS.get("redacted") or 0),
        "pending": int(_SCAN_COUNTS.get("pending") or 0) + pending,
        "last_scan": _SCAN_COUNTS.get("last_scan"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def run_diagnostics() -> Dict[str, Any]:
    state = get_state()
    checks: List[Dict[str, Any]] = []

    def add(name: str, status: str, detail: str, action: str = "") -> None:
        checks.append({"name": name, "status": status, "detail": detail, "action": action})

    try:
        import server  # noqa: F401
        add("Safety backend", "healthy", "Safety API reachable")
    except Exception:
        add("Safety backend", "failed", "Safety API could not be imported", "Restart the Nexus server")

    try:
        from permissions import PermissionSystem
        _ = PermissionSystem().mode
        add("Permission engine", "healthy", "Permission system loads and responds")
    except Exception:
        add("Permission engine", "failed", "Permission engine could not be initialised", "Restart the Nexus server")

    try:
        from sandbox.sandbox_manager import SandboxTier, SovereignSandbox
        _ = SovereignSandbox(workspace_root())
        add("Sandbox engine", "healthy", "Sandbox manager initialised")
    except Exception:
        add("Sandbox engine", "failed", "Sandbox manager could not be initialised", "Restart the Nexus server")

    root = workspace_root()
    exists = os.path.isdir(root)
    add("Workspace root protection", "healthy" if exists else "failed", f"Root exists: {root}" if exists else "Selected workspace is missing")
    add("Command interception", "healthy", "Command risk scoring + policy checks are active")
    add("File policy", "healthy", f"{len(state.get('file_policies') or {})} file policies configured")
    add("Secret redaction", "healthy" if state.get("secret_protection", {}).get("detect_secrets") else "warning", "Secret scanning active" if state.get("secret_protection", {}).get("detect_secrets") else "Secret scanning disabled")
    add("Network policy", "healthy", f"Policy: {state.get('network', {}).get('policy')}")
    add("Browser policy", "healthy", f"{len(state.get('browser') or {})} browser controls configured")
    add("MCP policy", "healthy", "MCP controls configured")
    add("Approval storage", "healthy", f"{len(state.get('approval_history') or [])} approval record(s)")
    add("Checkpoint service", "healthy" if state.get("checkpoints", {}).get("create_before_file_changes") else "warning", "Checkpoints enabled" if state.get("checkpoints", {}).get("create_before_file_changes") else "Checkpoints disabled")
    add("Audit storage", "healthy", f"{len(state.get('safety_events') or [])} safety event(s) recorded")
    add("Configuration validity", "healthy", "Safety configuration is valid")
    return {"status": "ok", "run_at": time.time(), "checks": checks}


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

def summary() -> Dict[str, Any]:
    state = get_state()
    filesystem = state.get("filesystem") or {}
    secret = state.get("secret_protection") or {}
    network = state.get("network") or {}
    browser = state.get("browser") or {}
    mcp = state.get("mcp") or {}
    destructive = state.get("destructive") or {}
    root = workspace_root()
    protected = state.get("protected_paths") or []
    exists = os.path.isdir(root)
    return {
        "workspace": root,
        "workspace_exists": exists,
        "permission_mode": state.get("permission_mode"),
        "permission_label": PERMISSION_MODES.get(state.get("permission_mode"), {}).get("label", state.get("permission_mode")),
        "sandbox_mode": state.get("sandbox_mode"),
        "sandbox_label": SANDBOX_MODES.get(state.get("sandbox_mode"), {}).get("label", state.get("sandbox_mode")),
        "root_protection": bool(filesystem.get("enforce_workspace_root", True)),
        "command_protection": _command_protection_active(),
        "file_protection": _file_protection_active(),
        "network_policy": network.get("policy"),
        "network_policy_label": NETWORK_POLICIES.get(str(network.get("policy")), {}).get("label", network.get("policy")),
        "browser_policy": _browser_summary(browser),
        "mcp_policy": _mcp_summary(mcp),
        "destructive_policy": "approval required" if destructive.get("require_approval") else "no approval required",
        "active_temp_permissions": len(active_temp_permissions()),
        "pending_approvals": pending_approval_count(),
        "blocked_action_count": blocked_action_count(),
        "last_safety_event": last_safety_event(),
        "backend_status": "healthy",
        "protected_path_count": len(protected),
        "redaction_active": bool(secret.get("detect_secrets")),
        "secret_counts": secret_counts(),
        "last_saved": state.get("last_saved"),
    }


def _command_protection_active() -> bool:
    state = get_state()
    policies = state.get("command_policies") or {}
    for category in COMMAND_CATEGORIES:
        if category["id"] in ("safe_commands",):
            continue
        if policies.get(category["id"]) in ("ask", "deny"):
            return True
    return False


def _file_protection_active() -> bool:
    state = get_state()
    policies = state.get("file_policies") or {}
    for category in FILE_POLICY_CATEGORIES:
        if category["id"] == "read_file":
            continue
        if policies.get(category["id"]) in ("ask", "deny", "read_only", "session"):
            return True
    return False


def _browser_summary(browser: Dict[str, Any]) -> str:
    if not browser:
        return "configured"
    deny = sum(1 for value in browser.values() if value == "deny")
    if deny == len(browser):
        return "all denied"
    if deny:
        return f"{deny} denied"
    return "as configured"


def _mcp_summary(mcp: Dict[str, Any]) -> str:
    if not mcp:
        return "configured"
    if not mcp.get("allow_servers"):
        return "disabled"
    if mcp.get("require_approval_unknown"):
        return "approval for unknown tools"
    return "enabled"


# ─────────────────────────────────────────────────────────────────────────────
# Enforcement
# ─────────────────────────────────────────────────────────────────────────────

def _command_policy_for(action: str) -> tuple:
    """Return (category_id, risk, reason) for a command action."""
    lowered = str(action or "").strip().lower()
    rules = [
        # High-risk matches must precede the broad read-command rule below.
        # Otherwise `type .env` and `echo ok && type .env` are classified as
        # safe before credential/chaining checks get a chance to run.
        (r"\b(get-content|type|cat|head|tail)\b.*(\.env|\.pem|\.key|id_rsa|credential|secret)", "credential_access", "Critical"),
        (r"\b(env|printenv|set)\b", "credential_access", "Critical"),
        (r"(?:(?<=\s)|^)(?:&&|\|\||;)(?=\s|$)", "command_chaining", "Medium"),
        (r"^\s*(dir|ls|pwd|date|echo|type|cat|head|tail|rg|grep|findstr|where)\b", "safe_commands", "Safe"),
        (r"\b(rm|Remove-Item|del|erase)\b.*(-[rR][a-zA-Z]*[fF]|-recurse)", "destructive_commands", "Critical"),
        (r"\b(git\s+clean|git\s+reset\s+--hard)\b", "destructive_commands", "Critical"),
        (r"\b(rmdir|Remove-Item)\b.*/\s*[sq]", "destructive_commands", "Critical"),
        (r"\b(rm -rf\s+/|del /s /q)\b", "destructive_commands", "Critical"),
        (r"\b(sudo|runas|gsudo|elevat(e|ion)|Start-Process.*-Verb\s+RunAs)\b", "privilege_escalation", "Critical"),
        (r"\b(shutdown|reboot|Restart-Computer|Stop-Computer)\b", "system_shutdown", "Critical"),
        (r"\b(restart|Restart-Computer)\b", "system_restart", "Critical"),
        (r"\b(format|diskpart|mkfs\.|fdisk|dd if=)\b", "disk_formatting", "Critical"),
        (r"\b(diskpart|parted|sfdisk|gpt|mbr)\b", "partition_changes", "Critical"),
        (r"\b(reg\s+(add|delete|copy|save|restore)|Set-ItemProperty.*\bHKLM)\b", "registry_modification", "High"),
        (r"\b(bcdedit|bootcfg|msconfig|Set-ItemProperty.*boot)\b", "boot_configuration", "Critical"),
        (r"\b(net\s+user|net\s+localgroup|New-LocalUser|Set-LocalUser|Remove-LocalUser)\b", "user_account_changes", "Critical"),
        (r"\b(netsh\s+advfirewall|Set-NetFirewallRule|New-NetFirewallRule)\b", "firewall_changes", "High"),
        (r"\b(Set-MpPreference|Stop-Service\s+WinDefend|Disable-ScheduledTask.*Defender)\b", "security_tool_disabling", "Critical"),
        (r"\b(mimikatz|secretsdump|Invoke-Mimikatz|kekeo)\b", "credential_access", "Critical"),
        (r"\b(CreateRemoteThread|Inject-Process|dllinject|process\s+inject)\b", "process_injection", "Critical"),
        (r"\b(Register-ScheduledTask|schtasks\s+/create|at\s+)\b", "scheduled_task_creation", "High"),
        (r"\b(New-Service|sc\s+create|service\s+install)\b", "service_creation", "High"),
        (r"\b(New-ItemProperty.*CurrentVersion\\Run|\.bashrc|\.bash_profile|\.zshrc|\.profile)\b", "persistence_creation", "High"),
        (r"\b(Start-Process.*-WindowStyle\s+Hidden|powershell\.exe\s+-WindowStyle\s+Hidden|start\s+/b)\b", "hidden_background_execution", "High"),
        (r"\.\.(?:\\|/)+", "path_traversal", "Critical"),
        (r"\b(cd\s+\.\.|\$env:)\b", "unresolved_variables", "Medium"),
        (r"\b\|\s*(Select-Object|Out-String|ConvertTo-Json|more|less)\b|\b(\|)\b", "command_pipelines", "Medium"),
        (r"[>]{1,2}\s*[^\s]", "output_redirection", "Medium"),
        (r"\b(start|Start-Process|Start-Job|scheduled)\b", "detached_processes", "High"),
        (r"\b(pip\s+install|npm\s+install|pnpm\s+(add|install)|yarn\s+add|uv\s+add|poetry\s+add|cargo\s+install|go\s+(get|install))\b", "safe_commands", "Safe"),
    ]
    for pattern, category_id, risk in rules:
        if re.search(pattern, lowered):
            return category_id, risk, pattern
    return "safe_commands", "Safe", ""


def enforce_command(action: str, tool: str = "bash", session_id: str = "") -> EnforcementResult:
    """Enforce permission + command policies for a shell command."""
    state = get_state()
    permission = state.get("permission_mode")
    if permission == "deny_all":
        return EnforcementResult(False, "block", "Deny all tools mode is active. Nexus responds with text only.", policy="permission_mode", risk="Critical", requires_approval=False, category="deny_all")

    category_id, risk, _reason = _command_policy_for(action)
    policy = str(state.get("command_policies", {}).get(category_id) or "ask")

    if permission == "read_only":
        if category_id in ("destructive_commands", "privilege_escalation", "disk_formatting", "partition_changes", "system_shutdown", "system_restart", "path_traversal", "credential_access", "security_tool_disabling", "process_injection"):
            return EnforcementResult(False, "deny", "Read-only mode blocks this command.", policy="permission_mode", risk=risk, requires_approval=False, category=category_id)

    if policy == "deny":
        return EnforcementResult(False, "deny", f"Command blocked by policy ({category_id}).", policy=category_id, risk=risk, requires_approval=False, category=category_id)
    if policy == "ask":
        return EnforcementResult(True, "ask", f"Command requires approval ({category_id}).", policy=category_id, risk=risk, requires_approval=True, category=category_id)
    if permission == "restricted":
        return EnforcementResult(True, "ask", "Restricted mode requires approval for commands.", policy="permission_mode", risk=risk, requires_approval=True, category=category_id)
    return EnforcementResult(True, "allow", f"Command allowed ({category_id}).", policy=category_id, risk=risk, requires_approval=False, category=category_id)


def enforce_file_action(action: str, path: str, tool: str = "file") -> EnforcementResult:
    """Enforce permission + file policies + protected paths for a file operation."""
    state = get_state()
    permission = state.get("permission_mode")
    if permission == "deny_all":
        return EnforcementResult(False, "block", "Deny all tools mode is active.", policy="permission_mode", risk="Critical", requires_approval=False, category="deny_all")

    if action not in ("read", "write", "delete", "rename", "move", "create"):
        action = "write"
    policy = str(state.get("file_policies", {}).get(f"{action}_file") or (state.get("file_policies", {}).get("modify_file") if action == "write" else "ask"))

    if permission == "read_only":
        if action != "read":
            return EnforcementResult(False, "deny", "Read-only mode denies file changes.", policy="permission_mode", risk="High", requires_approval=False, category="read_only")

    if permission == "restricted" and action != "read":
        return EnforcementResult(True, "ask", "Restricted mode requires approval for file changes.", policy="permission_mode", risk="Medium", requires_approval=True, category="restricted")

    protected = find_protected_path(path, action="write" if action != "read" else "read")
    if protected is not None:
        matched = str(protected.get("matched_policy") or "warn")
        reason = f"Protected path: {protected.get('pattern')} ({matched})"
        if matched == "deny":
            return EnforcementResult(False, "deny", reason, policy="protected_path", risk="Critical", requires_approval=False, category="protected_path")
        if matched == "warn" and action == "read":
            return EnforcementResult(True, "ask", f"{reason}. Reading sensitive content requires approval.", policy="protected_path", risk="Medium", requires_approval=True, category="protected_path")
        if matched == "warn":
            return EnforcementResult(True, "ask", f"{reason}. Modifying sensitive content requires approval.", policy="protected_path", risk="High", requires_approval=True, category="protected_path")

    if policy == "deny":
        return EnforcementResult(False, "deny", f"File policy blocks {action}.", policy="file_policy", risk="Medium", requires_approval=False, category=action)
    if policy in ("ask", "read_only", "session"):
        if policy == "read_only" and action != "read":
            return EnforcementResult(False, "deny", "Read-only file policy.", policy="file_policy", risk="Medium", requires_approval=False, category=action)
        return EnforcementResult(True, "ask", f"File {action} requires approval.", policy="file_policy", risk="Medium", requires_approval=True, category=action)
    return EnforcementResult(True, "allow", f"File {action} allowed.", policy="file_policy", risk="Low", requires_approval=False, category=action)


def enforce_network(url: str) -> EnforcementResult:
    """Enforce network policy against a destination URL."""
    state = get_state()
    network = state.get("network") or {}
    policy = str(network.get("policy") or "ask")
    lowered = str(url or "").lower()

    # Blocklists that apply regardless of the chosen policy so that metadata
    # endpoints, private scanning, credential URLs, and unsupported protocols
    # are never silently allowed.
    if network.get("block_cloud_metadata", True) and re.search(
        r"169\.254\.169\.254|metadata\.google\.internal|metadata\.amazonaws\.com|instance-data",
        lowered,
    ):
        return EnforcementResult(False, "deny", "Cloud metadata endpoints are blocked.", policy="network", risk="Critical", requires_approval=False, category="cloud_metadata")
    if network.get("block_local_metadata", True) and re.search(
        r"(^|\.)localhost$|127\.0\.0\.1|::1|169\.254\.\d+\.\d+",
        lowered,
    ):
        return EnforcementResult(False, "deny", "Local metadata endpoints are blocked.", policy="network", risk="Critical", requires_approval=False, category="local_metadata")
    if network.get("block_private_scanning", True) and re.search(
        r"10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+",
        lowered,
    ):
        return EnforcementResult(False, "deny", "Private-network scanning is blocked.", policy="network", risk="High", requires_approval=False, category="private_scanning")
    if network.get("block_credential_urls", True) and re.search(
        r"//[^/]*(credential|token|secret|password|session|cookie|api[_-]?key)[^/]*[/:]",
        lowered,
    ):
        return EnforcementResult(False, "deny", "Credential-bearing URLs are blocked.", policy="network", risk="High", requires_approval=False, category="credential_url")
    scheme = re.match(r"^([a-z][a-z0-9+.-]*):", lowered)
    if scheme and network.get("block_unsupported_protocols", True) and scheme.group(1) not in ("http", "https"):
        return EnforcementResult(False, "deny", f"Unsupported protocol: {scheme.group(1)}.", policy="network", risk="Medium", requires_approval=False, category="unsupported_protocol")

    if policy == "deny_all":
        return EnforcementResult(False, "deny", "Network access is denied.", policy="network", risk="Medium", requires_approval=False, category="network")
    if policy == "allow_all":
        return EnforcementResult(True, "allow", "Network access allowed.", policy="network", risk="Low", requires_approval=False, category="network")
    if policy == "approved_domains":
        allowlist = [str(item).lower() for item in (network.get("allowlist") or []) if str(item).strip()]
        blocklist = [str(item).lower() for item in (network.get("blocklist") or []) if str(item).strip()]
        domain = re.sub(r"^[a-z]+://", "", lowered).split("/")[0].split(":")[0].rstrip(".")
        if any(domain == blocked or domain.endswith("." + blocked) for blocked in blocklist):
            return EnforcementResult(False, "deny", f"Domain blocked: {domain}", policy="network", risk="Medium", requires_approval=False, category="network")
        if any(domain == approved or domain.endswith("." + approved) for approved in allowlist):
            return EnforcementResult(True, "allow", f"Domain approved: {domain}", policy="network", risk="Low", requires_approval=False, category="network")
        return EnforcementResult(False, "deny", f"Domain not approved: {domain}", policy="network", risk="Medium", requires_approval=False, category="network")
    return EnforcementResult(True, "ask", "Network request requires approval.", policy="network", risk="Low", requires_approval=True, category="network")


def enforce_mcp(server_name: str, action: str = "read") -> EnforcementResult:
    state = get_state()
    mcp = state.get("mcp") or {}
    if not mcp.get("allow_servers"):
        return EnforcementResult(False, "deny", "MCP servers are disabled.", policy="mcp", risk="Medium", requires_approval=False, category="mcp")
    if action == "write" and not mcp.get("allow_write_actions"):
        return EnforcementResult(False, "deny", "MCP write actions are disabled.", policy="mcp", risk="Medium", requires_approval=False, category="mcp")
    if mcp.get("require_approval_unknown"):
        return EnforcementResult(True, "ask", "MCP tool requires approval.", policy="mcp", risk="Low", requires_approval=True, category="mcp")
    return EnforcementResult(True, "allow", "MCP action allowed.", policy="mcp", risk="Low", requires_approval=False, category="mcp")


def enforce_package(package: str, action: str = "install") -> EnforcementResult:
    state = get_state()
    policies = state.get("package", {}).get("policies") or {}
    if not policies.get("allow_install") or policies.get("allow_install") == "deny":
        return EnforcementResult(False, "deny", "Package installation is disabled.", policy="package", risk="Medium", requires_approval=False, category="package")
    if policies.get("allow_install") == "ask":
        return EnforcementResult(True, "ask", "Package installation requires approval.", policy="package", risk="Medium", requires_approval=True, category="package")
    return EnforcementResult(True, "allow", "Package installation allowed.", policy="package", risk="Low", requires_approval=False, category="package")


# ─────────────────────────────────────────────────────────────────────────────
# Presets
# ─────────────────────────────────────────────────────────────────────────────

def list_presets() -> List[Dict[str, Any]]:
    state = get_state()
    return [
        {
            "id": preset_id,
            "label": preset.get("label", preset_id),
            "description": preset.get("description", ""),
            "changes": _preset_changes(preset, state),
            "reduces_protection": _preset_reduces_protection(preset, state),
        }
        for preset_id, preset in PRESETS.items()
    ]


def _preset_changes(preset: Dict[str, Any], state: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    if "permission_mode" in preset and preset["permission_mode"] != state.get("permission_mode"):
        changes.append({"field": "permission_mode", "from": state.get("permission_mode"), "to": preset["permission_mode"]})
    if "sandbox_mode" in preset and preset["sandbox_mode"] != state.get("sandbox_mode"):
        changes.append({"field": "sandbox_mode", "from": state.get("sandbox_mode"), "to": preset["sandbox_mode"]})
    for group in ("command_policies", "file_policies", "network", "secret_protection", "checkpoints"):
        if group in preset:
            current = state.get(group) or {}
            for key, value in preset[group].items():
                if str(current.get(key)) != str(value):
                    changes.append({"field": f"{group}.{key}", "from": current.get(key), "to": value})
    return changes


def _preset_reduces_protection(preset: Dict[str, Any], state: Dict[str, Any]) -> bool:
    """Detect whether applying a preset would reduce protection vs. current state."""
    risk_rank = {"deny": 3, "ask": 2, "allow": 1}
    rank = 0
    if preset.get("permission_mode") in ("automatic", "custom"):
        if state.get("permission_mode") in ("restricted", "read_only", "deny_all"):
            rank += 1
    net = preset.get("network") or {}
    if net.get("policy") in ("allow_all", "browser_only"):
        current_net = (state.get("network") or {}).get("policy")
        if current_net in ("deny_all", "approved_domains", "ask"):
            rank += 1
    for group in ("command_policies", "file_policies"):
        if group in preset:
            current = state.get(group) or {}
            for key, value in preset[group].items():
                if risk_rank.get(str(current.get(key)), 0) < risk_rank.get(str(value), 0):
                    rank += 1
    return rank > 0


def apply_preset(preset_id: str) -> Dict[str, Any]:
    if preset_id not in PRESETS:
        return {"ok": False, "errors": [f"Unknown preset: {preset_id!r}"]}
    if preset_id == "custom":
        return {"ok": True, "errors": [], "message": "Custom preset keeps current policies."}
    preset = PRESETS[preset_id]
    state = get_state()
    before = copy.deepcopy(state)
    if "permission_mode" in preset:
        state["permission_mode"] = preset["permission_mode"]
    if "sandbox_mode" in preset:
        state["sandbox_mode"] = preset["sandbox_mode"]
    for group in ("command_policies", "file_policies", "secret_protection", "checkpoints"):
        if group in preset:
            for key, value in preset[group].items():
                state[group][key] = value
    if "network" in preset:
        for key, value in preset["network"].items():
            state["network"][key] = value
    result = _persist(state)
    if result.get("ok"):
        _record_event("preset_applied", f"Safety preset applied: {preset_id}", risk="medium")
    return {**result, "changes": _preset_changes(preset, before)}
