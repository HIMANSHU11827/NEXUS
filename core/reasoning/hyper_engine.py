"""Planner/executor/critic/verifier reasoning skeleton.

This is deterministic scaffolding for reliable agent loops. It does not pretend
to be magic chain-of-thought. It produces explicit plans, uncertainty scores,
verification checks, and replan triggers that the main loop or swarm can consume.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Dict, List


@dataclass
class ReasoningStep:
    id: str
    objective: str
    suggested_tool: str
    risk: str = "low"
    verifier: str = ""
    status: str = "planned"


@dataclass
class ReasoningPlan:
    task: str
    steps: List[ReasoningStep] = field(default_factory=list)
    uncertainty: float = 0.0
    critiques: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["steps"] = [asdict(step) for step in self.steps]
        return data


class HyperReasoningEngine:
    """Creates explicit, verifiable plans for autonomous work."""

    def plan(self, task: str) -> ReasoningPlan:
        task_l = task.lower()
        steps: List[ReasoningStep] = []

        steps.append(ReasoningStep("understand", "Map relevant files and existing behavior", "repo_map", verifier="source files identified"))
        if any(k in task_l for k in ["bug", "debug", "crash", "fail", "fix"]):
            steps.append(ReasoningStep("reproduce", "Reproduce or inspect the failure", "bash", risk="medium", verifier="failure observed or logs inspected"))
        if any(k in task_l for k in ["implement", "fix", "refactor", "add", "code"]):
            steps.append(ReasoningStep("edit", "Apply the smallest coherent code change", "file_edit", risk="medium", verifier="syntax check passes"))
        if any(k in task_l for k in ["security", "upload", "auth", "api"]):
            steps.append(ReasoningStep("security", "Check API/path/auth/security boundaries", "grep", verifier="risk cases covered"))
        steps.append(ReasoningStep("verify", "Run targeted tests/builds", "bash", verifier="tests/build pass"))
        steps.append(ReasoningStep("summarize", "Summarize changes, remaining risks, and evidence", "final", verifier="evidence cited"))

        plan = ReasoningPlan(task=task, steps=steps, uncertainty=self.estimate_uncertainty(task, steps))
        plan.critiques = self.critique(plan)
        return plan

    def estimate_uncertainty(self, task: str, steps: List[ReasoningStep]) -> float:
        uncertainty = 0.2
        if len(task) < 25:
            uncertainty += 0.25
        if re.search(r"\b(all|everything|entire|massive|production-grade)\b", task.lower()):
            uncertainty += 0.25
        if len(steps) > 5:
            uncertainty += 0.1
        return min(0.95, uncertainty)

    def critique(self, plan: ReasoningPlan) -> List[str]:
        critiques: List[str] = []
        if plan.uncertainty > 0.6:
            critiques.append("High uncertainty: narrow scope or gather more repo evidence before broad edits.")
        if not any(step.suggested_tool == "bash" for step in plan.steps):
            critiques.append("No execution verification step found.")
        if any(step.risk in {"high", "critical"} for step in plan.steps):
            critiques.append("High-risk step requires rollback/snapshot planning.")
        return critiques

    def should_replan(self, plan: ReasoningPlan, observations: List[str]) -> bool:
        joined = "\n".join(observations).lower()
        if any(marker in joined for marker in ["traceback", "failed", "error", "timeout", "permission denied"]):
            return True
        completed = sum(1 for step in plan.steps if step.status == "done")
        return completed == 0 and len(observations) > 2
