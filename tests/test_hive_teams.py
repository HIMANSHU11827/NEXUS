"""Tests for the Agent Team system: registry, builder, plan generation, and
plug-and-play team management."""

import pytest

from hive import (
    AgentTeamSpec,
    HiveAgentSpec,
    HiveRequest,
    TeamBuilder,
    list_team_templates,
    get_team_template,
    clone_team_template,
    register_team_template,
    delete_team_template,
    export_team_templates,
    import_team_templates,
    CapabilityMode,
)

AVAIL = {
    "tools": ["read", "write", "edit", "terminal", "grep", "search", "web", "test"],
    "skills": ["coding", "testing", "research", "security"],
    "plugins": [], "mcp_servers": [], "models": [], "providers": ["lm_studio"],
    "memory": ["short_term"], "permissions": ["file_read"],
}


def test_builtin_templates_present():
    names = {t.name for t in list_team_templates()}
    assert "Software Development Agent Team" in names
    assert "Research Agent Team" in names
    assert "Security Audit Agent Team" in names
    assert "Documentation Agent Team" in names
    assert "Incident Response Agent Team" in names
    assert "Continuous Maintenance Agent Team" in names
    assert "Deployment Agent Team" in names
    assert "UI Redesign Agent Team" in names


def test_get_team_template_by_name_and_id():
    assert get_team_template("research") is not None
    by_name = get_team_template("Research Agent Team")
    assert by_name is not None
    # Registry is keyed by template id ("research"); name lookups also resolve.
    assert get_team_template("research") is by_name


def test_clone_team_template_new_identity():
    clone = clone_team_template("research", new_name="Research (staging)")
    assert clone.team_id != get_team_template("research").team_id
    assert clone.name == "Research (staging)"


def test_register_and_delete_custom_team():
    team = AgentTeamSpec(name="Custom QA Team",
                         agents=[HiveAgentSpec(specialization="TESTER", category="parallel", goal="test")])
    register_team_template(team)
    assert get_team_template(team.team_id) is not None
    assert delete_team_template(team.team_id) is True
    assert get_team_template(team.team_id) is None


def test_export_import_team_templates():
    exported = export_team_templates()
    assert isinstance(exported, list) and exported
    before = len(list_team_templates())
    extra = AgentTeamSpec(name="Imported Team",
                          agents=[HiveAgentSpec(specialization="ENGINEER")])
    n = import_team_templates([extra.to_dict()])
    assert n == 1
    assert len(list_team_templates()) == before + 1


def test_builder_uses_named_template():
    builder = TeamBuilder(AVAIL)
    req = HiveRequest(goal="Audit the repo", team_preference="security_audit")
    team = builder.build(req)
    assert team.name == "Security Audit Agent Team"
    assert any(a.specialization == "SECURITY_AUDITOR" for a in team.agents)


def test_builder_synthesizes_team_from_specializations():
    builder = TeamBuilder(AVAIL)
    req = HiveRequest(goal="Build X", required_specializations=["BACKEND_AGENT", "FRONTEND_AGENT"])
    team = builder.build(req)
    specs = [a.specialization for a in team.agents]
    assert "PLANNER" in specs
    assert "BACKEND_AGENT" in specs
    assert "FRONTEND_AGENT" in specs
    assert "REVIEWER" in specs
    # Planner + 2 parallel + reviewer.
    plan = builder.plan(team)
    assert plan[0].kind == "sequential"          # planner
    assert plan[1].kind == "parallel"            # backend+frontend
    assert plan[2].kind == "sequential"          # reviewer


def test_builder_honors_agent_team_in_request():
    req_team = AgentTeamSpec(name="Inline Team",
                             agents=[HiveAgentSpec(specialization="RESEARCHER", category="sequential", goal="r")])
    req = HiveRequest(goal="G", agent_team=req_team)
    team = TeamBuilder(AVAIL).build(req)
    assert team.name == "Inline Team"


def test_plan_mixed_from_software_team():
    tmpl = get_team_template("software_development")
    plan = TeamBuilder(AVAIL).plan(tmpl)
    kinds = [s.kind for s in plan]
    # sequential (planner), sequential (architect), parallel (backend/frontend/db), ...
    assert kinds[0] == "sequential"
    assert kinds.count("sequential") == 5
    # Exactly one parallel stage, and it contains the backend/frontend/database trio.
    parallel_stages = [s for s in plan if s.kind == "parallel"]
    assert len(parallel_stages) == 1
    parallel_specs = {a.specialization for a in parallel_stages[0].agents}
    assert {"BACKEND_AGENT", "FRONTEND_AGENT", "DATABASE_AGENT"}.issubset(parallel_specs)


def test_continuous_team_gets_loop_policy():
    builder = TeamBuilder(AVAIL)
    req = HiveRequest(goal="Maintain repo", allow_continuous=True,
                      required_specializations=["MONITORING_AGENT"])
    team = builder.build(req)
    assert team.continuous is True
    assert team.loop_policy is not None
    assert team.loop_policy.max_failures == 3
