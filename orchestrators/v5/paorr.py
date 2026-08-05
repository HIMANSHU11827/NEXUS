"""PAORR Enhanced Loop - Enhanced Plan-Act-Observe-Reflect-Retry loop for NEXUS V5.

This module implements the enhanced PAORR loop with:
- Dynamic planning with hierarchical decomposition
- Alternative path generation
- Plan confidence scoring
- Parallel action orchestration
- Resource-aware scheduling
- Multi-modal observation
- Causal analysis and counterfactual reasoning
- Adaptive retry strategies

Plus V5 integration:
- Tool execution with ToolCall
- Tool registry integration
- Permission checking
- Risk scoring

Plus V5 core integration:
- External planner callback for real LLM-driven planning
- External tool executor callback for real tool execution
- Stage telemetry emitter (stage, action, status)

The external callbacks are injected by ``core``. When they are absent,
the loop degrades gracefully to heuristic planning and simulated execution
(without artificial delays).
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class PAORRPhase(str, Enum):
    """Phases of the PAORR loop."""
    PLAN = "plan"
    ACT = "act"
    OBSERVE = "observe"
    REFLECT = "reflect"
    RETRY = "retry"


@dataclass
class PlanStep:
    """Single step in a plan."""
    step_id: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    estimated_duration: float = 1.0
    confidence: float = 1.0
    resources: Dict[str, Any] = field(default_factory=dict)
    tool: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


@dataclass
class Plan:
    """Complete plan with multiple steps."""
    plan_id: str
    steps: List[PlanStep]
    confidence: float
    alternative_plans: List['Plan'] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    goal: str = ""
    approved: bool = True


@dataclass
class ActionResult:
    """Result of an action execution."""
    step_id: str
    success: bool
    output: str
    error: Optional[str] = None
    duration: float = 0.0
    resources_used: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    """Multi-modal observation."""
    observations: Dict[str, Any]
    anomalies: List[str] = field(default_factory=list)
    progress: float = 0.0
    resource_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class Reflection:
    """Reflection on execution results."""
    success: bool
    root_causes: List[str] = field(default_factory=list)
    counterfactuals: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ToolCall:
    """Minimal ToolCall shape, duck-typed compatible with ``core.ToolCall``.

    The core engine's ToolCall carries ``name``, ``params`` and ``call_id``.
    This module must NOT import from ``core`` (circular import risk),
    so this lightweight local shape is used instead. The ``tool_executor``
    callback only relies on the ``.name`` and ``.params`` attributes.
    """
    name: str
    params: Dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


class PAORREnhanced:
    """Enhanced PAORR loop implementation with V1 and V5 core integration.

    Accepts optional dependency callbacks injected by the loop:
    - ``planner``: real planning (PerceivedInput -> List[step dicts])
    - ``tool_executor``: real tool execution (ToolCall -> output text)
    - ``emitter``: stage telemetry (stage, action, status)
    """

    def __init__(
        self,
        root_dir: str,
        planner: Optional[Callable[[Any], Awaitable[List[Dict[str, Any]]]]] = None,
        tool_executor: Optional[Callable[[Any], Awaitable[str]]] = None,
        emitter: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
        approval_gate: Optional[Callable[[List[Dict[str, Any]], str], Awaitable[bool]]] = None,
        plan_emitter: Optional[Callable[[str, Optional[int], str, str], Awaitable[None]]] = None,
    ):
        """Initialize the PAORR loop.

        Args:
            root_dir: Project root directory.
            planner: Optional async callback ``(perceived) -> List[Dict]`` where
                each step dict is ``{"description": str, "tool": Optional[str],
                "params": Optional[Dict]}``. May be None.
            tool_executor: Optional async callback ``(ToolCall) -> str`` returning
                the tool output text or raising RuntimeError on failure. The
                ToolCall may be any object with ``.name`` and ``.params``
                attributes (duck typing). May be None.
            emitter: Optional async telemetry callback ``(stage, action, status)``
                for stage telemetry. May be None.
            approval_gate: Optional async callback ``(steps, goal) -> bool``
                consulted with the raw planner step dicts AFTER the external
                planner produced them and BEFORE the Plan is returned. A
                ``False`` decision marks the plan unapproved: ``execute``
                short-circuits with an empty plan and never runs tools. May
                be None.
            plan_emitter: Optional async callback
                ``(status, step_index, description, plan_id)`` receiving live
                per-step plan updates - "running" before each step,
                "done"/"failed" after it - plus one whole-plan "done" with
                ``step_index=None`` once all steps have run (``None`` is the
                total=None semantics: the signal covers the full plan, not a
                single step). May be None.
        """
        self.root_dir = root_dir
        self.planner = planner
        self.tool_executor = tool_executor
        self.emitter = emitter
        self.approval_gate = approval_gate
        self.plan_emitter = plan_emitter
        self.logger = logging.getLogger("nexus.v5.paorr")
        self.current_plan: Optional[Plan] = None
        self.execution_history: List[ActionResult] = []
        self.retry_count = 0
        self.max_retries = 3

        # V5 integration (used only as fallback when tool_executor is absent)
        self.tool_registry = None
        self._init_tool_registry()

    def _init_tool_registry(self):
        """Initialize tool registry from kernel (fallback only)."""
        try:
            from kernel import get_nexus_kernel
            kernel = get_nexus_kernel(root_dir=self.root_dir)
            self.tool_registry = kernel.tools
            self.logger.info("PAORR enhanced connected to tool registry")
        except Exception as e:
            self.logger.warning(f"Could not connect to tool registry: {e}")

    async def _emit(self, stage: str, action: str, status: str) -> None:
        """Emit stage telemetry if an emitter callback is configured.

        Args:
            stage: Telemetry stage (e.g. "planning", "acting", "verification").
            action: Telemetry action within the stage.
            status: Telemetry status (e.g. "running", "done").
        """
        if self.emitter is None:
            return
        try:
            await self.emitter(stage, action, status)
        except Exception as e:
            self.logger.warning(f"Emitter failed ({stage}/{action}/{status}): {e}")

    async def execute(self, perceived: Any) -> Dict[str, Any]:
        """Execute the enhanced PAORR loop.

        Args:
            perceived: PerceivedInput from perception layer

        Returns:
            Dict with execution results
        """
        self.logger.info(f"Starting PAORR loop for intent: {perceived.intent}")
        # PAORR instances are reused by the V5 core.  Retry state belongs to
        # one task, not to the lifetime of the process.
        self.retry_count = 0

        # PLAN phase
        await self._emit("planning", "planning", "running")
        plan = await self._plan(perceived)
        await self._emit("planning", "planning", "done")
        self.current_plan = plan

        # A plan rejected by the human gate must never execute tools.
        if getattr(plan, "approved", True) is False:
            self.logger.info("Plan rejected by user; no tools will run")
            await self._emit("planning", "denied", "done")
            return {
                "success": False,
                "plan": plan,
                "actions": [],
                "observation": {
                    "progress": 0.0,
                    "anomalies": ["plan not approved"],
                },
                "reflection": {
                    "success": False,
                    "root_causes": ["plan rejected by user"],
                    "improvements": [],
                },
                "retries": 0,
            }

        # ACT phase
        await self._emit("acting", "acting", "running")
        actions = await self._act(plan)
        await self._emit("acting", "acting", "done")

        # OBSERVE + REFLECT phases
        await self._emit("verification", "verifying", "running")
        observation = await self._observe(actions)
        reflection = await self._reflect(actions, observation)
        await self._emit("verification", "verifying", "done")

        # RETRY phase if needed
        if not reflection.success and self.retry_count < self.max_retries:
            self.retry_count += 1
            self.logger.info(f"Retrying (attempt {self.retry_count}/{self.max_retries})")
            return await self._retry(plan, reflection)

        return {
            "success": reflection.success,
            "plan": plan,
            "actions": actions,
            "observation": observation,
            "reflection": reflection,
            "retries": self.retry_count
        }

    async def _plan(self, perceived: Any) -> Plan:
        """Enhanced planning with hierarchical decomposition.

        Uses the external planner callback when available. If the model cannot
        produce a valid plan, returns an empty plan rather than inventing tool
        steps from keywords. Alternative plans are still generated for
        robustness. When an ``approval_gate`` callback is
        configured, the raw planner steps are offered to the gate first; a
        denial yields an empty, unapproved Plan that ``execute`` short-
        circuits before any tool runs.

        Args:
            perceived: PerceivedInput from perception layer

        Returns:
            Plan with alternative plans attached
        """
        self.logger.info("PLAN phase: Generating plan")

        goal = str(getattr(perceived, "original_input", "") or "").strip()

        # Generate main plan
        steps, steps_raw = await self._request_plan_steps(perceived)
        main_plan = Plan(
            plan_id=f"plan_{datetime.utcnow().timestamp()}",
            steps=steps,
            confidence=self._calculate_plan_confidence(steps)
        )
        main_plan.goal = goal

        approved = await self._run_approval_gate(steps_raw, goal)
        main_plan.approved = approved
        if not approved:
            self.logger.info("Plan denied by approval gate; execution will be skipped")
            main_plan.steps = []
            main_plan.confidence = 0.0

        # Generate alternative plans
        main_plan.alternative_plans = self._generate_alternative_plans(perceived, steps)

        return main_plan

    async def _request_plan_steps(
        self, perceived: Any
    ) -> Tuple[List[PlanStep], List[Dict[str, Any]]]:
        """Request plan steps from the discovered/model planner.

        Returns a ``(steps, steps_raw)`` pair: the built ``PlanStep`` list
        and the raw step dicts produced by the external planner (empty when
        the raw dicts feed the approval gate, which is defined against the
        planner's dict contract. An unavailable or invalid planner returns an
        empty plan; it never invents tool steps.

        Args:
            perceived: PerceivedInput from perception layer

        Returns:
            Tuple of (List[PlanStep], List[Dict])
        """
        if self.planner is not None:
            try:
                steps_raw = await self.planner(perceived)
                steps = self._build_steps_from_planner(steps_raw)
                if steps:
                    raw = steps_raw if isinstance(steps_raw, list) else []
                    return steps, list(raw)
                self.logger.warning("External planner returned no steps; no tools will run")
            except Exception as e:
                self.logger.warning(f"External planner failed ({e}); no tools will run")

        return [], []

    async def _run_approval_gate(self, steps_raw: List[Dict[str, Any]], goal: str) -> bool:
        """Consult the plan-level approval gate; fail-open on any error.

        A missing gate or a broken gate always resolves to approved so the
        approval plumbing can never freeze or break the loop.

        Args:
            steps_raw: Raw step dicts produced by the external planner.
            goal: The user's original request text.

        Returns:
            True when the plan is approved (or no gate is configured).
        """
        if self.approval_gate is None:
            return True
        try:
            return bool(await self.approval_gate(steps_raw, goal))
        except Exception as e:
            self.logger.warning(f"Plan approval gate failed open: {e}")
            return True

    def _build_steps_from_planner(self, steps_raw: Any) -> List[PlanStep]:
        """Convert raw planner step dicts into PlanStep objects.

        Args:
            steps_raw: List of step dicts, each ``{"description": str,
                "tool": Optional[str], "params": Optional[Dict]}``

        Returns:
            List of PlanStep objects
        """
        steps = []
        if not isinstance(steps_raw, list) or not steps_raw:
            return steps

        for i, raw in enumerate(steps_raw):
            if not isinstance(raw, dict):
                continue
            description = raw.get("description") or f"Step {i}"
            tool = raw.get("tool")
            params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
            steps.append(PlanStep(
                step_id=f"step_{i}",
                description=description,
                tool=tool,
                params=params,
                confidence=0.8 if tool else 0.9,
                estimated_duration=1.0,
                resources={"tool": tool, "params": params}
            ))
        return steps

    def _calculate_plan_confidence(self, steps: List[PlanStep]) -> float:
        """Calculate overall plan confidence.

        Handles both ``PlanStep`` objects and plain dicts so callers
        that pass dict-shaped steps do not crash with ``AttributeError``.
        """
        if not steps:
            return 0.0

        def _conf(step: Any) -> float:
            if isinstance(step, dict):
                return float(step.get("confidence", 1.0))
            return float(getattr(step, "confidence", 1.0))

        avg = sum(_conf(s) for s in steps) / len(steps)
        return min(avg, 1.0)

    def _generate_alternative_plans(self, perceived: Any, main_steps: List[PlanStep]) -> List[Plan]:
        """Generate alternative plans for robustness."""
        alternatives = []

        # Alternative 1: Parallel execution where possible
        parallel_steps = [
            PlanStep(
                step_id=s.step_id + "_parallel",
                description=s.description,
                dependencies=[],
                estimated_duration=s.estimated_duration * 0.7,
                tool=s.tool,
                params=s.params,
                resources={"tool": s.tool, "params": s.params}
            )
            for s in main_steps
        ]
        alternatives.append(Plan(
            plan_id="parallel_plan",
            steps=parallel_steps,
            confidence=self._calculate_plan_confidence(parallel_steps)
        ))

        return alternatives

    async def _act(self, plan: Plan) -> List[ActionResult]:
        """Enhanced action execution with parallel orchestration.

        When ``plan_emitter`` is configured, each step reports "running"
        before execution and "done"/"failed" after it; once every step has
        run, one whole-plan "done" update with ``step_index=None`` is
        emitted (``None`` carries the total=None semantics: the signal
        refers to the full plan, not to any single step).
        """
        self.logger.info("ACT phase: Executing plan")

        results = []
        index_by_id = {step.step_id: index for index, step in enumerate(plan.steps)}

        def _step_index(step: PlanStep) -> int:
            return index_by_id.get(step.step_id, 0)

        # Execute steps in dependency order
        # A failed step is terminal for this plan attempt.  It must be
        # recorded as finished so the scheduler cannot spin forever on the
        # same ready step; the RETRY phase is responsible for replanning.
        finished_steps = set()
        successful_steps = set()

        while len(finished_steps) < len(plan.steps):
            # Find steps whose dependencies are satisfied
            ready_steps = [
                step for step in plan.steps
                if step.step_id not in finished_steps
                and all(dep in successful_steps for dep in step.dependencies)
            ]

            if not ready_steps:
                # A failed dependency (or a malformed cycle) prevents the
                # remaining steps from running.  Preserve that fact as real
                # failed evidence instead of silently returning a partial
                # plan that looks complete.
                for step in plan.steps:
                    if step.step_id in finished_steps:
                        continue
                    results.append(ActionResult(
                        step_id=step.step_id,
                        success=False,
                        output="",
                        error="blocked by an unfinished dependency",
                    ))
                    finished_steps.add(step.step_id)
                    await self._call_plan_emitter(
                        "failed", _step_index(step), step.description, plan.plan_id
                    )
                break

            for step in ready_steps:
                await self._call_plan_emitter(
                    "running", _step_index(step), step.description, plan.plan_id
                )

            # Execute ready steps in parallel
            tasks = [self._execute_step(step) for step in ready_steps]
            step_results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, result in zip(ready_steps, step_results):
                if isinstance(result, Exception):
                    results.append(ActionResult(
                        step_id=step.step_id,
                        success=False,
                        output="",
                        error=str(result)
                    ))
                    await self._call_plan_emitter(
                        "failed", _step_index(step), step.description, plan.plan_id
                    )
                else:
                    results.append(result)
                    finished_steps.add(step.step_id)
                    if result.success:
                        successful_steps.add(step.step_id)
                    status = "done" if result.success else "failed"
                    await self._call_plan_emitter(
                        status, _step_index(step), step.description, plan.plan_id
                    )

        all_steps_finished = len(finished_steps) == len(plan.steps)
        any_failed = any(not action.success for action in results)
        if not all_steps_finished:
            plan_event_status, plan_status = "failed", "plan incomplete"
        elif any_failed:
            plan_event_status, plan_status = "failed", "plan failed"
        else:
            plan_event_status, plan_status = "done", "plan complete"
        await self._call_plan_emitter(plan_event_status, None, plan_status, plan.plan_id)

        self.execution_history.extend(results)
        return results

    async def _call_plan_emitter(
        self,
        status: str,
        step_index: Optional[int],
        description: str,
        plan_id: str,
    ) -> None:
        """Forward a live plan update to the plan_emitter callback, guarded.

        Args:
            status: "running", "done" or "failed".
            step_index: Index of the step this update refers to; ``None``
                means the whole plan (the plan-level completion signal).
            description: Human-readable step description (or a plan summary
                for the plan-level update).
            plan_id: Id of the plan being executed.
        """
        if self.plan_emitter is None:
            return
        try:
            await self.plan_emitter(status, step_index, description, plan_id)
        except Exception as e:
            self.logger.warning(f"Plan emitter failed ({status}/{description}): {e}")

    async def _execute_step(self, step: PlanStep) -> ActionResult:
        """Execute a single plan step with real tool execution.

        Priority:
        1. ``tool_executor`` callback: real tool execution for tool steps;
           reasoning-only steps are recorded separately and never claim an
           external action was executed.
        2. Kernel tool registry (fallback when no executor is provided).
        3. No simulated execution: unavailable execution is reported as a
           structured failure.

        Args:
            step: PlanStep to execute

        Returns:
            ActionResult with success/output/error/duration
        """
        self.logger.debug(f"Executing step: {step.step_id}")

        start_time = datetime.utcnow()

        tool = step.tool or step.resources.get("tool")
        params = step.params or step.resources.get("params") or {}
        output = ""
        error = None
        success = False
        # This path must never describe work as simulated.  If no real
        # executor is available, the result below is an explicit failure.
        execution_mode = "unavailable"

        if self.tool_executor is not None:
            if tool:
                # Real tool execution via the loop's tool executor.
                execution_mode = "tool"
                call = ToolCall(name=tool, params=params or {})
                try:
                    raw_output = await self.tool_executor(call)
                    if isinstance(raw_output, dict) and "success" in raw_output:
                        success = bool(raw_output.get("success"))
                        output = str(raw_output.get("output") or "")[:4000]
                        error = str(raw_output.get("error") or "") or None
                    elif hasattr(raw_output, "success"):
                        success = bool(getattr(raw_output, "success", False))
                        output = str(getattr(raw_output, "output", "") or "")[:4000]
                        error = str(getattr(raw_output, "error", "") or "") or None
                    else:
                        # A plain return value is evidence that the callback
                        # completed, but not a structured failure.
                        output = str(raw_output)[:4000]
                        success = True
                except Exception as e:
                    # A tool step that fails must never report success.
                    output = ""
                    error = str(e)
                    success = False
            else:
                # Reasoning is not an external action. Keep it visible, but do
                # not present it as completed work or verified evidence.
                execution_mode = "reasoning"
                output = f"Reasoning recorded; no external action executed: {step.description}"
                success = True
        else:
            # The registry is the only valid fallback. Never fabricate output
            # merely because a tool name exists in the registry.
            if tool and self.tool_registry is not None:
                execution_mode = "tool"
                try:
                    result = await self.tool_registry.execute(tool, **params)
                    output = str(getattr(result, "output", "") or "")[:4000]
                    error = str(getattr(result, "error", "") or "") or None
                    success = bool(getattr(result, "success", False))
                except Exception as e:
                    output = f"Tool execution error: {e}"
                    success = False
            else:
                execution_mode = "unavailable"
                output = ""
                error = "no tool executor or registry is available"
                success = False

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        return ActionResult(
            step_id=step.step_id,
            success=success,
            output=output,
            error=error,
            duration=duration,
            resources_used={
                "cpu": 0.5,
                "memory": 100,
                "execution_mode": execution_mode,
                "tool": tool if tool else None,
                "verified": execution_mode == "tool" and success,
            }
        )

    async def _observe(self, actions: List[ActionResult]) -> Observation:
        """Enhanced observation with multi-modal input.

        Resource metrics are heuristic estimates derived from real execution
        data: ``api_calls`` counts the tool-executed steps, while cpu/memory
        usage scale heuristically with the measured total duration.

        Args:
            actions: List of ActionResult from the ACT phase

        Returns:
            Observation with progress, anomalies and resource metrics
        """
        self.logger.info("OBSERVE phase: Observing results")

        observations = {
            "actions_completed": sum(1 for a in actions if a.success),
            "actions_failed": sum(1 for a in actions if not a.success),
            "total_duration": sum(a.duration for a in actions),
        }

        # Detect anomalies
        anomalies = []
        if observations["actions_failed"] > 0:
            anomalies.append(f"{observations['actions_failed']} actions failed")

        # Calculate progress
        progress = observations["actions_completed"] / len(actions) if actions else 0.0

        # Resource metrics (heuristics derived from measured durations)
        tool_steps = [
            a for a in actions
            if a.resources_used.get("execution_mode") == "tool"
        ]
        total_duration = observations["total_duration"]
        resource_metrics = {
            "cpu_usage": min(0.6 + total_duration * 0.01, 1.0),  # heuristic
            "memory_usage": min(0.4 + total_duration * 0.005, 1.0),  # heuristic
            "api_calls": len(tool_steps)
        }

        return Observation(
            observations=observations,
            anomalies=anomalies,
            progress=progress,
            resource_metrics=resource_metrics
        )

    async def _reflect(self, actions: List[ActionResult], observation: Observation) -> Reflection:
        """Enhanced reflection with causal analysis."""
        self.logger.info("REFLECT phase: Reflecting on results")

        success = observation.progress >= 1.0 and len(observation.anomalies) == 0

        root_causes = []
        if not success:
            if observation.anomalies:
                root_causes.extend(observation.anomalies)

        # Counterfactual reasoning
        counterfactuals = []
        if not success:
            counterfactuals.append("If we had used alternative plan, might have succeeded")

        # Improvements
        improvements = []
        if observation.progress < 1.0:
            improvements.append("Increase parallel execution for faster completion")

        confidence = observation.progress

        return Reflection(
            success=success,
            root_causes=root_causes,
            counterfactuals=counterfactuals,
            improvements=improvements,
            confidence=confidence
        )

    async def _retry(self, plan: Plan, reflection: Reflection) -> Dict[str, Any]:
        """Adaptive retry with different strategy."""
        self.logger.info("RETRY phase: Retrying with adaptive strategy")

        # Try alternative plan if available
        if plan.alternative_plans:
            alternative = plan.alternative_plans[0]
            self.logger.info(f"Using alternative plan: {alternative.plan_id}")

            # Execute alternative
            actions = await self._act(alternative)
            observation = await self._observe(actions)
            reflection = await self._reflect(actions, observation)

            return {
                "success": reflection.success,
                "plan": alternative,
                "actions": actions,
                "observation": observation,
                "reflection": reflection,
                "retries": self.retry_count
            }

        # Otherwise retry with modified parameters
        return {
            "success": False,
            "error": "No alternative plans available",
            "retries": self.retry_count
        }
