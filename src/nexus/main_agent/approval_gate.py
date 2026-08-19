"""Plan-level HITL approval gates — human-in-the-loop plan review.

Inspired by Devin's editable plans, Gemini CLI's plan-mode approval, and
LangGraph's interrupt/resume: plans are presented to the human for approval
before any tools execute. The human can approve, reject, or modify the plan.

Three approval modes:
- APPROVE: Present plan, wait for explicit approval (default in ask_all mode)
- AUTO: Execute without asking (auto mode)
- ASK: Ask only for high-risk plans (ai_decide mode, risk > threshold)

Approval is communicated via the canonical event system: the loop emits
a plan.approval_request event and waits for a plan.approval_response.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ApprovalMode(str, Enum):
    AUTO = "auto"           # Execute without asking
    ASK = "ask"             # Ask for every plan
    AI_DECIDE = "ai_decide" # Ask only for high-risk plans
    CHECKLIST = "checklist" # Pre-authorized whitelist only


class PlanDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    """A plan approval request sent to the human."""
    request_id: str
    plan_id: str
    goal: str
    steps: List[Dict[str, str]]  # [{"index": 1, "description": "..."}]
    risk_level: str  # "low", "medium", "high"
    timestamp: float = field(default_factory=time.time)
    timeout_seconds: float = 30.0  # How long to wait for approval


@dataclass
class ApprovalResponse:
    """Human response to a plan approval request."""
    request_id: str
    decision: PlanDecision
    modified_steps: Optional[List[Dict[str, str]]] = None  # If modified
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


class PlanApprovalGate:
    """Manages plan-level HITL approval.

    The gate intercepts plans produced by the planner and decides whether
    to present them to the human based on the approval mode and risk level.
    """

    def __init__(
        self,
        root_dir: str,
        *,
        mode: ApprovalMode = ApprovalMode.AI_DECIDE,
        risk_threshold: float = 0.7,
        timeout_seconds: float = 30.0,
    ):
        self.root_dir = root_dir
        self.mode = mode
        self._risk_threshold = risk_threshold
        self._timeout_seconds = timeout_seconds
        self._pending: Dict[str, ApprovalRequest] = {}
        self._responses: Dict[str, ApprovalResponse] = {}
        self._history: List[Dict[str, Any]] = []

    def assess_risk(self, steps: List[Dict[str, Any]], goal: str) -> str:
        """Assess the risk level of a plan.

        Returns "low", "medium", or "high" based on the tools and actions
        in the plan steps.
        """
        high_risk_tools = {
            "bash", "terminal", "shell", "run_command", "deleting",
            "git_ops", "deploy", "write_code",
        }
        medium_risk_tools = {
            "modifying", "creating", "file_ops", "write", "edit",
        }
        goal_lower = str(goal or "").lower()
        has_destructive = any(
            kw in goal_lower
            for kw in ("delete", "remove", "destroy", "drop", "purge", "reset")
        )

        risk_score = 0.0
        for step in steps:
            tool = str(step.get("tool") or "").lower()
            if tool in high_risk_tools:
                risk_score += 0.4
            elif tool in medium_risk_tools:
                risk_score += 0.2
            else:
                risk_score += 0.05
        if has_destructive:
            risk_score += 0.3

        if risk_score >= self._risk_threshold:
            return "high"
        if risk_score >= self._risk_threshold * 0.5:
            return "medium"
        return "low"

    async def gate(
        self,
        steps: List[Dict[str, Any]],
        goal: str,
        *,
        emit_request=None,
        wait_for_response=None,
    ) -> bool:
        """Consult the approval gate; returns True if the plan is approved.

        Args:
            steps: Raw planner step dicts.
            goal: The user's original request text.
            emit_request: Async callable to emit an approval_request event.
            wait_for_response: Async callable that returns an ApprovalResponse or None.

        Returns:
            True if the plan should proceed.
        """
        if self.mode == ApprovalMode.AUTO:
            return True

        risk_level = self.assess_risk(steps, goal)

        if self.mode == ApprovalMode.AI_DECIDE:
            if risk_level != "high":
                return True  # Auto-approve low/medium risk

        # Build approval request
        plan_steps = [
            {"index": i + 1, "description": str(s.get("description", f"Step {i + 1}"))}
            for i, s in enumerate(steps)
        ]
        request = ApprovalRequest(
            request_id=f"approval_{int(time.time() * 1000)}",
            plan_id=f"plan_{int(time.time())}",
            goal=goal,
            steps=plan_steps,
            risk_level=risk_level,
            timeout_seconds=self._timeout_seconds,
        )
        self._pending[request.request_id] = request

        # Emit the approval request event
        if callable(emit_request):
            try:
                await emit_request(request)
            except Exception as exc:
                logger.debug("approval request emit failed: %s", exc)

        # Wait for response
        if callable(wait_for_response):
            try:
                response = await wait_for_response(request)
                if response is not None:
                    self._responses[request.request_id] = response
                    self._history.append({
                        "request": request.__dict__,
                        "response": response.__dict__,
                    })
                    self._pending.pop(request.request_id, None)
                    return response.decision == PlanDecision.APPROVED
            except Exception as exc:
                logger.debug("approval wait failed: %s", exc)

        # Default: approve if no response mechanism (timeout → approve for auto modes)
        self._pending.pop(request.request_id, None)
        if self.mode == ApprovalMode.CHECKLIST:
            return False  # Checklist mode: deny if not in whitelist
        return True  # Default approve on timeout

    def pending_count(self) -> int:
        return len(self._pending)

    def history_count(self) -> int:
        return len(self._history)
