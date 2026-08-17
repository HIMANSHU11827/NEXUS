"""Nexus Hive — a plug-and-play multi-agent orchestration capability.

The Nexus *main agent* is OUTSIDE Hive.  The main agent uses Hive as one of
its capabilities: it hands Hive a goal / task / long-running responsibility
(see :class:`hive.capability.HiveCapability.submit_goal`), and Hive manages its
own internal Agent Teams, agents, scheduling, monitoring, recovery, and returns
one verified result.

Public surface:

* ``NexusHiveEngine`` — the durable sub-agent execution engine (spawn, pause,
  resume, cancel, checkpoint, consolidate, quorum).
* ``HiveCapability`` — the main-agent boundary contract (goal -> run summary).
* ``AgentTeamSpec`` / ``HiveRequest`` / ``HiveRunSummary`` / ``HiveAgentSpec`` /
  ``TaskSpec`` / ``MessageSpec`` / ``CapabilitySpec`` — typed models.
* ``TeamBuilder`` + team-template registry — define and reuse Agent Teams.
* ``Specialization`` registry — plug-and-play specialized-agent library.
* ``resolve`` (capabilities) — capability-inheritance resolution + escalation
  guard.
"""

from .engine import NexusHiveEngine, SubAgent
from .capability import HiveCapability, HivePersistence, DEFAULT_AVAILABLE_CAPABILITIES
from .teams import (
    AgentTeamSpec,
    TeamBuilder,
    ExecutionStage,
    register_team_template,
    get_team_template,
    list_team_templates,
    clone_team_template,
    delete_team_template,
    export_team_templates,
    import_team_templates,
)
from .specializations import (
    Specialization,
    register_specialization,
    get_specialization,
    list_specializations,
    all_keys as specialization_keys,
    export_registry as export_specializations,
    import_registry as import_specializations,
)
from .capabilities import resolve, assert_no_escalation, CapabilityError
from .models import (
    HiveRequest,
    HiveRunSummary,
    HiveAgentSpec,
    TaskSpec,
    MessageSpec,
    HiveError,
    HiveEvent,
    CapabilitySpec,
    BudgetSpec,
    LoopPolicy,
    AgentCategory,
    CapabilityMode,
    ConnectionMode,
    HealthStatus,
    TaskState,
    HiveRunStatus,
    ErrorCategory,
    can_transition_task,
    TASK_TRANSITIONS,
)

__all__ = [
    "NexusHiveEngine",
    "SubAgent",
    "HiveCapability",
    "HivePersistence",
    "AgentTeamSpec",
    "TeamBuilder",
    "ExecutionStage",
    "register_team_template",
    "get_team_template",
    "list_team_templates",
    "clone_team_template",
    "delete_team_template",
    "export_team_templates",
    "import_team_templates",
    "Specialization",
    "register_specialization",
    "get_specialization",
    "list_specializations",
    "specialization_keys",
    "export_specializations",
    "import_specializations",
    "resolve",
    "assert_no_escalation",
    "CapabilityError",
    "HiveRequest",
    "HiveRunSummary",
    "HiveAgentSpec",
    "TaskSpec",
    "MessageSpec",
    "HiveError",
    "HiveEvent",
    "CapabilitySpec",
    "BudgetSpec",
    "LoopPolicy",
    "AgentCategory",
    "CapabilityMode",
    "ConnectionMode",
    "HealthStatus",
    "TaskState",
    "HiveRunStatus",
    "ErrorCategory",
    "can_transition_task",
    "TASK_TRANSITIONS",
]
