"""Unit tests for the Hive capabilities resolver and specialization library."""

import pytest

from hive import (
    resolve,
    assert_no_escalation,
    CapabilityError,
    CapabilitySpec,
    CapabilityMode,
    ConnectionMode,
    get_specialization,
    register_specialization,
    list_specializations,
    Specialization,
)


AVAIL = {
    "tools": ["read", "write", "edit", "terminal", "grep", "search", "web", "test"],
    "skills": ["coding", "testing", "research", "security"],
    "plugins": ["p1"],
    "mcp_servers": ["fs", "git"],
    "models": ["m1", "m2"],
    "providers": ["lm_studio", "cloud"],
    "memory": ["short_term"],
    "permissions": ["file_read", "shell"],
}


def test_restricted_by_default_set_exists():
    assert "terminal" in __import__("hive.capabilities", fromlist=["RESTRICTED_BY_DEFAULT"]).RESTRICTED_BY_DEFAULT
    assert "write" in __import__("hive.capabilities", fromlist=["RESTRICTED_BY_DEFAULT"]).RESTRICTED_BY_DEFAULT


def test_full_mode_excludes_restricted_tools():
    caps = resolve("full", AVAIL)
    assert "write" not in caps.tools
    assert "terminal" not in caps.tools
    assert "read" in caps.tools


def test_full_mode_includes_safe_tools_and_skills():
    caps = resolve("full", AVAIL)
    assert "coding" in caps.skills
    assert "fs" in caps.mcp_servers
    assert "m1" in caps.models


def test_role_based_inherits_specialization_profile():
    caps = resolve("role_based", AVAIL, specialization="BACKEND_AGENT")
    assert "write" in caps.tools
    assert "terminal" in caps.tools
    assert "coding" in caps.skills


def test_selected_mode_only_explicit():
    caps = resolve("selected", AVAIL, explicit=CapabilitySpec(tools=["read", "grep"], skills=["research"]))
    assert set(caps.tools) == {"read", "grep"}
    assert caps.skills == ["research"]


def test_custom_mode_uses_explicit_lists():
    caps = resolve("custom", AVAIL, explicit=CapabilitySpec(tools=["read", "write"], skills=["coding"]))
    assert set(caps.tools) == {"read", "write"}
    assert caps.skills == ["coding"]


def test_restricted_mode_minimal():
    caps = resolve("restricted", AVAIL, explicit=CapabilitySpec(tools=["read"]))
    assert caps.tools == ["read"]
    assert caps.permissions == []


def test_unknown_mode_falls_back_to_role_based():
    caps = resolve("bogus_mode", AVAIL)
    assert caps.mode == CapabilityMode.ROLE_BASED.value


def test_resolver_strips_unavailable_capabilities():
    caps = resolve("selected", AVAIL, explicit=CapabilitySpec(tools=["read", "does_not_exist"]))
    assert "does_not_exist" not in caps.tools
    assert "read" in caps.tools


def test_subagent_ceiling_never_broader_than_parent():
    parent = CapabilitySpec(tools=["read", "grep"], skills=["coding"])
    child = resolve("selected", AVAIL,
                    explicit=CapabilitySpec(tools=["read", "write", "terminal"]),
                    parent_capabilities=parent)
    # Child may ask for write/terminal but may only receive what the parent has.
    assert "write" not in child.tools
    assert "terminal" not in child.tools
    assert "read" in child.tools


def test_remove_inherited_strips_capabilities():
    caps = resolve("role_based", AVAIL, specialization="BACKEND_AGENT",
                   explicit=CapabilitySpec(remove_inherited=["terminal"]))
    assert "terminal" not in caps.tools
    assert "write" in caps.tools


def test_escalation_guard_raises_on_security_limit():
    with pytest.raises(CapabilityError):
        caps = resolve("full", AVAIL)
        assert_no_escalation(caps, security_limits=["read"])


def test_specialization_registry_has_core_entries():
    assert get_specialization("ENGINEER") is not None
    assert get_specialization("RESEARCHER") is not None
    assert get_specialization("SECURITY_AUDITOR") is not None
    assert get_specialization("BACKEND_AGENT") is not None


def test_specialization_to_from_dict_roundtrip():
    spec = get_specialization("BACKEND_AGENT")
    data = spec.to_dict()
    restored = Specialization.from_dict(data)
    assert restored.key == spec.key
    assert restored.capabilities.tools == spec.capabilities.tools


def test_register_and_list_custom_specialization():
    register_specialization(Specialization(
        "PIPELINE_WATCHER", "Pipeline Watcher",
        capabilities=CapabilitySpec(tools=["read", "terminal"], skills=["devops"]),
        tags=["devops"],
    ))
    spec = get_specialization("PIPELINE_WATCHER")
    assert spec is not None
    assert spec.tags == ["devops"]
    listed = list_specializations(tag="devops")
    assert any(s.key == "PIPELINE_WATCHER" for s in listed)
