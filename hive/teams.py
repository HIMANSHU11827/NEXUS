"""Agent Team system for Nexus Hive (§9, §16, §18).

An **Agent Team** is a reusable group of Hive agents working toward one shared
goal.  Internally a team is expressed as an ordered list of *stages*: each
stage is either a single agent (sequential) or a parallel group of agents.
Stages run in order; within a parallel stage every agent runs concurrently.
This single representation covers single / parallel / sequential / mixed /
pipeline execution.

This module provides:

* A plug-and-play registry of team *templates* (register / list / get / clone
  / export / import / delete).
* A set of built-in reusable templates (software-dev, research, security-audit,
  docs, incident-response, continuous-maintenance, ...).
* A :class:`TeamBuilder` that turns a :class:`HiveRequest` into a concrete
  :class:`AgentTeamSpec`, honouring ``required_specializations``,
  ``team_preference`` and capability mode.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import (
    AgentTeamSpec,
    CapabilityMode,
    ConnectionMode,
    HiveAgentSpec,
    HiveRequest,
)
from .specializations import get_specialization


# A stage is either {"sequential": [agent, ...]} or {"parallel": [[agent,...], ...]}
@dataclass
class ExecutionStage:
    """One step in a team's execution plan.

    ``kind`` is ``"sequential"`` (one agent, after the previous stage) or
    ``"parallel"`` (several agents at the same time).
    """

    kind: str
    agents: List[HiveAgentSpec] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "agents": [a.to_dict() for a in self.agents],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionStage":
        return cls(
            kind=str(data.get("kind", "sequential")),
            agents=[HiveAgentSpec.from_dict(a) for a in data.get("agents", [])],
        )


# ---------------------------------------------------------------------------
# Built-in team templates
# ---------------------------------------------------------------------------

_GLOBAL_TEAM_SPECS = {
    "software_development": AgentTeamSpec(
        name="Software Development Agent Team",
        goal="Plan, build, test, secure, and document a software change.",
        workflow="mixed",
        agents=[
            HiveAgentSpec(specialization="PLANNER", category="sequential", goal="Plan the implementation."),
            HiveAgentSpec(specialization="ARCHITECT", category="sequential", goal="Design the structure."),
            HiveAgentSpec(specialization="BACKEND_AGENT", category="parallel",
                          goal="Implement backend changes."),
            HiveAgentSpec(specialization="FRONTEND_AGENT", category="parallel",
                          goal="Implement frontend changes."),
            HiveAgentSpec(specialization="DATABASE_AGENT", category="parallel",
                          goal="Implement database/migration changes."),
            HiveAgentSpec(specialization="TESTER", category="sequential", goal="Run tests."),
            HiveAgentSpec(specialization="SECURITY_AUDITOR", category="sequential",
                          goal="Security review."),
            HiveAgentSpec(specialization="REVIEWER", category="sequential",
                          goal="Final review of the change."),
        ],
        completion_criteria=["All tests pass", "Security review clean", "Final review approved"],
    ),
    "research": AgentTeamSpec(
        name="Research Agent Team",
        goal="Research a topic thoroughly and produce a cited synthesis.",
        workflow="mixed",
        agents=[
            HiveAgentSpec(specialization="RESEARCHER", category="parallel",
                          goal="Web and technical research."),
            HiveAgentSpec(specialization="REPO_RESEARCHER", category="parallel",
                          goal="Repository / source research."),
            HiveAgentSpec(specialization="SOURCE_VERIFIER", category="parallel",
                          goal="Verify and fact-check sources."),
            HiveAgentSpec(specialization="RESEARCH_SYNTHESIZER", category="sequential",
                          goal="Synthesize findings into a report."),
            HiveAgentSpec(specialization="CITATION_AGENT", category="sequential",
                          goal="Add citations and finalise."),
        ],
        completion_criteria=["Report produced", "All claims cited"],
    ),
    "security_audit": AgentTeamSpec(
        name="Security Audit Agent Team",
        goal="Audit the project for security weaknesses and produce a remediation plan.",
        workflow="mixed",
        agents=[
            HiveAgentSpec(specialization="SECURITY_AUDITOR", category="sequential",
                          goal="Run the security audit."),
            HiveAgentSpec(specialization="VULNERABILITY_AGENT", category="parallel",
                          goal="Map vulnerabilities."),
            HiveAgentSpec(specialization="SECRET_DETECTOR", category="parallel",
                          goal="Scan for leaked secrets."),
            HiveAgentSpec(specialization="DEPENDENCY_SECURITY", category="parallel",
                          goal="Audit dependencies."),
            HiveAgentSpec(specialization="COMPLIANCE_AGENT", category="sequential",
                          goal="Assess compliance gaps."),
        ],
        completion_criteria=["Findings documented", "Severity assigned", "Remediation plan produced"],
    ),
    "documentation": AgentTeamSpec(
        name="Documentation Agent Team",
        goal="Produce and validate project documentation.",
        workflow="mixed",
        agents=[
            HiveAgentSpec(specialization="DOC_PLANNER", category="sequential",
                          goal="Plan documentation set."),
            HiveAgentSpec(specialization="TECH_WRITER", category="parallel",
                          goal="Write core docs."),
            HiveAgentSpec(specialization="README_AGENT", category="parallel",
                          goal="Write/update README."),
            HiveAgentSpec(specialization="API_DOC_AGENT", category="parallel",
                          goal="Document APIs."),
            HiveAgentSpec(specialization="LINK_VALIDATOR", category="sequential",
                          goal="Validate links and consistency."),
        ],
        completion_criteria=["Docs produced", "Links valid", "Consistency checked"],
    ),
    "incident_response": AgentTeamSpec(
        name="Incident Response Agent Team",
        goal="Triage, diagnose, and remediate an active incident.",
        workflow="mixed",
        agents=[
            HiveAgentSpec(specialization="INCIDENT_AGENT", category="sequential",
                          goal="Triage the incident."),
            HiveAgentSpec(specialization="ROOT_CAUSE", category="parallel",
                          goal="Find root cause."),
            HiveAgentSpec(specialization="MONITORING_AGENT", category="parallel",
                          goal="Gather telemetry."),
            HiveAgentSpec(specialization="RECOVERY_AGENT", category="sequential",
                          goal="Apply remediation."),
            HiveAgentSpec(specialization="ROLLBACK_AGENT", category="sequential",
                          goal="Prepare rollback if needed."),
        ],
        completion_criteria=["Incident contained", "Remediation applied", "Postmortem drafted"],
    ),
    "continuous_maintenance": AgentTeamSpec(
        name="Continuous Maintenance Agent Team",
        goal="Continuously maintain the repository: monitor, fix, test, review.",
        workflow="loop",
        continuous=True,
        loop_policy=None,  # filled by the live runner with sane defaults
        agents=[
            HiveAgentSpec(specialization="MONITORING_AGENT", category="sequential",
                          goal="Detect actionable work."),
            HiveAgentSpec(specialization="BUG_DETECTOR", category="parallel",
                          goal="Find issues."),
            HiveAgentSpec(specialization="REFACTORER", category="parallel",
                          goal="Apply safe improvements."),
            HiveAgentSpec(specialization="TESTER", category="sequential",
                          goal="Run the test suite."),
            HiveAgentSpec(specialization="REVIEWER", category="sequential",
                          goal="Review changes; keep or revert."),
        ],
        completion_criteria=["Tests green", "Review approved", "Or safe revert"],
    ),
    "deployment": AgentTeamSpec(
        name="Deployment Agent Team",
        goal="Build, verify, and deploy a release safely.",
        workflow="mixed",
        agents=[
            HiveAgentSpec(specialization="BUILD_AGENT", category="sequential",
                          goal="Build and package."),
            HiveAgentSpec(specialization="QA_AGENT", category="sequential",
                          goal="Verify the build."),
            HiveAgentSpec(specialization="SECURITY_AUDITOR", category="parallel",
                          goal="Pre-deploy security gate."),
            HiveAgentSpec(specialization="DEPLOYMENT_AGENT", category="sequential",
                          goal="Deploy the release."),
            HiveAgentSpec(specialization="HEALTH_CHECK_AGENT", category="sequential",
                          goal="Confirm post-deploy health."),
        ],
        completion_criteria=["Build green", "Deployed", "Health checks pass"],
    ),
    "ui_redesign": AgentTeamSpec(
        name="UI Redesign Agent Team",
        goal="Redesign a user interface with research, design, and implementation.",
        workflow="mixed",
        agents=[
            HiveAgentSpec(specialization="UX_RESEARCHER" if get_specialization("UX_RESEARCHER") else "RESEARCHER",
                          category="parallel", goal="Research user needs."),
            HiveAgentSpec(specialization="UI_DESIGNER", category="parallel",
                          goal="Produce design."),
            HiveAgentSpec(specialization="FRONTEND_AGENT", category="sequential",
                          goal="Implement the UI."),
            HiveAgentSpec(specialization="ACCESSIBILITY_AGENT", category="parallel",
                          goal="Accessibility pass."),
            HiveAgentSpec(specialization="UI_REVIEWER", category="sequential",
                          goal="Review the result."),
        ],
        completion_criteria=["Design produced", "Implemented", "Reviewed"],
    ),
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_TEMPLATES: Dict[str, AgentTeamSpec] = {k: copy.deepcopy(v) for k, v in _GLOBAL_TEAM_SPECS.items()}


def register_team_template(spec: AgentTeamSpec) -> None:
    _TEMPLATES[spec.team_id if spec.team_id else spec.name] = spec


def get_team_template(key: str) -> Optional[AgentTeamSpec]:
    if key in _TEMPLATES:
        return _TEMPLATES[key]
    for spec in _TEMPLATES.values():
        if spec.name.lower() == str(key).lower():
            return spec
    return None


def list_team_templates() -> List[AgentTeamSpec]:
    return list(_TEMPLATES.values())


def clone_team_template(key: str, new_name: Optional[str] = None) -> AgentTeamSpec:
    src = get_team_template(key)
    if src is None:
        raise KeyError(f"No Agent Team template named {key!r}")
    clone = copy.deepcopy(src)
    clone.team_id = f"team_{uuid.uuid4().hex[:8]}"
    clone.name = new_name or f"{src.name} (clone)"
    clone.version = 1
    return clone


def export_team_templates() -> List[Dict[str, Any]]:
    return [t.to_dict() for t in _TEMPLATES.values()]


def import_team_templates(records: List[Dict[str, Any]]) -> int:
    count = 0
    for rec in records:
        if isinstance(rec, dict):
            spec = AgentTeamSpec.from_dict(rec)
            register_team_template(spec)
            count += 1
    return count


def delete_team_template(key: str) -> bool:
    if key in _TEMPLATES:
        del _TEMPLATES[key]
        return True
    for k, spec in list(_TEMPLATES.items()):
        if spec.name.lower() == str(key).lower():
            del _TEMPLATES[k]
            return True
    return False


# ---------------------------------------------------------------------------
# Builder: HiveRequest -> AgentTeamSpec + ExecutionStage plan
# ---------------------------------------------------------------------------


class TeamBuilder:
    """Turns a :class:`HiveRequest` into a concrete Agent Team + plan."""

    def __init__(self, available_capabilities: Optional[Dict[str, List[str]]] = None):
        self._available = available_capabilities or {}

    def build(self, request: HiveRequest) -> AgentTeamSpec:
        # 1) Selected template, if the main agent named one.
        if request.team_preference:
            tmpl = get_team_template(request.team_preference)
            if tmpl is not None:
                team = copy.deepcopy(tmpl)
                team.goal = request.goal
                if request.goal:
                    team.instructions = request.goal
                self._apply_request_limits(team, request)
                self.validate_limits(team, request)
                return team

        # 2) If the request already carries a concrete team, use it.
        if request.agent_team is not None:
            team = copy.deepcopy(request.agent_team)
            if not team.goal and request.goal:
                team.goal = request.goal
            self._apply_request_limits(team, request)
            self.validate_limits(team, request)
            return team

        # 3) Otherwise synthesise a team from required specializations.
        specs = list(request.required_specializations) or ["ENGINEER"]
        agents: List[HiveAgentSpec] = []
        # First stage: planning (sequential), then parallel work, then review.
        agents.append(HiveAgentSpec(
            specialization="PLANNER", category="sequential",
            goal=f"Plan work for: {request.goal}",
        ))
        for spec_key in specs:
            agents.append(HiveAgentSpec(
                specialization=spec_key, category="parallel",
                goal=request.goal,
            ))
        agents.append(HiveAgentSpec(
            specialization="REVIEWER", category="sequential",
            goal=f"Review the work for: {request.goal}",
        ))

        team = AgentTeamSpec(
            name="Ad-hoc Agent Team",
            goal=request.goal,
            instructions=request.goal,
            agents=agents,
            workflow="mixed",
            continuous=request.allow_continuous,
            completion_criteria=request.completion_criteria or ["Goal achieved"],
        )
        self._apply_request_limits(team, request)
        self.validate_limits(team, request)
        return team

    def _apply_request_limits(self, team: AgentTeamSpec, request: HiveRequest) -> None:
        if request.token_budget or request.cost_budget or request.runtime_budget_seconds \
           or request.max_agents or request.max_parallel_agents:
            from .models import BudgetSpec
            team.budgets = BudgetSpec(
                tokens=request.token_budget,
                cost_usd=request.cost_budget,
                runtime_seconds=request.runtime_budget_seconds,
                max_agents=request.max_agents,
                max_parallel_agents=request.max_parallel_agents,
            )
        if request.allow_continuous and team.loop_policy is None:
            from .models import LoopPolicy
            team.loop_policy = request.loop_policy or LoopPolicy(
                max_iterations=10, max_runtime_seconds=request.runtime_budget_seconds,
                max_failures=3, no_progress_threshold_seconds=300,
                checkpoint_every_iterations=1,
            )
        if request.require_human_approval:
            team.failure_policy = "stop_team"

    def validate_limits(self, team: AgentTeamSpec, request: HiveRequest) -> List[str]:
        """Enforce dynamic-creation safety limits (§20). Returns warnings.

        These guards prevent unbounded agent spawning and silent privilege
        escalation.  Hard limits raise ``ValueError``; soft limits append a
        warning and trim the team to comply.
        """
        warnings: List[str] = []
        # Sub-agent depth: the request can allow agents that themselves create
        # sub-agents.  We cap the *request-declared* depth here; the engine is
        # expected to honour the same ceiling when agents spawn sub-agents.
        max_depth = (team.budgets.max_subagent_depth if team.budgets else None) \
            or request.max_agents  # fall back: depth must not exceed total cap
        if max_depth is not None and max_depth > 4:
            raise ValueError(f"max_subagent_depth {max_depth} exceeds hard cap of 4")

        # Total agent count.
        if request.max_agents is not None:
            if len(team.agents) > request.max_agents:
                # Trim parallel-stage agents first (keep coordinator + planners).
                keep = []
                for a in team.agents:
                    if len(keep) >= request.max_agents:
                        warnings.append(f"trimmed agent {a.specialization} (max_agents={request.max_agents})")
                        continue
                    keep.append(a)
                team.agents = keep

        # Per-team parallel agents.
        if request.max_parallel_agents is not None:
            parallel = [a for a in team.agents if a.category == "parallel"]
            if len(parallel) > request.max_parallel_agents:
                warnings.append(
                    f"parallel agents {len(parallel)} exceed max_parallel_agents="
                    f"{request.max_parallel_agents}; they will be serialised in waves"
                )

        # Privilege-escalation guard: if an agent explicitly requests
        # capabilities (SELECTED / CUSTOM / RESTRICTED with explicit lists), no
        # requested name may lie outside what the main agent exposes or inside
        # an operator security deny-list.  Agents without explicit caps are safe
        # because ``resolve()`` already caps them to ``available``.
        limits = set(request.permission_limits or [])
        for agent in team.agents:
            caps = agent.capabilities
            if caps is None:
                continue
            explicit = caps.tools + caps.skills + caps.plugins + caps.mcp_servers \
                + caps.models + caps.providers + caps.permissions
            if not explicit:
                continue
            for cat, names in (
                ("tools", caps.tools),
                ("skills", caps.skills),
                ("plugins", caps.plugins),
                ("mcp_servers", caps.mcp_servers),
                ("models", caps.models),
                ("providers", caps.providers),
                ("permissions", caps.permissions),
            ):
                allowed = set(self._available.get(cat, [])) - limits
                for name in names:
                    if name not in allowed:
                        raise ValueError(
                            f"agent {agent.specialization} requests '{name}' ({cat}) "
                            f"which is not exposed by the main agent or is denied"
                        )
        return warnings


    @staticmethod
    def plan(team: AgentTeamSpec) -> List[ExecutionStage]:
        """Convert a team's agent list into an ordered execution plan.

        The agent category decides staging: sequential agents each get
        their own stage; consecutive parallel agents are merged into one
        parallel stage.  This yields the mixed DAG described in section 18.
        """
        stages: List[ExecutionStage] = []
        pending_parallel: List[HiveAgentSpec] = []

        def flush_parallel() -> None:
            if pending_parallel:
                # Copy: the stage must own its agent list, because
                # ``pending_parallel.clear()`` would otherwise empty the very
                # list the stage holds a reference to.
                stages.append(ExecutionStage(kind="parallel", agents=list(pending_parallel)))
                pending_parallel.clear()

        for agent in team.agents:
            if agent.category == "parallel":
                pending_parallel.append(agent)
            else:
                flush_parallel()
                stages.append(ExecutionStage(kind="sequential", agents=[agent]))
        flush_parallel()
        return stages
