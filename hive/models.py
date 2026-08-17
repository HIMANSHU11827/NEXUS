"""Typed data models for the Nexus Hive capability.

These models define the *contract* between the Nexus main agent (which is
OUTSIDE Hive) and Hive (a plug-and-play capability used by the main agent).

The main agent submits a :class:`HiveRequest` (a goal / task / long-running
responsibility).  Hive manages its own internal agents, plans, scheduling,
monitoring and recovery, and returns a :class:`HiveRunSummary` plus the
verified final result.

Nothing in here depends on the live engine, the LLM, providers, or tools, so
the contract can be validated, serialised, and tested in isolation.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class HiveRunStatus(str, enum.Enum):
    """Lifecycle status of a Hive run."""

    DRAFT = "draft"
    PLANNED = "planned"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class TaskState(str, enum.Enum):
    """States a single Hive task may move through (see ``TASK_TRANSITIONS``)."""

    DRAFT = "draft"
    PENDING = "pending"
    READY = "ready"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING = "waiting"
    WAITING_DEPENDENCY = "waiting_for_dependency"
    WAITING_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    PAUSED = "paused"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    DEAD_LETTERED = "dead_lettered"

    @classmethod
    def terminal_states(cls) -> frozenset[str]:
        return frozenset({
            cls.COMPLETED.value, cls.FAILED.value, cls.CANCELLED.value,
            cls.SKIPPED.value, cls.DEAD_LETTERED.value,
        })


# Valid task-state transitions (closed set; anything else is rejected).
TASK_TRANSITIONS: Dict[str, frozenset[str]] = {
    TaskState.DRAFT.value: frozenset({TaskState.PENDING, TaskState.CANCELLED, TaskState.SKIPPED}),
    TaskState.PENDING.value: frozenset({
        TaskState.READY.value, TaskState.QUEUED, TaskState.ASSIGNED,
        TaskState.RUNNING.value, TaskState.WAITING_DEPENDENCY.value,
        TaskState.WAITING_APPROVAL.value, TaskState.CANCELLED.value, TaskState.SKIPPED.value,
    }),
    TaskState.READY.value: frozenset({TaskState.QUEUED, TaskState.ASSIGNED, TaskState.CANCELLED}),
    TaskState.QUEUED.value: frozenset({
        TaskState.ASSIGNED, TaskState.RUNNING, TaskState.CANCELLED,
        TaskState.BLOCKED, TaskState.WAITING_DEPENDENCY, TaskState.WAITING_APPROVAL,
    }),
    TaskState.ASSIGNED.value: frozenset({
        TaskState.RUNNING, TaskState.CANCELLED, TaskState.WAITING_DEPENDENCY,
        TaskState.WAITING_APPROVAL, TaskState.BLOCKED,
    }),
    TaskState.RUNNING.value: frozenset({
        TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PAUSED,
        TaskState.RETRYING, TaskState.WAITING, TaskState.BLOCKED, TaskState.DEAD_LETTERED,
    }),
    TaskState.WAITING.value: frozenset({TaskState.RUNNING, TaskState.CANCELLED, TaskState.BLOCKED}),
    TaskState.WAITING_DEPENDENCY.value: frozenset({
        TaskState.RUNNING, TaskState.BLOCKED, TaskState.CANCELLED, TaskState.SKIPPED,
    }),
    TaskState.WAITING_APPROVAL.value: frozenset({
        TaskState.RUNNING, TaskState.CANCELLED, TaskState.BLOCKED, TaskState.SKIPPED,
    }),
    TaskState.BLOCKED.value: frozenset({
        TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED, TaskState.SKIPPED,
        TaskState.DEAD_LETTERED, TaskState.RETRYING,
    }),
    TaskState.PAUSED.value: frozenset({TaskState.RUNNING, TaskState.CANCELLED}),
    TaskState.RETRYING.value: frozenset({
        TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED, TaskState.DEAD_LETTERED,
    }),
    # Terminal states are sinks.
    TaskState.COMPLETED.value: frozenset(),
    TaskState.FAILED.value: frozenset({TaskState.RETRYING, TaskState.DEAD_LETTERED}),
    TaskState.CANCELLED.value: frozenset(),
    TaskState.SKIPPED.value: frozenset(),
    TaskState.DEAD_LETTERED.value: frozenset(),
}


def can_transition_task(from_state: str, to_state: str) -> bool:
    """Return True when ``to_state`` is a valid successor of ``from_state``."""
    allowed = TASK_TRANSITIONS.get(from_state)
    if allowed is None:
        return False
    return to_state in allowed


class AgentCategory(str, enum.Enum):
    """Primary Hive agent categories. These overlap freely (see §10)."""

    AGENT_TEAM = "agent_team"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    SPECIALIZED = "specialized"
    SUB_AGENT = "sub_agent"
    SUPERVISOR = "supervisor"


class CapabilityMode(str, enum.Enum):
    """How a Hive agent inherits capabilities from the main agent.

    * FULL        — inherit everything the main agent may delegate, subject to
                    explicit security boundaries.
    * SELECTED    — inherit only explicitly selected categories.
    * ROLE_BASED  — inherit the capability profile defined by the specialization.
    * CUSTOM      — an exact, caller-specified combination.
    * RESTRICTED  — a minimal capability set (e.g. read-only + review skills).
    """

    FULL = "full"
    SELECTED = "selected"
    ROLE_BASED = "role_based"
    CUSTOM = "custom"
    RESTRICTED = "restricted"


class HealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    BUSY = "busy"
    IDLE = "idle"
    WAITING = "waiting"
    BLOCKED = "blocked"
    RETRYING = "retrying"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    UNRESPONSIVE = "unresponsive"
    FAILED = "failed"
    STOPPED = "stopped"


class ConnectionMode(str, enum.Enum):
    """Provider/connection mode for a Hive agent (see §21)."""

    LOCAL = "local"
    API_KEY = "api_key"
    OAUTH = "oauth"
    INHERIT = "inherit"


class ErrorCategory(str, enum.Enum):
    CONFIG = "hive_configuration_error"
    TEAM = "agent_team_error"
    AGENT = "agent_error"
    TASK = "task_error"
    QUEUE = "queue_error"
    SCHEDULING = "scheduling_error"
    PROVIDER = "provider_error"
    MODEL = "model_error"
    TOOL = "tool_error"
    SKILL = "skill_error"
    PLUGIN = "plugin_error"
    MCP = "mcp_error"
    PERMISSION = "permission_error"
    APPROVAL = "approval_error"
    BUDGET = "budget_error"
    TIMEOUT = "timeout_error"
    PERSISTENCE = "persistence_error"
    RECOVERY = "recovery_error"
    CONFLICT = "conflict_error"
    CANCELLATION = "cancellation_error"


# ---------------------------------------------------------------------------
# Serializable base
# ---------------------------------------------------------------------------


class _Serializable:
    """Mixin giving dataclasses a safe ``to_dict`` / ``from_dict``."""

    def to_dict(self) -> Dict[str, Any]:
        return _strip_none(asdict(self))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Any":
        # Only hydrate fields the dataclass actually declares.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in (data or {}).items() if k in known}
        return cls(**filtered)


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Capability specification
# ---------------------------------------------------------------------------


@dataclass
class CapabilitySpec(_Serializable):
    """Declares which platform capabilities a Hive agent may use.

    ``mode`` selects the inheritance strategy (see :class:`CapabilityMode`).
    The explicit lists are used for SELECTED / CUSTOM / RESTRICTED modes and as
    overrides for ROLE_BASED.  In FULL mode an empty explicit list means
    "inherit all available".
    """

    mode: str = CapabilityMode.ROLE_BASED.value
    tools: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    plugins: List[str] = field(default_factory=list)
    mcp_servers: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)
    memory: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    sandbox: Optional[str] = None
    workspace: Optional[str] = None
    remove_inherited: List[str] = field(default_factory=list)
    overrides: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalise the mode string.
        try:
            self.mode = CapabilityMode(self.mode).value
        except ValueError:
            self.mode = CapabilityMode.ROLE_BASED.value


@dataclass
class BudgetSpec(_Serializable):
    """Budget limits for a Hive run / team / agent / task."""

    tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    runtime_seconds: Optional[float] = None
    max_agents: Optional[int] = None
    max_parallel_agents: Optional[int] = None
    max_subagent_depth: Optional[int] = None
    max_tool_calls: Optional[int] = None
    max_retries: Optional[int] = None
    max_loop_iterations: Optional[int] = None


@dataclass
class LoopPolicy(_Serializable):
    """Safety boundaries for a controlled (possibly long-running) loop (§19)."""

    start_condition: str = ""
    continuation_condition: str = ""
    completion_condition: str = ""
    stop_condition: str = ""
    max_iterations: Optional[int] = None
    max_runtime_seconds: Optional[float] = None
    max_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None
    max_retries: Optional[int] = None
    max_failures: Optional[int] = None
    idle_timeout_seconds: Optional[float] = None
    no_progress_threshold_seconds: Optional[float] = None
    checkpoint_every_iterations: Optional[int] = None
    approval_points: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent & task specs
# ---------------------------------------------------------------------------


@dataclass
class HiveAgentSpec(_Serializable):
    """A single Hive agent definition (real Nexus agent instance, §13)."""

    agent_id: str = ""
    name: str = ""
    description: str = ""
    category: str = AgentCategory.SPECIALIZED.value
    specialization: str = "WORKER"
    instructions: str = ""
    goal: str = ""
    model: Optional[str] = None
    provider: Optional[str] = None
    connection_mode: str = ConnectionMode.INHERIT.value
    tools: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    plugins: List[str] = field(default_factory=list)
    mcp_servers: List[str] = field(default_factory=list)
    capabilities: Optional[CapabilitySpec] = None
    permissions: List[str] = field(default_factory=list)
    sandbox: Optional[str] = None
    workspace: Optional[str] = None
    token_budget: Optional[int] = None
    cost_budget: Optional[float] = None
    runtime_limit_seconds: Optional[float] = None
    retry_policy: Optional[Dict[str, Any]] = None
    priority: int = 5
    output_schema: Optional[Dict[str, Any]] = None
    validation_rules: List[str] = field(default_factory=list)
    review_rules: List[str] = field(default_factory=list)
    lifecycle: str = "temporary"  # temporary | persistent
    health_policy: Optional[Dict[str, Any]] = None
    stopping_rules: List[str] = field(default_factory=list)
    max_steps: int = 6
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not self.agent_id:
            self.agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        if not self.name:
            self.name = self.agent_id
        try:
            self.category = AgentCategory(self.category).value
        except ValueError:
            self.category = AgentCategory.SPECIALIZED.value
        try:
            self.connection_mode = ConnectionMode(self.connection_mode).value
        except ValueError:
            self.connection_mode = ConnectionMode.INHERIT.value


@dataclass
class TaskSpec(_Serializable):
    """One task inside a Hive run / Agent Team (§23)."""

    task_id: str = ""
    hive_run_id: str = ""
    team_id: str = ""
    parent_task_id: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    category: str = AgentCategory.SPECIALIZED.value
    specialization: str = "WORKER"
    goal: str = ""
    description: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 5
    status: str = TaskState.PENDING.value
    attempts: int = 0
    retry_policy: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[float] = None
    budget: Optional[BudgetSpec] = None
    required_capabilities: Optional[CapabilitySpec] = None
    required_permissions: List[str] = field(default_factory=list)
    workspace: Optional[str] = None
    checkpoint_ref: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    assigned_at: Optional[float] = None
    started_at: Optional[float] = None
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    failure_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    validation_result: Optional[Dict[str, Any]] = None
    review_result: Optional[Dict[str, Any]] = None
    result: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = f"task_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Agent Team
# ---------------------------------------------------------------------------


@dataclass
class AgentTeamSpec(_Serializable):
    """A reusable group of Hive agents working toward one shared goal (§16).

    ``stages`` is an ordered execution plan.  Each stage is either a single
    agent (sequential) or a *parallel group* of agents.  Stages run in order;
    within a parallel stage every agent runs concurrently.  This is the
    canonical representation for "mixed" execution (§18).
    """

    team_id: str = ""
    name: str = ""
    goal: str = ""
    instructions: str = ""
    coordinator: Optional[str] = None
    agents: List[HiveAgentSpec] = field(default_factory=list)
    shared_tools: List[str] = field(default_factory=list)
    shared_skills: List[str] = field(default_factory=list)
    shared_plugins: List[str] = field(default_factory=list)
    shared_mcp_servers: List[str] = field(default_factory=list)
    shared_memory: List[str] = field(default_factory=list)
    workspace: Optional[str] = None
    permissions: List[str] = field(default_factory=list)
    budgets: Optional[BudgetSpec] = None
    schedule: Optional[Dict[str, Any]] = None
    workflow: str = "mixed"  # single | parallel | sequential | mixed | pipeline | event_driven | loop
    checkpoints: bool = True
    completion_criteria: List[str] = field(default_factory=list)
    failure_policy: str = "isolate"  # isolate | stop_team | skip_noncritical
    reporting_policy: Dict[str, Any] = field(default_factory=dict)
    loop_policy: Optional[LoopPolicy] = None
    continuous: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        if not self.team_id:
            self.team_id = f"team_{uuid.uuid4().hex[:8]}"
        if not self.name:
            self.name = self.team_id

    @property
    def is_agent_team(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# The main-agent -> Hive boundary contract
# ---------------------------------------------------------------------------


@dataclass
class HiveRequest(_Serializable):
    """What the main agent hands to Hive (§3).

    ``goal`` is the only truly required field.  Everything else is optional
    and lets the main agent steer how Hive should self-organise.
    """

    goal: str = ""
    task: str = ""
    expected_outcome: str = ""
    completion_criteria: List[str] = field(default_factory=list)
    priority: int = 5
    deadline: Optional[float] = None
    team_preference: Optional[str] = None  # named team template id/name
    required_specializations: List[str] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    required_skills: List[str] = field(default_factory=list)
    required_plugins: List[str] = field(default_factory=list)
    required_mcp_servers: List[str] = field(default_factory=list)
    provider_preference: Optional[str] = None
    model_preference: Optional[str] = None
    permission_limits: List[str] = field(default_factory=list)
    sandbox_requirements: Optional[str] = None
    token_budget: Optional[int] = None
    cost_budget: Optional[float] = None
    runtime_budget_seconds: Optional[float] = None
    max_agents: Optional[int] = None
    max_parallel_agents: Optional[int] = None
    allow_continuous: bool = False
    require_human_approval: bool = False
    reporting_frequency: Optional[str] = None
    final_output_format: str = "text"
    capability_mode: str = CapabilityMode.ROLE_BASED.value
    connection_mode: str = ConnectionMode.INHERIT.value
    agent_team: Optional[AgentTeamSpec] = None
    loop_policy: Optional[LoopPolicy] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.goal and self.task:
            self.goal = self.task
        if not self.goal:
            raise ValueError("HiveRequest requires a non-empty 'goal'")
        try:
            self.capability_mode = CapabilityMode(self.capability_mode).value
        except ValueError:
            self.capability_mode = CapabilityMode.ROLE_BASED.value
        try:
            self.connection_mode = ConnectionMode(self.connection_mode).value
        except ValueError:
            self.connection_mode = ConnectionMode.INHERIT.value


@dataclass
class MessageSpec(_Serializable):
    """Structured internal Hive message (§27)."""

    message_id: str = ""
    sender: str = ""
    recipient: str = ""
    hive_run_id: str = ""
    team_id: str = ""
    task_id: Optional[str] = None
    message_type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None
    delivery_status: str = "pending"  # pending | delivered | failed
    acknowledgement_status: str = "unacknowledged"  # unacknowledged | acknowledged

    def __post_init__(self) -> None:
        if not self.message_id:
            self.message_id = f"msg_{uuid.uuid4().hex[:10]}"


@dataclass
class HiveEvent(_Serializable):
    """Lightweight observability event (§39)."""

    event_id: str = ""
    event_type: str = ""
    hive_run_id: str = ""
    team_id: str = ""
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    status: str = ""
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = f"evt_{uuid.uuid4().hex[:10]}"


@dataclass
class HiveError(_Serializable):
    """Typed error envelope (§40)."""

    code: str = ""
    message: str = ""
    component: str = ""
    category: str = ErrorCategory.AGENT.value
    hive_run_id: str = ""
    team_id: str = ""
    agent_id: str = ""
    task_id: str = ""
    retryable: bool = False
    suggested_action: str = ""
    underlying_cause: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        try:
            self.category = ErrorCategory(self.category).value
        except ValueError:
            self.category = ErrorCategory.AGENT.value


@dataclass
class HiveRunSummary(_Serializable):
    """What Hive returns to the main agent (§3, §35)."""

    hive_run_id: str = ""
    status: str = HiveRunStatus.DRAFT.value
    created_agents: List[str] = field(default_factory=list)
    selected_team_id: Optional[str] = None
    current_tasks: List[str] = field(default_factory=list)
    progress: float = 0.0
    important_events: List[str] = field(default_factory=list)
    errors: List[HiveError] = field(default_factory=list)
    retry_status: Dict[str, Any] = field(default_factory=dict)
    budget_usage: Dict[str, Any] = field(default_factory=dict)
    pending_approvals: List[str] = field(default_factory=list)
    checkpoints: List[str] = field(default_factory=list)
    final_result: Optional[str] = None
    verification_result: Optional[Dict[str, Any]] = None
    remaining_limitations: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        try:
            HiveRunStatus(self.status)
        except ValueError:
            self.status = HiveRunStatus.DRAFT.value
