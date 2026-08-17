"""Tests for the Hive capability boundary, team builder, capabilities resolver,
and specialization library.  These exercise the NEW architectural pieces on top
of the real NexusHiveEngine with injected (fake) async LLMs — no network.
"""

import asyncio

import pytest

from hive import (
    HiveCapability,
    HiveRequest,
    TeamBuilder,
    resolve,
    assert_no_escalation,
    CapabilityError,
    get_specialization,
    list_team_templates,
    clone_team_template,
    get_team_template,
    import_team_templates,
    AgentTeamSpec,
    HiveAgentSpec,
    CapabilitySpec,
    CapabilityMode,
    TaskState,
    can_transition_task,
)
from hive.capabilities import RESTRICTED_BY_DEFAULT
from hive.models import BudgetSpec, ConnectionMode


AVAILABLE = {
    "tools": ["read", "write", "edit", "terminal", "grep", "search", "web", "test", "planning", "todo"],
    "skills": ["coding", "testing", "research", "security", "documentation"],
    "plugins": ["demo_plugin"],
    "mcp_servers": ["fs"],
    "models": ["gpt-4o", "llama-3"],
    "providers": ["lm_studio", "cloud"],
    "memory": ["short_term", "long_term"],
    "permissions": ["file_read", "file_write", "shell", "network"],
}


async def fake_llm(messages):
    # Deterministic stub: echo the last user task + a FINAL ANSWER marker.
    last = messages[-1]["content"]
    return f"FINAL ANSWER: done with: {last[:40]}"


@pytest.mark.asyncio
async def test_hive_request_requires_goal():
    with pytest.raises(ValueError):
        HiveRequest(goal="")


@pytest.mark.asyncio
async def test_resolve_full_mode_does_not_escalate():
    caps = resolve(CapabilityMode.FULL.value, AVAILABLE)
    # write/terminal/edit are restricted-by-default and must NOT be granted.
    assert "write" not in caps.tools
    assert "terminal" not in caps.tools
    assert "read" in caps.tools


@pytest.mark.asyncio
async def test_resolve_role_based_uses_specialization():
    caps = resolve(CapabilityMode.ROLE_BASED.value, AVAILABLE, specialization="BACKEND_AGENT")
    assert "write" in caps.tools
    assert "terminal" in caps.tools
    assert "coding" in caps.skills


@pytest.mark.asyncio
async def test_resolve_selected_only_explicit():
    caps = resolve(CapabilityMode.SELECTED.value, AVAILABLE,
                   explicit=CapabilitySpec(tools=["read", "grep"], skills=["research"]))
    assert set(caps.tools) == {"read", "grep"}
    assert caps.skills == ["research"]


@pytest.mark.asyncio
async def test_resolve_rejects_unavailable_capability():
    caps = resolve(CapabilityMode.SELECTED.value, AVAILABLE,
                   explicit=CapabilitySpec(tools=["nonexistent_tool"]))
    assert caps.tools == []


@pytest.mark.asyncio
async def test_resolve_security_limit_blocks_escalation():
    caps = resolve(CapabilityMode.FULL.value, AVAILABLE)
    with pytest.raises(CapabilityError):
        assert_no_escalation(caps, security_limits=["read"])


@pytest.mark.asyncio
async def test_specialization_registry_extensible():
    before = len(__import__("hive", fromlist=["specialization_keys"]).specialization_keys())
    from hive import register_specialization, Specialization
    register_specialization(Specialization("MY_CUSTOM_AGENT", "My Custom Agent",
                                capabilities=CapabilitySpec(tools=["read"])))
    from hive import specialization_keys
    assert "MY_CUSTOM_AGENT" in specialization_keys()
    assert len(specialization_keys()) == before + 1


@pytest.mark.asyncio
async def test_team_builder_builtin_templates():
    templates = list_team_templates()
    names = {t.name for t in templates}
    assert "Software Development Agent Team" in names
    assert "Research Agent Team" in names
    assert "Security Audit Agent Team" in names


@pytest.mark.asyncio
async def test_team_builder_plan_mixed():
    # Synthesized team: PLANNER (seq) + [BACKEND, TESTER] (parallel) + REVIEWER (seq).
    req = HiveRequest(goal="Build a feature", required_specializations=["BACKEND_AGENT", "TESTER"])
    team = TeamBuilder(AVAILABLE).build(req)
    plan = TeamBuilder(AVAILABLE).plan(team)
    assert plan[0].kind == "sequential"          # planner
    assert plan[1].kind == "parallel"            # backend + tester
    assert plan[2].kind == "sequential"          # reviewer
    parallel_specs = {a.specialization for a in plan[1].agents}
    assert parallel_specs == {"BACKEND_AGENT", "TESTER"}

    # The Software Development template must also contain a parallel stage.
    tmpl = next(t for t in list_team_templates() if t.name == "Software Development Agent Team")
    assert any(s.kind == "parallel" for s in TeamBuilder(AVAILABLE).plan(tmpl))


@pytest.mark.asyncio
async def test_team_builder_from_request_required_specs():
    req = HiveRequest(goal="Build a feature", required_specializations=["BACKEND_AGENT", "TESTER"])
    team = TeamBuilder(AVAILABLE).build(req)
    assert team.workflow == "mixed"
    # Planner (sequential) + 2 parallel agents + reviewer (sequential).
    specs = [a.specialization for a in team.agents]
    assert "PLANNER" in specs
    assert "REVIEWER" in specs


@pytest.mark.asyncio
async def test_team_clone_and_export_import():
    clone = clone_team_template("research", new_name="Research Clone")
    assert clone.name == "Research Clone"
    assert clone.team_id != get_team_template("research").team_id
    exported = [clone.to_dict()]
    from hive import import_team_templates
    # importing the same id again should not crash and should be idempotent-ish.
    n = import_team_templates(exported)
    assert n == 1


@pytest.mark.asyncio
async def test_task_state_transitions():
    assert can_transition_task(TaskState.PENDING.value, TaskState.RUNNING.value)
    assert not can_transition_task(TaskState.COMPLETED.value, TaskState.RUNNING.value)
    assert can_transition_task(TaskState.RUNNING.value, TaskState.COMPLETED.value)
    assert not can_transition_task(TaskState.DRAFT.value, TaskState.COMPLETED.value)


@pytest.mark.asyncio
async def test_hive_capability_submit_and_execute(tmp_path):
    cap = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=fake_llm)
    req = HiveRequest(
        goal="Write a tiny module and test it",
        required_specializations=["BACKEND_AGENT", "TESTER"],
        capability_mode=CapabilityMode.ROLE_BASED.value,
    )
    summary = await cap.submit_goal(req)
    assert summary.status == "planned"
    assert len(summary.created_agents) >= 3
    assert summary.selected_team_id

    await cap.execute_run(summary.hive_run_id)
    run = await cap.get_run(summary.hive_run_id)
    assert run.status == "completed"
    assert run.final_result and "FINAL ANSWER" in run.final_result
    assert run.verification_result["agents"] >= 3
    # Each agent must have resolved capabilities attached (role-based).
    team = cap.get_agent_team(run.selected_team_id)
    for agent in team.agents:
        assert agent.capabilities is not None
        assert agent.tools  # BACKEND/TESTER got real tools from the resolver


@pytest.mark.asyncio
async def test_hive_capability_pause_resume_cancel(tmp_path):
    cap = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=fake_llm)
    req = HiveRequest(goal="Research topic X", required_specializations=["RESEARCHER"])
    summary = await cap.submit_goal(req)
    await cap.pause(summary.hive_run_id)
    run = await cap.get_run(summary.hive_run_id)
    assert run.status == "paused"
    await cap.resume(summary.hive_run_id)
    run = await cap.get_run(summary.hive_run_id)
    assert run.status == "running"
    await cap.cancel(summary.hive_run_id)
    run = await cap.get_run(summary.hive_run_id)
    assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_hive_capability_failure_isolation(tmp_path):
    # The tester's task text contains "TEST-TASK" so the flaky LLM can target it.
    async def flaky_llm(messages):
        if "TEST-TASK" in messages[-1]["content"]:
            raise RuntimeError("tester exploded")
        return "FINAL ANSWER: ok"

    cap = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=flaky_llm)
    req = HiveRequest(goal="Do work", required_specializations=["BACKEND_AGENT", "TESTER"])
    # Force the tester's task to carry the marker the flaky LLM looks for.
    summary = await cap.submit_goal(req)
    team = cap.get_agent_team(summary.selected_team_id)
    for agent in team.agents:
        if agent.specialization == "TESTER":
            agent.goal = "TEST-TASK: run the test suite"
    await cap.execute_run(summary.hive_run_id)
    run = await cap.get_run(summary.hive_run_id)
    # The run itself finished (did not crash) even though one agent failed.
    assert run.status in ("completed", "failed")
    assert any(e.code == "hive.agent_failed" for e in run.errors)


@pytest.mark.asyncio
async def test_hive_persistence_recovery(tmp_path):
    cap = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=fake_llm)
    req = HiveRequest(goal="Persisted goal", required_specializations=["RESEARCHER"])
    summary = await cap.submit_goal(req)
    # Simulate a restart: build a new capability over the same root.
    cap2 = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=fake_llm)
    recovered = await cap2.recover_interrupted(summary.hive_run_id)
    assert recovered.hive_run_id == summary.hive_run_id
    # A run that was only submitted (planned) and never started is not
    # "interrupted"; it is simply reloaded. Both states are valid.
    assert recovered.status in ("planned", "interrupted")

    # A run persisted as running must be marked interrupted after recovery.
    from hive import HiveRunStatus
    summary.status = HiveRunStatus.RUNNING.value
    cap._persistence.save_run(summary, cap.get_agent_team(summary.selected_team_id))
    cap3 = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=fake_llm)
    recovered2 = await cap3.recover_interrupted(summary.hive_run_id)
    assert recovered2.status == "interrupted"


@pytest.mark.asyncio
async def test_hive_continuous_loop_respects_iteration_limit(tmp_path):
    from hive import LoopPolicy
    cap = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=fake_llm)
    req = HiveRequest(
        goal="Continuous maintenance",
        required_specializations=["BACKEND_AGENT"],
        allow_continuous=True,
        loop_policy=LoopPolicy(max_iterations=2, max_failures=5, no_progress_threshold_seconds=9999),
    )
    summary = await cap.submit_goal(req)
    result = await cap.run_continuous(summary.hive_run_id)
    assert result.budget_usage.get("iterations") == 2
    assert "max_iterations" in result.budget_usage.get("limits_hit", [])
    assert result.status == "completed"
    # Each iteration replays the plan (planner + backend + reviewer = 3 agents);
    # _agents_by_run holds the most recent iteration's agents.
    agents = cap._agents_by_run.get(summary.hive_run_id, [])
    assert len(agents) >= 3


@pytest.mark.asyncio
async def test_hive_continuous_loop_stops_on_cancel(tmp_path):
    from hive import LoopPolicy
    cap = HiveCapability(str(tmp_path), available_capabilities=AVAILABLE, llm_call=fake_llm)
    req = HiveRequest(
        goal="Long job",
        required_specializations=["RESEARCHER"],
        allow_continuous=True,
        loop_policy=LoopPolicy(max_iterations=100, max_failures=50, no_progress_threshold_seconds=9999),
    )
    summary = await cap.submit_goal(req)
    # Drive the loop in the background, then cancel it.
    import asyncio
    loop_task = asyncio.ensure_future(cap.run_continuous(summary.hive_run_id))
    await asyncio.sleep(0.2)
    await cap.cancel(summary.hive_run_id)
    result = await loop_task
    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_team_builder_trims_to_max_agents():
    from hive import TeamBuilder, HiveRequest
    req = HiveRequest(
        goal="Build everything",
        required_specializations=["BACKEND_AGENT", "FRONTEND_AGENT", "TESTER", "SECURITY_AUDITOR"],
        max_agents=3,
    )
    team = TeamBuilder(AVAILABLE).build(req)
    # planner + reviewer + <=1 parallel => trimmed to 3 total
    assert len(team.agents) == 3


@pytest.mark.asyncio
async def test_team_builder_rejects_escalation():
    from hive import TeamBuilder, HiveRequest, HiveAgentSpec, CapabilitySpec, CapabilityMode
    # Request an agent with a capability the main agent does NOT expose.
    escalated = HiveAgentSpec(
        specialization="BACKEND_AGENT",
        capabilities=CapabilitySpec(mode=CapabilityMode.SELECTED.value, tools=["supersecret_tool"]),
    )
    req = HiveRequest(goal="g", agent_team=__import__("hive.models", fromlist=["AgentTeamSpec"]).AgentTeamSpec(
        name="X", agents=[escalated]))
    with pytest.raises(ValueError):
        TeamBuilder(AVAILABLE).build(req)
