"""Capability inheritance resolution for Hive agents (§14).

Given a set of *available* main-agent capabilities plus a Hive agent's
declared inheritance mode, produce the concrete capability set the agent may
use.

The resolver is provider/tool-registry agnostic: the caller supplies the
*available* capability lists (discovered from the live runtime) and receives
back a resolved :class:`CapabilitySpec`.  It never invents capabilities the
main agent does not actually have, and it blocks silent privilege escalation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import CapabilityMode, CapabilitySpec
from .specializations import get_specialization


# Capabilities that are *never* inherited by default and require explicit opt-in.
# This is the core anti-privilege-escalation guard (§29, §44).
RESTRICTED_BY_DEFAULT = (
    "shell", "terminal", "write", "edit", "delete", "deploy", "publish",
    "exfiltrate", "secret", "credential", "mcp_admin", "plugin_install",
    "agent_create", "subagent_create", "production_write",
)

# Categories a normal agent may inherit broadly under FULL mode (read-mostly).
SAFE_FULL_TOOLS = (
    "read", "grep", "search", "web", "planning", "todo", "test",
)


class CapabilityError(ValueError):
    """Raised when a capability assignment would violate a security boundary."""


def _intersect(available: List[str], requested: List[str]) -> List[str]:
    avail = set(available or [])
    return [r for r in requested if r in avail]


def _dedupe(items: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def resolve(
    mode: str,
    available: Dict[str, List[str]],
    *,
    explicit: Optional[CapabilitySpec] = None,
    specialization: Optional[str] = None,
    parent_capabilities: Optional[CapabilitySpec] = None,
    security_limits: Optional[List[str]] = None,
) -> CapabilitySpec:
    """Resolve a concrete :class:`CapabilitySpec` for a Hive agent.

    Args:
        mode: one of ``CapabilityMode`` values.
        available: mapping of category -> list of capability names the main
            agent is actually permitted to delegate (e.g.
            ``{"tools": [...], "skills": [...], "providers": [...]}``).
        explicit: the agent's own ``CapabilitySpec`` (overrides/selected/etc.).
        specialization: optional specialization key whose ROLE_BASED profile is
            used as the base for ``ROLE_BASED`` mode.
        parent_capabilities: for sub-agents, the parent's resolved capabilities
            (sub-agents may only inherit a subset of their parent).
        security_limits: capability names the operator has forbidden for Hive
            agents entirely (hard ceiling).

    Returns:
        A resolved :class:`CapabilitySpec` whose lists contain only names
        present in ``available`` (plus ``inherits_all`` markers where the live
        runtime understands them).
    """
    try:
        mode = CapabilityMode(mode).value
    except ValueError:
        mode = CapabilityMode.ROLE_BASED.value

    limits = set(security_limits or set())
    avail_tools = [t for t in (available.get("tools") or []) if t not in limits]
    avail_skills = [s for s in (available.get("skills") or []) if s not in limits]
    avail_plugins = [p for p in (available.get("plugins") or []) if p not in limits]
    avail_mcp = [m for m in (available.get("mcp_servers") or []) if m not in limits]
    avail_models = list(available.get("models") or [])
    avail_providers = list(available.get("providers") or [])
    avail_memory = list(available.get("memory") or [])
    avail_permissions = [p for p in (available.get("permissions") or []) if p not in limits]

    explicit = explicit or CapabilitySpec(mode=mode)
    base = CapabilitySpec(mode=mode)

    if mode == CapabilityMode.FULL.value:
        # Inherit everything available, subject to the safe-default boundary:
        # mutating/secret capabilities are NOT auto-granted; they must be
        # explicitly listed in the agent's overrides to be allowed (no silent
        # privilege escalation).
        base.tools = [t for t in avail_tools if t not in RESTRICTED_BY_DEFAULT]
        base.skills = list(avail_skills)
        base.plugins = list(avail_plugins)
        base.mcp_servers = list(avail_mcp)
        base.models = list(avail_models)
        base.providers = list(avail_providers)
        base.memory = list(avail_memory)
        base.permissions = [p for p in avail_permissions if p not in RESTRICTED_BY_DEFAULT]

    elif mode == CapabilityMode.SELECTED.value:
        base.tools = _intersect(avail_tools, explicit.tools)
        base.skills = _intersect(avail_skills, explicit.skills)
        base.plugins = _intersect(avail_plugins, explicit.plugins)
        base.mcp_servers = _intersect(avail_mcp, explicit.mcp_servers)
        base.models = _intersect(avail_models, explicit.models)
        base.providers = _intersect(avail_providers, explicit.providers)
        base.memory = _intersect(avail_memory, explicit.memory)
        base.permissions = _intersect(avail_permissions, explicit.permissions)

    elif mode == CapabilityMode.ROLE_BASED.value:
        role_profile = None
        if specialization:
            spec = get_specialization(specialization)
            if spec and spec.capabilities is not None:
                role_profile = spec.capabilities
        if role_profile is None and explicit.tools:
            role_profile = explicit
        if role_profile is not None:
            base.tools = _intersect(avail_tools, role_profile.tools)
            base.skills = _intersect(avail_skills, role_profile.skills)
            base.plugins = _intersect(avail_plugins, role_profile.plugins)
            base.mcp_servers = _intersect(avail_mcp, role_profile.mcp_servers)
            base.models = _intersect(avail_models, role_profile.models)
            base.providers = _intersect(avail_providers, role_profile.providers)
            base.memory = _intersect(avail_memory, role_profile.memory)
            base.permissions = _intersect(avail_permissions, role_profile.permissions)
        else:
            # No profile and nothing explicit -> safe read-only minimum.
            base.tools = [t for t in avail_tools if t in ("read", "grep", "search", "web")]

    elif mode == CapabilityMode.RESTRICTED.value:
        # Minimal set. Only explicitly named safe items are honoured.
        allowed = set(explicit.tools) | set(explicit.skills)
        base.tools = [t for t in _intersect(avail_tools, explicit.tools) if t not in RESTRICTED_BY_DEFAULT]
        base.skills = _intersect(avail_skills, explicit.skills)
        base.memory = _intersect(avail_memory, explicit.memory)
        base.permissions = []

    elif mode == CapabilityMode.CUSTOM.value:
        base.tools = _intersect(avail_tools, explicit.tools)
        base.skills = _intersect(avail_skills, explicit.skills)
        base.plugins = _intersect(avail_plugins, explicit.plugins)
        base.mcp_servers = _intersect(avail_mcp, explicit.mcp_servers)
        base.models = _intersect(avail_models, explicit.models)
        base.providers = _intersect(avail_providers, explicit.providers)
        base.memory = _intersect(avail_memory, explicit.memory)
        base.permissions = _intersect(avail_permissions, explicit.permissions)

    # Merge explicit extra overrides on top of the mode base.
    if explicit.tools:
        base.tools = _dedupe(base.tools + _intersect(avail_tools, explicit.tools))
    if explicit.skills:
        base.skills = _dedupe(base.skills + _intersect(avail_skills, explicit.skills))
    if explicit.plugins:
        base.plugins = _dedupe(base.plugins + _intersect(avail_plugins, explicit.plugins))
    if explicit.mcp_servers:
        base.mcp_servers = _dedupe(base.mcp_servers + _intersect(avail_mcp, explicit.mcp_servers))
    if explicit.models:
        base.models = _dedupe(base.models + _intersect(avail_models, explicit.models))
    if explicit.providers:
        base.providers = _dedupe(base.providers + _intersect(avail_providers, explicit.providers))
    if explicit.memory:
        base.memory = _dedupe(base.memory + _intersect(avail_memory, explicit.memory))
    if explicit.permissions:
        base.permissions = _dedupe(base.permissions + _intersect(avail_permissions, explicit.permissions))

    # Sub-agent inheritance ceiling: never broader than the parent.
    if parent_capabilities is not None:
        base.tools = [t for t in base.tools if t in (parent_capabilities.tools or [])] or base.tools
        base.skills = [s for s in base.skills if s in (parent_capabilities.skills or [])] or base.skills
        base.plugins = [p for p in base.plugins if p in (parent_capabilities.plugins or [])] or base.plugins
        base.mcp_servers = [m for m in base.mcp_servers if m in (parent_capabilities.mcp_servers or [])] or base.mcp_servers

    # Remove explicitly dropped capabilities.
    if explicit.remove_inherited:
        drop = set(explicit.remove_inherited)
        base.tools = [t for t in base.tools if t not in drop]
        base.skills = [s for s in base.skills if s not in drop]
        base.plugins = [p for p in base.plugins if p not in drop]
        base.mcp_servers = [m for m in base.mcp_servers if m not in drop]
        base.models = [m for m in base.models if m not in drop]
        base.providers = [p for p in base.providers if p not in drop]
        base.permissions = [p for p in base.permissions if p not in drop]

    # Final escalation guard: strip any restricted capability that was not
    # explicitly present in the *original available* set for a safe category.
    base.tools = _dedupe([t for t in base.tools if t in avail_tools])
    base.skills = _dedupe([s for s in base.skills if s in avail_skills])
    base.plugins = _dedupe([p for p in base.plugins if p in avail_plugins])
    base.mcp_servers = _dedupe([m for m in base.mcp_servers if m in avail_mcp])
    base.models = _dedupe([m for m in base.models if m in avail_models])
    base.providers = _dedupe([p for p in base.providers if p in avail_providers])
    base.memory = _dedupe([m for m in base.memory if m in avail_memory])
    base.permissions = _dedupe([p for p in base.permissions if p in avail_permissions])

    if explicit.sandbox is not None:
        base.sandbox = explicit.sandbox
    if explicit.workspace is not None:
        base.workspace = explicit.workspace
    if explicit.overrides:
        base.overrides = dict(explicit.overrides)

    base.mode = mode
    return base


def assert_no_escalation(
    resolved: CapabilitySpec,
    security_limits: Optional[List[str]] = None,
) -> None:
    """Raise :class:`CapabilityError` if ``resolved`` violates a hard limit."""
    limits = set(security_limits or set())
    forbidden = (
        set(resolved.tools) | set(resolved.skills) | set(resolved.plugins)
        | set(resolved.mcp_servers) | set(resolved.providers)
        | set(resolved.permissions)
    ) & limits
    if forbidden:
        raise CapabilityError(
            "Hive agent capability assignment violates security limits: "
            + ", ".join(sorted(forbidden))
        )
