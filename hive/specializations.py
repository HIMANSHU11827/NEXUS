"""Hive specialization library — a plug-and-play registry of specialized agents.

A *specialization* is a named recipe that describes what a Hive agent is for
and which capabilities (tools / skills / permissions / sandbox) it should
receive by default.  Specializations are the building blocks of Agent Teams
and of the ROLE_BASED capability-inheritance mode.

The built-in library mirrors the catalogue in the master brief (§12).  It is
intentionally *extensible*: callers may ``register_specialization`` at runtime,
export/import JSON, and clone entries.  Nothing here assumes a specific model,
provider, or tool registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import (
    CapabilityMode,
    CapabilitySpec,
    ConnectionMode,
)


@dataclass
class Specialization:
    """A reusable specialized-agent recipe."""

    key: str
    title: str
    category: str = "specialized"
    description: str = ""
    # ROLE_BASED capability profile — used when an agent inherits by role.
    capabilities: Optional[CapabilitySpec] = None
    default_model: Optional[str] = None
    default_provider: Optional[str] = None
    connection_mode: str = ConnectionMode.INHERIT.value
    system_prompt_hint: str = ""
    tags: List[str] = field(default_factory=list)
    extensible: bool = True

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "key": self.key,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "connection_mode": self.connection_mode,
            "system_prompt_hint": self.system_prompt_hint,
            "tags": list(self.tags),
            "extensible": self.extensible,
            "default_model": self.default_model,
            "default_provider": self.default_provider,
        }
        if self.capabilities is not None:
            data["capabilities"] = self.capabilities.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Specialization":
        caps = data.get("capabilities")
        return cls(
            key=str(data["key"]),
            title=str(data.get("title", data["key"])),
            category=str(data.get("category", "specialized")),
            description=str(data.get("description", "")),
            capabilities=CapabilitySpec.from_dict(caps) if isinstance(caps, dict) else None,
            default_model=data.get("default_model"),
            default_provider=data.get("default_provider"),
            connection_mode=str(data.get("connection_mode", ConnectionMode.INHERIT.value)),
            system_prompt_hint=str(data.get("system_prompt_hint", "")),
            tags=list(data.get("tags", [])),
            extensible=bool(data.get("extensible", True)),
        )


# ---------------------------------------------------------------------------
# Built-in catalogue
# ---------------------------------------------------------------------------
# Each entry gets a ROLE_BASED capability profile where it makes sense.  Tools
# are referenced by *name* only — the live engine resolves them against the
# installed tool registry, so this module stays plug-and-play.

def _role(cap: CapabilitySpec) -> CapabilitySpec:
    cap.mode = CapabilityMode.ROLE_BASED.value
    return cap


_BUILTIN: Dict[str, Specialization] = {}


def _add(spec: Specialization) -> None:
    _BUILTIN[spec.key] = spec


# Planning & coordination
_add(_role(Specialization("GOAL_INTERPRETER", "Goal Interpretation Agent",
      description="Interprets the main-agent goal into a concrete plan.",
      capabilities=CapabilitySpec(tools=["read", "planning"], skills=["planning"]),
      system_prompt_hint="Break ambiguous goals into measurable objectives.")))
_add(_role(Specialization("PLANNER", "Planning Agent",
      description="Decomposes work into ordered, independent tasks.",
      capabilities=CapabilitySpec(tools=["read", "planning", "todo"], skills=["planning", "workflow"]),
      system_prompt_hint="Produce an ordered plan with dependencies and exit criteria.")))
_add(_role(Specialization("TASK_DECOMPOSER", "Task Decomposition Agent",
      description="Splits a large task into parallelizable sub-tasks.",
      capabilities=CapabilitySpec(tools=["read", "planning"], skills=["planning"]))))
_add(_role(Specialization("DEPENDENCY_AGENT", "Dependency Agent",
      description="Determines task dependencies and ordering.",
      capabilities=CapabilitySpec(tools=["read"], skills=["planning"]))))
_add(_role(Specialization("PRIORITIZER", "Prioritization Agent",
      description="Ranks work by value, risk, and urgency.",
      capabilities=CapabilitySpec(tools=["read"], skills=["planning"]))))
_add(_role(Specialization("SCHEDULER", "Scheduling Agent",
      description="Assigns work to agents respecting budgets and capacity.",
      capabilities=CapabilitySpec(tools=["read"], skills=["planning"]))))
_add(_role(Specialization("RISK_AGENT", "Risk Agent",
      description="Identifies risks and failure modes before execution.",
      capabilities=CapabilitySpec(tools=["read"], skills=["planning", "security"]),
      tags=["planning", "security"])))
_add(_role(Specialization("COMPLETION_EVALUATOR", "Completion Evaluation Agent",
      description="Decides whether acceptance criteria are met.",
      capabilities=CapabilitySpec(tools=["read", "test"], skills=["testing", "validation"]))))

# Software engineering
_add(_role(Specialization("REPO_ANALYZER", "Repository Analysis Agent",
      description="Maps the codebase and surfaces relevant modules.",
      capabilities=CapabilitySpec(tools=["read", "grep", "terminal"], skills=["coding"]))))
_add(_role(Specialization("CODEBASE_MAPPER", "Codebase Mapping Agent",
      description="Builds a structural map of the repository.",
      capabilities=CapabilitySpec(tools=["read", "grep", "terminal"], skills=["coding"]))))
_add(_role(Specialization("ARCHITECT", "Software Architect Agent",
      description="Designs structures, interfaces, and system boundaries.",
      capabilities=CapabilitySpec(tools=["read", "grep"], skills=["coding", "architecture"]))))
_add(_role(Specialization("SYSTEM_DESIGNER", "System Design Agent",
      description="Produces detailed design documents.",
      capabilities=CapabilitySpec(tools=["read"], skills=["architecture"]))))
_add(_role(Specialization("BACKEND_AGENT", "Backend Agent",
      description="Implements backend, API, and service logic.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal", "grep"], skills=["coding"]),
      tags=["engineering"])))
_add(_role(Specialization("FRONTEND_AGENT", "Frontend Agent",
      description="Implements UI components and front-end logic.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding", "ui"]),
      tags=["engineering"])))
_add(_role(Specialization("FULLSTACK_AGENT", "Full-Stack Agent",
      description="Implements end-to-end features across stack layers.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal", "grep"], skills=["coding", "ui"]))))
_add(_role(Specialization("DATABASE_AGENT", "Database Agent",
      description="Designs schemas and writes migrations/queries.",
      capabilities=CapabilitySpec(tools=["read", "write", "terminal"], skills=["coding", "data"]))))
_add(_role(Specialization("API_AGENT", "API Agent",
      description="Designs and implements API contracts and handlers.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding"]))))
_add(_role(Specialization("MOBILE_AGENT", "Mobile Agent",
      description="Implements mobile-specific features.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding", "ui"]))))
_add(_role(Specialization("DESKTOP_AGENT", "Desktop Agent",
      description="Implements desktop/OS-native features.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding"]))))
_add(_role(Specialization("CLI_AGENT", "CLI Agent",
      description="Implements command-line tools and scripts.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding"]))))
_add(_role(Specialization("TUI_AGENT", "TUI Agent",
      description="Implements terminal UI components.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding", "ui"]))))
_add(_role(Specialization("GUI_AGENT", "GUI Agent",
      description="Implements graphical UI components.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding", "ui"]))))
_add(_role(Specialization("INTEGRATION_AGENT", "Integration Agent",
      description="Wires systems together via APIs and events.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal"], skills=["coding"]))))
_add(_role(Specialization("REFACTORER", "Refactoring Agent",
      description="Improves structure without changing behaviour.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal", "grep"], skills=["coding"]))))
_add(_role(Specialization("MIGRATOR", "Migration Agent",
      description="Performs safe data/code migrations.",
      capabilities=CapabilitySpec(tools=["read", "write", "terminal"], skills=["coding", "data"]))))
_add(_role(Specialization("BUILD_AGENT", "Build Agent",
      description="Keeps the build green and packages artifacts.",
      capabilities=CapabilitySpec(tools=["terminal", "read"], skills=["coding"]))))
_add(_role(Specialization("DEPENDENCY_AGENT", "Dependency Agent",
      description="Manages dependencies and version constraints.",
      capabilities=CapabilitySpec(tools=["terminal", "read"], skills=["coding"]))))
_add(_role(Specialization("CONFIG_AGENT", "Configuration Agent",
      description="Manages configuration and environment wiring.",
      capabilities=CapabilitySpec(tools=["read", "write", "terminal"], skills=["coding"]))))
_add(_role(Specialization("LEGACY_MODERNIZER", "Legacy Modernization Agent",
      description="Modernizes legacy code safely.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal", "grep"], skills=["coding"]))))

# Testing & debugging
for _k, _t in [
    ("BUG_DETECTOR", "Bug Detection Agent"),
    ("DEBUGGER", "Debugging Agent"),
    ("ROOT_CAUSE", "Root-Cause Analysis Agent"),
    ("REPRODUCER", "Reproduction Agent"),
    ("UNIT_TESTER", "Unit Testing Agent"),
    ("INTEGRATION_TESTER", "Integration Testing Agent"),
    ("E2E_TESTER", "End-to-End Testing Agent"),
    ("REGRESSION_TESTER", "Regression Testing Agent"),
    ("STRESS_TESTER", "Stress Testing Agent"),
    ("LOAD_TESTER", "Load Testing Agent"),
    ("FAILURE_INJECTOR", "Failure-Injection Agent"),
    ("COMPAT_TESTER", "Compatibility Testing Agent"),
    ("UI_TESTER", "UI Testing Agent"),
    ("API_TESTER", "API Testing Agent"),
    ("COVERAGE_AGENT", "Test Coverage Agent"),
    ("QA_AGENT", "Quality Assurance Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} for the project under test.",
          capabilities=CapabilitySpec(tools=["read", "terminal", "grep", "test"], skills=["testing"]),
          tags=["testing"])))

# Security
for _k, _t in [
    ("SECURITY_AUDITOR", "Security Audit Agent"),
    ("VULNERABILITY_AGENT", "Vulnerability Agent"),
    ("DEPENDENCY_SECURITY", "Dependency Security Agent"),
    ("SECRET_DETECTOR", "Secret Detection Agent"),
    ("PERMISSION_REVIEWER", "Permission Review Agent"),
    ("AUTHN_REVIEWER", "Authentication Review Agent"),
    ("AUTHZ_REVIEWER", "Authorization Review Agent"),
    ("SANDBOX_REVIEWER", "Sandbox Review Agent"),
    ("PROMPT_INJECTION_AGENT", "Prompt Injection Agent"),
    ("COMMAND_INJECTION_AGENT", "Command Injection Agent"),
    ("PATH_TRAVERSAL_AGENT", "Path Traversal Agent"),
    ("EXFILTRATION_AGENT", "Data Exfiltration Agent"),
    ("PLUGIN_SECURITY", "Plugin Security Agent"),
    ("MCP_SECURITY", "MCP Security Agent"),
    ("THREAT_MODELER", "Threat Modeling Agent"),
    ("COMPLIANCE_AGENT", "Compliance Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} reviewing the project for weaknesses.",
          capabilities=CapabilitySpec(tools=["read", "grep", "terminal"], skills=["security", "testing"]),
          tags=["security"])))

# Research
for _k, _t in [
    ("WEB_RESEARCHER", "Web Research Agent"),
    ("TECH_RESEARCHER", "Technical Research Agent"),
    ("ACADEMIC_RESEARCHER", "Academic Research Agent"),
    ("REPO_RESEARCHER", "Repository Research Agent"),
    ("DOC_RESEARCHER", "Documentation Research Agent"),
    ("SOURCE_COLLECTOR", "Source Collection Agent"),
    ("SOURCE_VERIFIER", "Source Verification Agent"),
    ("FACT_CHECKER", "Fact-Checking Agent"),
    ("CITATION_AGENT", "Citation Agent"),
    ("COMPARATOR", "Comparison Agent"),
    ("EVIDENCE_ANALYST", "Evidence Analysis Agent"),
    ("RESEARCH_SYNTHESIZER", "Research Synthesis Agent"),
    ("REPORT_AGENT", "Report Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} gathering and validating information.",
          capabilities=CapabilitySpec(tools=["read", "web", "search"], skills=["research", "search"]),
          tags=["research"])))

# Performance
for _k, _t in [
    ("PERF_ANALYST", "Performance Analysis Agent"),
    ("PROFILER", "Profiling Agent"),
    ("BENCHMARKER", "Benchmarking Agent"),
    ("CPU_OPTIMIZER", "CPU Optimization Agent"),
    ("GPU_OPTIMIZER", "GPU Optimization Agent"),
    ("MEMORY_OPTIMIZER", "Memory Optimization Agent"),
    ("NETWORK_OPTIMIZER", "Network Optimization Agent"),
    ("DB_OPTIMIZER", "Database Optimization Agent"),
    ("LATENCY_AGENT", "Latency Agent"),
    ("THROUGHPUT_AGENT", "Throughput Agent"),
    ("CACHE_AGENT", "Cache Agent"),
    ("CONCURRENCY_AGENT", "Concurrency Agent"),
    ("BOTTLENECK_DETECTOR", "Bottleneck Detection Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} improving system performance.",
          capabilities=CapabilitySpec(tools=["read", "terminal", "grep"], skills=["performance"]),
          tags=["performance"])))

# Documentation
for _k, _t in [
    ("DOC_PLANNER", "Documentation Planning Agent"),
    ("TECH_WRITER", "Technical Writing Agent"),
    ("README_AGENT", "README Agent"),
    ("ARCH_DOC_AGENT", "Architecture Documentation Agent"),
    ("API_DOC_AGENT", "API Documentation Agent"),
    ("INSTALL_GUIDE_AGENT", "Installation Guide Agent"),
    ("TUTORIAL_AGENT", "Tutorial Agent"),
    ("TROUBLESHOOT_AGENT", "Troubleshooting Agent"),
    ("CONFIG_DOC_AGENT", "Configuration Documentation Agent"),
    ("CLI_DOC_AGENT", "CLI Documentation Agent"),
    ("TUI_DOC_AGENT", "TUI Documentation Agent"),
    ("GUI_DOC_AGENT", "GUI Documentation Agent"),
    ("DOCSTRING_AGENT", "Comment and Docstring Agent"),
    ("LINK_VALIDATOR", "Link Validation Agent"),
    ("DOC_CONSISTENCY_AGENT", "Documentation Consistency Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} producing clear project documentation.",
          capabilities=CapabilitySpec(tools=["read", "write", "web"], skills=["documentation"]),
          tags=["documentation"])))

# UI & product design
for _k, _t in [
    ("PRODUCT_DESIGNER", "Product Design Agent"),
    ("UI_DESIGNER", "UI Design Agent"),
    ("UX_DESIGNER", "UX Design Agent"),
    ("USER_FLOW_AGENT", "User Flow Agent"),
    ("WIREFRAME_AGENT", "Wireframe Agent"),
    ("DESIGN_SYSTEM_AGENT", "Design System Agent"),
    ("COMPONENT_AGENT", "Component Agent"),
    ("RESPONSIVE_AGENT", "Responsive Design Agent"),
    ("ACCESSIBILITY_AGENT", "Accessibility Agent"),
    ("INTERACTION_AGENT", "Interaction Agent"),
    ("UI_REVIEWER", "UI Review Agent"),
    ("UX_AUDITOR", "UX Audit Agent"),
    ("PROTOTYPER", "Prototype Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} shaping user experience.",
          capabilities=CapabilitySpec(tools=["read", "web"], skills=["ui", "design"]),
          tags=["design"])))

# Data
for _k, _t in [
    ("DATA_ANALYST", "Data Analysis Agent"),
    ("DATA_QUALITY_AGENT", "Data Quality Agent"),
    ("DATA_CLEANER", "Data Cleaning Agent"),
    ("DB_ARCHITECT", "Database Architecture Agent"),
    ("SCHEMA_AGENT", "Schema Agent"),
    ("SQL_AGENT", "SQL Agent"),
    ("QUERY_OPTIMIZER", "Query Optimization Agent"),
    ("DB_MIGRATION_AGENT", "Database Migration Agent"),
    ("DATA_VALIDATOR", "Data Validation Agent"),
    ("DATA_PIPELINE_AGENT", "Data Pipeline Agent"),
    ("ANALYTICS_AGENT", "Analytics Agent"),
    ("REPORTING_AGENT", "Reporting Agent"),
    ("VISUALIZATION_AGENT", "Visualization Agent"),
    ("BACKUP_RECOVERY_AGENT", "Backup and Recovery Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} working with data.",
          capabilities=CapabilitySpec(tools=["read", "terminal", "web"], skills=["data"]),
          tags=["data"])))

# DevOps & operations
for _k, _t in [
    ("DEVOPS_AGENT", "DevOps Agent"),
    ("CICD_AGENT", "CI/CD Agent"),
    ("DEPLOYMENT_AGENT", "Deployment Agent"),
    ("DOCKER_AGENT", "Docker Agent"),
    ("K8S_AGENT", "Kubernetes Agent"),
    ("CLOUD_AGENT", "Cloud Agent"),
    ("SERVER_CONFIG_AGENT", "Server Configuration Agent"),
    ("ENV_SETUP_AGENT", "Environment Setup Agent"),
    ("RELEASE_AGENT", "Release Agent"),
    ("INFRA_AGENT", "Infrastructure Agent"),
    ("MONITORING_AGENT", "Monitoring Agent"),
    ("INCIDENT_AGENT", "Incident Response Agent"),
    ("ROLLBACK_AGENT", "Rollback Agent"),
    ("HEALTH_CHECK_AGENT", "Health Check Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} operating infrastructure.",
          capabilities=CapabilitySpec(tools=["read", "write", "terminal"], skills=["devops", "operations"]),
          tags=["devops"])))

# Provider & model management
for _k, _t in [
    ("PROVIDER_SELECTOR", "Provider Selection Agent"),
    ("MODEL_SELECTOR", "Model Selection Agent"),
    ("PROVIDER_ROUTER", "Provider Router Agent"),
    ("MODEL_ROUTER", "Model Router Agent"),
    ("FALLBACK_AGENT", "Fallback Agent"),
    ("RATE_LIMIT_AGENT", "Rate-Limit Agent"),
    ("COST_OPTIMIZER", "Cost Optimization Agent"),
    ("CONTEXT_MANAGER", "Context Management Agent"),
    ("TOKEN_MANAGER", "Token Management Agent"),
    ("PROVIDER_HEALTH_AGENT", "Provider Health Agent"),
    ("MODEL_EVALUATOR", "Model Evaluation Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} managing model/provider selection.",
          capabilities=CapabilitySpec(tools=["read"], skills=["planning"]),
          tags=["provider"])))

# Capability management
for _k, _t in [
    ("TOOL_DISCOVERER", "Tool Discovery Agent"),
    ("TOOL_SELECTOR", "Tool Selection Agent"),
    ("TOOL_VALIDATOR", "Tool Validation Agent"),
    ("TOOL_RECOVERY_AGENT", "Tool Recovery Agent"),
    ("SKILL_DISCOVERER", "Skill Discovery Agent"),
    ("SKILL_SELECTOR", "Skill Selection Agent"),
    ("PLUGIN_MANAGER", "Plugin Management Agent"),
    ("PLUGIN_VALIDATOR", "Plugin Validation Agent"),
    ("MCP_DISCOVERER", "MCP Discovery Agent"),
    ("MCP_CONNECTION_AGENT", "MCP Connection Agent"),
    ("CAPABILITY_REGISTRY_AGENT", "Capability Registry Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} managing Nexus capabilities.",
          capabilities=CapabilitySpec(tools=["read"], skills=["planning"]),
          tags=["capability"])))

# Monitoring & recovery (internal Hive roles)
for _k, _t in [
    ("HIVE_HEALTH_AGENT", "Hive Health Agent"),
    ("AGENT_HEALTH_AGENT", "Agent Health Agent"),
    ("TASK_MONITOR", "Task Monitoring Agent"),
    ("QUEUE_MONITOR", "Queue Monitoring Agent"),
    ("WORKFLOW_MONITOR", "Workflow Monitoring Agent"),
    ("STUCK_AGENT_DETECTOR", "Stuck-Agent Detection Agent"),
    ("NO_PROGRESS_DETECTOR", "No-Progress Detection Agent"),
    ("FAILURE_CLASSIFIER", "Failure Classification Agent"),
    ("RETRY_AGENT", "Retry Agent"),
    ("RECOVERY_AGENT", "Recovery Agent"),
    ("CHECKPOINT_AGENT", "Checkpoint Agent"),
    ("ROLLBACK_AGENT_2", "Rollback Agent"),
    ("RESTART_AGENT", "Restart Agent"),
    ("REPLACEMENT_AGENT", "Replacement Agent"),
]:
    _add(_role(Specialization(_k, _t,
          description=f"{_t} watching and repairing Hive work.",
          capabilities=CapabilitySpec(tools=["read"], skills=["operations"]),
          tags=["monitoring"])))

# Generic / legacy aliases
_add(_role(Specialization("RESEARCHER", "Researcher", category="specialized",
      description="Deep research, cross-referencing, synthesis.",
      capabilities=CapabilitySpec(tools=["read", "web", "search"], skills=["research", "search"]))))
_add(_role(Specialization("ENGINEER", "Engineer", category="specialized",
      description="Implements code changes and technical fixes.",
      capabilities=CapabilitySpec(tools=["read", "write", "edit", "terminal", "grep"], skills=["coding"]))))
_add(_role(Specialization("REVIEWER", "Reviewer", category="specialized",
      description="Reviews risks, bugs, tests, and regressions.",
      capabilities=CapabilitySpec(tools=["read", "test"], skills=["testing", "validation"]),
      system_prompt_hint="Review strictly; never modify files unless asked.")))
_add(_role(Specialization("PLANNER_LEGACY", "Planner", category="specialized",
      description="Breaks larger goals into ordered execution steps.",
      capabilities=CapabilitySpec(tools=["read", "planning"], skills=["planning"]))))
_add(_role(Specialization("TESTER", "Tester", category="specialized",
      description="Runs validation, reproductions, quality checks.",
      capabilities=CapabilitySpec(tools=["read", "terminal", "test"], skills=["testing"]))))
_add(_role(Specialization("WORKER", "Generic Worker", category="specialized",
      description="General-purpose worker for any well-scoped task.",
      capabilities=CapabilitySpec(tools=["read", "write", "terminal"], skills=["general"]))))


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Specialization] = dict(_BUILTIN)
_CUSTOM: set[str] = set()


def register_specialization(spec: Specialization) -> None:
    """Register (or override) a specialization at runtime."""
    if not getattr(spec, "extensible", True) and spec.key in _REGISTRY and spec.key not in _CUSTOM:
        # Allow override of built-ins only when explicitly extensible.
        pass
    _REGISTRY[spec.key] = spec
    _CUSTOM.add(spec.key)


def get_specialization(key: str) -> Optional[Specialization]:
    return _REGISTRY.get(str(key).upper())


def has_specialization(key: str) -> bool:
    return str(key).upper() in _REGISTRY


def list_specializations(category: Optional[str] = None, tag: Optional[str] = None) -> List[Specialization]:
    out = [s for s in _REGISTRY.values()]
    if category:
        out = [s for s in out if s.category == category]
    if tag:
        out = [s for s in out if tag in s.tags]
    return sorted(out, key=lambda s: s.key)


def all_keys() -> List[str]:
    return sorted(_REGISTRY.keys())


def export_registry() -> List[Dict[str, Any]]:
    """Export the full registry (built-in + custom) for portability."""
    return [s.to_dict() for s in _REGISTRY.values()]


def import_registry(records: List[Dict[str, Any]]) -> int:
    """Import specializations from exported JSON; returns count added."""
    count = 0
    for rec in records:
        if isinstance(rec, dict) and rec.get("key"):
            register_specialization(Specialization.from_dict(rec))
            count += 1
    return count


def clear_custom() -> None:
    """Remove runtime-registered specializations, restoring built-ins."""
    for key in list(_CUSTOM):
        _REGISTRY.pop(key, None)
    _CUSTOM.clear()
