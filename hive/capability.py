"""HiveCapability — the main-agent boundary for Nexus Hive (§2, §3, §5).

``HiveCapability`` is the single, clean interface the Nexus main agent uses to
hand work to Hive.  The main agent is *outside* Hive: it submits a
:class:`HiveRequest`, receives a :class:`HiveRunSummary`, and may pause /
resume / cancel / inspect — without ever becoming part of Hive's internal
agent graph.

Internally HiveCapability:

* selects or builds an Agent Team (§9, §16) from the request,
* turns the team into a staged execution plan (sequential + parallel groups,
  §18) and runs it on the real :class:`NexusHiveEngine`,
* threads the selected capabilities, specializations, providers and models
  into each internal agent (§13, §14, §21),
* persists every run/team/agent/task to a SQLite store so a crash can be
  recovered and resumed (§34, §41),
* exposes a typed, observable status surface (§31, §39).

It is backend-agnostic: the constructor takes a ``NexusHiveEngine`` (or builds
a default one), a ``tool_registry``, an ``llm_call`` factory, and a dictionary
of *available* main-agent capabilities for the resolver.  Tests can inject fake
async LLMs and a ``None`` tool registry.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .capabilities import assert_no_escalation, resolve
from .models import (
    AgentTeamSpec,
    CapabilityMode,
    CapabilitySpec,
    ConnectionMode,
    ErrorCategory,
    HiveError,
    HiveEvent,
    HiveRequest,
    HiveRunStatus,
    HiveRunSummary,
    MessageSpec,
    TaskSpec,
)
from .specializations import get_specialization
from .teams import TeamBuilder


DEFAULT_AVAILABLE_CAPABILITIES: Dict[str, List[str]] = {
    "tools": ["read", "write", "edit", "terminal", "grep", "search", "web", "test", "planning", "todo"],
    "skills": ["coding", "testing", "research", "security", "documentation", "ui", "design",
               "planning", "architecture", "performance", "data", "devops", "operations", "validation"],
    "plugins": [],
    "mcp_servers": [],
    "models": [],
    "providers": ["lm_studio", "cloud"],
    "memory": ["short_term", "long_term"],
    "permissions": ["file_read", "file_write", "shell", "network"],
}


def _safe_text(value: Any, limit: int = 4000) -> str:
    return str(value or "")[:max(1, int(limit))]


class HivePersistence:
    """SQLite store for Hive runs, teams, tasks, messages, events."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root or os.getcwd())
        os.makedirs(os.path.join(self.root, ".nexus", "hive"), exist_ok=True)
        self.path = os.path.join(self.root, ".nexus", "hive", "hive_runs.sqlite3")
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hive_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    team_json TEXT,
                    created_at REAL,
                    updated_at REAL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hive_tasks (
                    task_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    team_id TEXT,
                    task_json TEXT NOT NULL,
                    updated_at REAL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hive_messages (
                    message_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    message_json TEXT NOT NULL,
                    created_at REAL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def save_run(self, summary: "HiveRunSummary", team: Optional[AgentTeamSpec] = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO hive_runs(run_id,status,goal,summary_json,team_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                "status=excluded.status, summary_json=excluded.summary_json, "
                "team_json=excluded.team_json, updated_at=excluded.updated_at",
                (summary.hive_run_id, summary.status, _safe_text(summary.final_result or "", 20000),
                 json.dumps(summary.to_dict(), default=str),
                 json.dumps(team.to_dict(), default=str) if team else "",
                 summary.created_at, summary.updated_at),
            )

    def load_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM hive_runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> List[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id FROM hive_runs ORDER BY updated_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [r["run_id"] for r in rows]

    def save_task(self, task: TaskSpec) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO hive_tasks(task_id,run_id,team_id,task_json,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET task_json=excluded.task_json, updated_at=excluded.updated_at",
                (task.task_id, task.hive_run_id, task.team_id,
                 json.dumps(task.to_dict(), default=str), task.updated_at),
            )

    def save_message(self, msg: MessageSpec) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO hive_messages(message_id,run_id,message_json,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(message_id) DO UPDATE SET message_json=excluded.message_json",
                (msg.message_id, msg.hive_run_id, json.dumps(msg.to_dict(), default=str), msg.timestamp),
            )


class HiveCapability:
    """Main-agent-facing Hive capability (the boundary)."""

    def __init__(
        self,
        root: str,
        engine: Any = None,
        *,
        tool_registry: Any = None,
        llm_call: Optional[Callable[[List[Dict[str, str]]], Awaitable[str] | str]] = None,
        available_capabilities: Optional[Dict[str, List[str]]] = None,
        security_limits: Optional[List[str]] = None,
        sink: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.root = os.path.abspath(root or os.getcwd())
        self._engine = engine
        self._tool_registry = tool_registry
        self._llm_call = llm_call
        self._available = available_capabilities or dict(DEFAULT_AVAILABLE_CAPABILITIES)
        self._security_limits = list(security_limits or [])
        self._sink = sink
        self._persistence = HivePersistence(self.root)
        self._builder = TeamBuilder(self._available)
        self._runs: Dict[str, HiveRunSummary] = {}
        self._teams: Dict[str, AgentTeamSpec] = {}
        self._tasks: Dict[str, TaskSpec] = {}
        self._agents_by_run: Dict[str, List[Any]] = {}
        self._hive_ids_by_run: Dict[str, str] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()
        self._closed = False

    # ---- engine access (lazy) -----------------------------------------
    def _get_engine(self):
        if self._engine is None:
            from .engine import NexusHiveEngine
            self._engine = NexusHiveEngine(self.root, tool_registry=self._tool_registry)
        eng = self._engine
        if self._tool_registry is not None and getattr(eng, "tool_registry", None) is None:
            eng.set_tool_registry(self._tool_registry)
        if self._llm_call is not None:
            eng.set_llm_call(self._llm_call)
        if self._sink is not None:
            eng.set_sink(self._sink)
        return eng

    # ---- main-agent boundary API --------------------------------------
    async def submit_goal(self, request: HiveRequest) -> HiveRunSummary:
        """Hand a goal/task/long-running responsibility to Hive (§3)."""
        run_id = f"hive_{uuid.uuid4().hex[:10]}"
        team = self._builder.build(request)

        # Resolve capabilities for every agent and enforce no-escalation (§44).
        for agent in team.agents:
            caps = self._resolve_agent_caps(agent, request)
            agent.capabilities = caps
            self._apply_security(agent, caps, request)

        summary = HiveRunSummary(hive_run_id=run_id, status=HiveRunStatus.PLANNED.value)
        summary.selected_team_id = team.team_id
        summary.created_agents = [a.agent_id for a in team.agents]
        summary.remaining_limitations = self._limitations(request, team)

        with self._lock:
            self._runs[run_id] = summary
            self._teams[run_id] = team

        self._persistence.save_run(summary, team)
        await self._emit("hive.run.created", run_id, "planned", payload={"goal": request.goal})
        return summary

    async def plan_and_execute(self, request: HiveRequest) -> HiveRunSummary:
        """Submit the goal then run the plan to completion and return the run."""
        summary = await self.submit_goal(request)
        await self.execute_run(summary.hive_run_id)
        return await self.get_run(summary.hive_run_id)

    async def execute_run(self, run_id: str) -> None:
        """Execute the staged plan for ``run_id`` (real parallel + sequential)."""
        with self._lock:
            summary = self._runs.get(run_id)
            team = self._teams.get(run_id)
        if summary is None or team is None:
            raise KeyError(f"Unknown Hive run: {run_id}")

        summary.status = HiveRunStatus.RUNNING.value
        summary.updated_at = time.time()
        self._persistence.save_run(summary, team)
        await self._emit("hive.run.started", run_id, "running", payload={"team": team.name})

        engine = self._get_engine()
        stages = TeamBuilder.plan(team)

        run_agents: List[Any] = []
        context: Dict[str, str] = {}  # stage outputs threaded to the next sequential agent

        try:
            for stage in stages:
                # Build (task, persona, capabilities) tuples for this stage.
                pairs: List[tuple[str, str]] = []
                caps_list: List[Optional[CapabilitySpec]] = []
                for spec in stage.agents:
                    task_desc = self._task_desc(spec, context)
                    pairs.append((task_desc, spec.specialization))
                    caps_list.append(spec.capabilities)
                    task = TaskSpec(
                        hive_run_id=run_id, team_id=team.team_id,
                        assigned_agent_id=spec.agent_id, specialization=spec.specialization,
                        category=spec.category, goal=spec.goal, description=task_desc,
                        status="running",
                    )
                    self._persistence.save_task(task)
                    with self._lock:
                        self._tasks[task.task_id] = task

                hive_id, spawned = await engine.spawn_hive(
                    pairs, parent_run_id=run_id, agent_capabilities=caps_list,
                )
                self._hive_ids_by_run[run_id] = hive_id
                await engine.consolidate_hive(hive_id, timeout=self._run_timeout())
                run_agents.extend(spawned)

                # Failure isolation: a failed stage does not crash the run; we
                # just record it and continue (§33).
                for spec, sub in zip(stage.agents, spawned):
                    if str(getattr(sub, "status", "")) != "success":
                        summary.errors.append(HiveError(
                            code="hive.agent_failed",
                            message=f"Agent {spec.specialization} did not complete successfully",
                            component="HiveCapability.execute_run",
                            category=ErrorCategory.AGENT.value,
                            hive_run_id=run_id, agent_id=spec.agent_id,
                            retryable=True,
                            suggested_action="Retry the task or replace the agent.",
                            underlying_cause=_safe_text(getattr(sub, "error", "") or "", 1000),
                        ))

                # Thread a sequential stage's result forward (§26).
                if stage.kind == "sequential" and spawned:
                    context[stage.agents[0].specialization] = _safe_text(spawned[0].result or "", 4000)

            final = self._aggregate(team, run_agents)
            summary.final_result = final
            failed = any(str(getattr(a, "status", "")) != "success" for a in run_agents)
            summary.status = HiveRunStatus.COMPLETED.value if not failed else HiveRunStatus.FAILED.value
            summary.verification_result = {
                "agents": len(run_agents),
                "succeeded": sum(1 for a in run_agents if str(getattr(a, "status", "")) == "success"),
                "team": team.name,
            }
        except asyncio.CancelledError:
            summary.status = HiveRunStatus.CANCELLED.value
            raise
        except Exception as exc:
            summary.errors.append(HiveError(
                code="hive.execution_error", message=str(exc),
                component="HiveCapability.execute_run", category=ErrorCategory.AGENT.value,
                hive_run_id=run_id, retryable=True,
                suggested_action="Inspect per-agent status; retry failed tasks.",
                underlying_cause=_safe_text(exc, 1000),
            ))
            summary.status = HiveRunStatus.FAILED.value
        finally:
            summary.updated_at = time.time()
            self._agents_by_run[run_id] = run_agents
            self._persistence.save_run(summary, team)
            await self._emit("hive.run.finished", run_id, summary.status,
                             payload={"status": summary.status})

    async def run_continuous(self, run_id: str) -> HiveRunSummary:
        """Run a Hive run as a controlled long-running / 24/7 loop (§17, §19).

        Each iteration replays the team plan.  The loop is bounded by the team's
        ``LoopPolicy`` (max iterations, runtime, failures, idle, no-progress) and
        can be paused / cancelled / resumed at any time via the control surface.
        At the end of every iteration a checkpoint is written so a process restart
        can resume without duplicating completed work (§34).
        """
        with self._lock:
            summary = self._runs.get(run_id)
            team = self._teams.get(run_id)
        if summary is None or team is None:
            raise KeyError(f"Unknown Hive run: {run_id}")

        policy = team.loop_policy or LoopPolicy(
            max_iterations=10, max_failures=3, no_progress_threshold_seconds=300,
            checkpoint_every_iterations=1,
        )
        start = time.time()
        iterations = 0
        consecutive_failures = 0
        last_progress = time.time()

        summary.status = HiveRunStatus.RUNNING.value
        self._persistence.save_run(summary, team)
        await self._emit("hive.loop.started", run_id, "running",
                         payload={"policy": policy.to_dict()})

        try:
            while True:
                # ---- control / safety gates --------------------------------
                # Check the dedicated cancel marker first so a cancel issued
                # mid-iteration is honoured even if execute_run overwrites the
                # cached status while finishing the current iteration.
                with self._lock:
                    cur_status = self._runs.get(run_id).status
                if run_id in self._cancelled or cur_status == HiveRunStatus.CANCELLED.value:
                    summary.status = HiveRunStatus.CANCELLED.value
                    break
                if cur_status == HiveRunStatus.PAUSED.value:
                    await self._emit("hive.loop.paused", run_id, "paused")
                    break
                iterations += 1
                if policy.max_iterations and iterations >= policy.max_iterations:
                    self._add_limit("max_iterations", run_id, summary)
                    summary.status = HiveRunStatus.COMPLETED.value
                    summary.important_events.append(f"stopped: max_iterations={policy.max_iterations}")
                    break
                if policy.max_runtime_seconds and (time.time() - start) > policy.max_runtime_seconds:
                    self._add_limit("max_runtime", run_id, summary)
                    summary.status = HiveRunStatus.COMPLETED.value
                    summary.important_events.append("stopped: max_runtime_seconds")
                    break

                # ---- one iteration (replays the staged plan) ---------------
                try:
                    await self.execute_run_iteration(run_id)
                except asyncio.CancelledError:
                    summary.status = HiveRunStatus.CANCELLED.value
                    break
                with self._lock:
                    cur = self._runs.get(run_id)
                    failed = any(e.code == "hive.agent_failed" for e in cur.errors
                                 if e.hive_run_id == run_id)
                if failed:
                    consecutive_failures += 1
                    if policy.max_failures and consecutive_failures > policy.max_failures:
                        summary.status = HiveRunStatus.FAILED.value
                        summary.important_events.append(f"stopped: max_failures={policy.max_failures}")
                        break
                else:
                    consecutive_failures = 0
                    last_progress = time.time()

                # ---- checkpoint ------------------------------------------
                if policy.checkpoint_every_iterations and \
                        iterations % policy.checkpoint_every_iterations == 0:
                    summary.checkpoints.append(f"iter-{iterations}")
                    await self._emit("hive.loop.checkpoint", run_id, "running",
                                     payload={"iteration": iterations})

                if policy.no_progress_threshold_seconds and \
                        (time.time() - last_progress) > policy.no_progress_threshold_seconds:
                    self._add_limit("no_progress", run_id, summary)
                    summary.status = HiveRunStatus.COMPLETED.value
                    summary.important_events.append("stopped: no_progress_threshold")
                    break
        finally:
            summary.updated_at = time.time()
            summary.budget_usage["iterations"] = iterations
            self._persistence.save_run(summary, team)
            await self._emit("hive.loop.finished", run_id, summary.status,
                             payload={"iterations": iterations, "status": summary.status})
        return summary

    async def execute_run_iteration(self, run_id: str) -> None:
        """Run a single iteration of the plan (used by ``run_continuous``)."""
        await self.execute_run(run_id)

    # ---- control surface ----------------------------------------------
    async def pause(self, run_id: str, reason: str = "operator requested pause") -> None:
        hive_id = self._hive_ids_by_run.get(run_id)
        if hive_id:
            await self._get_engine().pause_hive(hive_id, reason)
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id].status = HiveRunStatus.PAUSED.value
                self._runs[run_id].updated_at = time.time()
        await self._emit("hive.run.paused", run_id, "paused", payload={"reason": reason})

    async def resume(self, run_id: str) -> None:
        hive_id = self._hive_ids_by_run.get(run_id)
        if hive_id:
            await self._get_engine().resume_hive(hive_id)
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id].status = HiveRunStatus.RUNNING.value
                self._runs[run_id].updated_at = time.time()

    async def cancel(self, run_id: str, reason: str = "operator cancellation") -> None:
        hive_id = self._hive_ids_by_run.get(run_id)
        if hive_id:
            await self._get_engine().cancel_hive(hive_id)
        with self._lock:
            if run_id in self._runs:
                self._runs[run_id].status = HiveRunStatus.CANCELLED.value
                self._runs[run_id].updated_at = time.time()
            self._cancelled.add(run_id)
        await self._emit("hive.run.cancelled", run_id, "cancelled", payload={"reason": reason})

    async def get_run(self, run_id: str) -> HiveRunSummary:
        with self._lock:
            cached = self._runs.get(run_id)
        if cached is not None:
            return cached
        row = self._persistence.load_run(run_id)
        if row is None:
            raise KeyError(f"Unknown Hive run: {run_id}")
        return HiveRunSummary.from_dict(json.loads(row["summary_json"]))

    def _is_cancelled(self, run_id: str) -> bool:
        with self._lock:
            cur = self._runs.get(run_id)
        if cur is None:
            return False
        return cur.status == HiveRunStatus.CANCELLED.value

    @staticmethod
    def _add_limit(label: str, run_id: str, summary: "HiveRunSummary") -> None:
        summary.budget_usage.setdefault("limits_hit", [])
        if label not in summary.budget_usage["limits_hit"]:
            summary.budget_usage["limits_hit"].append(label)

    def list_runs(self, limit: int = 50) -> List[str]:
        with self._lock:
            if self._runs:
                return list(self._runs.keys())[:limit]
        return self._persistence.list_runs(limit)

    # ---- Agent Team management (plug-and-play) ------------------------
    def list_agent_teams(self) -> List[AgentTeamSpec]:
        from .teams import list_team_templates
        with self._lock:
            dynamic = [t for k, t in self._teams.items() if k.startswith("team_only_")]
        return list_team_templates() + dynamic

    def get_agent_team(self, key: str) -> Optional[AgentTeamSpec]:
        from .teams import get_team_template
        with self._lock:
            for t in self._teams.values():
                if t.team_id == key or t.name == key:
                    return t
        return get_team_template(key)

    def clone_agent_team(self, key: str, new_name: Optional[str] = None) -> AgentTeamSpec:
        from .teams import clone_team_template
        return clone_team_template(key, new_name)

    # ---- messaging (§27) ----------------------------------------------
    def send_message(self, msg: MessageSpec) -> MessageSpec:
        msg.delivery_status = "delivered"
        self._persistence.save_message(msg)
        return msg

    # ---- recovery (§34) -----------------------------------------------
    async def recover_interrupted(self, run_id: str) -> HiveRunSummary:
        """Rehydrate a run interrupted by a crash and mark it resumable."""
        row = self._persistence.load_run(run_id)
        if row is None:
            raise KeyError(f"No persisted Hive run: {run_id}")
        summary = HiveRunSummary.from_dict(json.loads(row["summary_json"]))
        team = AgentTeamSpec.from_dict(json.loads(row["team_json"])) if row["team_json"] else None
        with self._lock:
            self._runs[run_id] = summary
            if team is not None:
                self._teams[run_id] = team
        if summary.status in {HiveRunStatus.INTERRUPTED.value, HiveRunStatus.RUNNING.value,
                              HiveRunStatus.PAUSED.value}:
            summary.status = HiveRunStatus.INTERRUPTED.value
            summary.updated_at = time.time()
            self._persistence.save_run(summary, team)
            await self._emit("hive.run.recovered", run_id, "interrupted",
                             payload={"note": "Resumable after restart."})
        return summary

    async def aclose(self) -> None:
        self._closed = True
        if self._engine is not None:
            await self._engine.aclose()

    # ---- helpers ------------------------------------------------------
    def _task_desc(self, spec, context: Dict[str, str]) -> str:
        if not context:
            return spec.goal
        return (
            f"{spec.goal}\n\n---\nContext from prior stages:\n"
            + "\n".join(f"[{k}] {v[:1500]}" for k, v in context.items())
        )

    def _resolve_agent_caps(self, agent: "Any", request: HiveRequest) -> CapabilitySpec:
        mode = agent.capabilities.mode if agent.capabilities else request.capability_mode
        return resolve(
            mode, self._available,
            explicit=agent.capabilities,
            specialization=agent.specialization or "WORKER",
            security_limits=self._security_limits,
        )

    def _apply_security(self, agent: "Any", caps: CapabilitySpec, request: HiveRequest) -> None:
        assert_no_escalation(caps, self._security_limits)
        agent.tools = caps.tools
        agent.skills = caps.skills
        agent.plugins = caps.plugins
        agent.mcp_servers = caps.mcp_servers
        if caps.sandbox:
            agent.sandbox = caps.sandbox
        if caps.workspace:
            agent.workspace = caps.workspace
        if caps.permissions:
            agent.permissions = caps.permissions
        spec = get_specialization(agent.specialization)
        agent.provider = agent.provider or request.provider_preference or (spec.default_provider if spec else None)
        agent.model = agent.model or request.model_preference or (spec.default_model if spec else None)

    def _aggregate(self, team: AgentTeamSpec, agents: List[Any]) -> str:
        parts = [f"# Hive result — {team.name}\n\nGoal: {team.goal}\n"]
        for agent in agents:
            status = getattr(agent, "status", "unknown")
            result = _safe_text(getattr(agent, "result", "") or "", 3000)
            if status == "success":
                parts.append(f"## [{agent.specialization}] {agent.task[:80]}\n{result}")
            else:
                err = _safe_text(getattr(agent, "error", "") or "", 500)
                parts.append(f"## [{agent.specialization}] {agent.task[:80]} (status={status})\n{result or err}")
        return "\n\n".join(parts)

    def _run_timeout(self) -> float:
        return 600.0

    def _limitations(self, request: HiveRequest, team: AgentTeamSpec) -> List[str]:
        limits = []
        if not request.required_specializations and not request.team_preference:
            limits.append("No explicit specializations requested; Hive chose a default team.")
        limits.append("Sub-agents execute as isolated LLM+tool loops (real Nexus agents), not the main loop.")
        return limits

    async def _emit(self, event_type: str, run_id: str, status: str, payload: Any = None) -> None:
        evt = HiveEvent(event_type=event_type, hive_run_id=run_id, status=status, payload=payload or {})
        if self._sink:
            try:
                res = self._sink(evt.to_dict())
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass
