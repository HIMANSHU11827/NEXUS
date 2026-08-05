"""V5ActiveLoop — Hive-powered agentic loop control (Phase 3, items #21–#33).

This mixin adds three agentic capabilities to ``NexusLoopV5`` using the
existing ``NexusHiveEngine`` (no new agent classes):

1. **Plan-level gating**: before executing a high-risk plan, spawn
   REVIEWER + PLANNER sub-agents to audit it.  Emit a ``plan.proposed``
   event; block or modify the plan when concerns are found.

2. **Hive-based bounded self-repair**: on verifier failure, spawn
   ENGINEER + TESTER sub-agents to propose a repair plan, then retry
   within a max repair budget.

3. **Stall-driven replan**: when ``_detect_stall`` fires, let the PLANNER
   sub-agent propose an alternative plan instead of repeating.

All features are gated by the existing ``NEXUS_HIVE`` env flag and an
``NEXUS_V5_ACTIVE_MODE`` toggle.  Every method degrades gracefully.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_HIGH_RISK_TOOLS = frozenset({
    "bash", "run_command", "terminal", "shell", "execute_command",
    "deleting", "modifying", "git_ops",
})
_PLAN_RISK_THRESHOLD = 1


class V5ActiveLoop:
    """Mixin: Hive-powered plan gating, self-repair, and task ledger."""

    # ── FEATURE TOGGLES (items #32–#33) ─────────────────────────────────

    def _active_mode_enabled(self) -> bool:
        """True when ``NEXUS_HIVE`` is on and active mode is not disabled."""
        try:
            hive_on = str(os.environ.get("NEXUS_HIVE", "0") or "0").lower() in (
                "1", "true", "yes", "on",
            )
            if not hive_on:
                return False
            active = str(
                os.environ.get("NEXUS_V5_ACTIVE_MODE", "true") or "true"
            ).lower()
            return active in ("1", "true", "yes", "on")
        except Exception:
            return False

    def _max_repair_attempts(self) -> int:
        """Max Hive self-repair attempts (env-overridable, default 2)."""
        try:
            return max(1, int(os.environ.get("NEXUS_V5_MAX_REPAIR", "2")))
        except Exception:
            return 2

    # ── TASK LEDGER (items #29–#31) ─────────────────────────────────────

    def _init_task_ledger(self) -> None:
        """Initialize or reset the per-turn task ledger."""
        self._task_ledger: List[Dict[str, Any]] = []
        self._repair_count: int = 0

    def _ledger_record(self, step: Dict[str, Any], success: bool) -> None:
        """Record one attempted step in the task ledger."""
        try:
            if not hasattr(self, "_task_ledger") or self._task_ledger is None:
                self._init_task_ledger()
            self._task_ledger.append({
                "description": str(step.get("description") or ""),
                "tool": str(step.get("tool") or ""),
                "success": success,
            })
        except Exception:
            logger.debug("V5ActiveLoop: suppressed error", exc_info=True)

    def _ledger_history(self) -> List[Dict[str, Any]]:
        """Return the current task ledger (empty list when not initialized)."""
        try:
            ledger = getattr(self, "_task_ledger", None)
            if isinstance(ledger, list):
                return ledger
        except Exception:
            logger.debug("V5ActiveLoop: suppressed error", exc_info=True)
        return []

    # ── PLAN-LEVEL GATING (items #21–#25) ───────────────────────────────

    def _classify_plan_risk(
        self, steps: List[Dict[str, Any]]
    ) -> Tuple[int, List[str]]:
        """Deterministic risk classification: returns (risk_score, concerns)."""
        risk = 0
        risky: List[str] = []
        try:
            for step in steps:
                tool = str(step.get("tool") or "").strip().lower()
                if tool in _HIGH_RISK_TOOLS:
                    risk += 1
                    risky.append(
                        f"step '{step.get('description', tool)}' uses "
                        f"high-risk tool '{tool}'"
                    )
        except Exception:
            logger.debug("V5ActiveLoop: suppressed error", exc_info=True)
        return risk, risky

    async def _hive_review_plan(
        self, steps: List[Dict[str, Any]], user_input: str
    ) -> Dict[str, Any]:
        """Spawn REVIEWER + PLANNER sub-agents to audit a plan.

        Falls back to the deterministic risk classifier when Hive is off.
        """
        if not self._active_mode_enabled():
            risk, risky = self._classify_plan_risk(steps)
            return {"approved": risk < _PLAN_RISK_THRESHOLD,
                    "concerns": risky, "modified_steps": steps}
        try:
            hive_engine = self._hive_engine() if hasattr(self, "_hive_engine") else None
            if hive_engine is None:
                risk, risky = self._classify_plan_risk(steps)
                return {"approved": risk < _PLAN_RISK_THRESHOLD,
                        "concerns": risky, "modified_steps": steps}

            llm = self._hive_llm_call() if hasattr(self, "_hive_llm_call") else None
            if llm is not None:
                try:
                    hive_engine.set_llm_call(llm)
                except Exception:
                    logger.debug("V5ActiveLoop: suppressed error", exc_info=True)

            plan_text = json.dumps(
                [{"description": s.get("description"), "tool": s.get("tool"),
                  "params": s.get("params")} for s in steps],
                ensure_ascii=False, default=str,
            )[:4000]

            tasks: List[Tuple[str, str]] = [
                ("You are the safety REVIEWER. Audit this plan for risks. "
                 "Reply:\nVERDICT: APPROVE or BLOCK\nCONCERNS: <comma-separated>\n"
                 f"\nUser task: {user_input[:500]}\nPlan: {plan_text}", "REVIEWER"),
                ("You are the PLANNER. Check if this plan is efficient. "
                 "Reply:\nVERDICT: APPROVE or MODIFY\nSUGGESTION: <one sentence>\n"
                 f"\nUser task: {user_input[:500]}\nPlan: {plan_text}", "PLANNER"),
            ]
            hive_id, agents = await hive_engine.spawn_hive(
                tasks, parent_run_id=getattr(self, "_current_turn_id", "plan_gate"),
            )
            concerns: List[str] = []
            approved = True
            for agent in agents:
                result = str(agent.result or "")
                if "BLOCK" in result.upper():
                    approved = False
                for line in result.splitlines():
                    if line.strip().lower().startswith("concerns:"):
                        c = line.split(":", 1)[1].strip()
                        if c and c.lower() not in ("none", "n/a", ""):
                            concerns.append(c)
            return {"approved": approved, "concerns": concerns,
                    "modified_steps": steps}
        except Exception as e:
            logger.warning("V5ActiveLoop: hive plan review failed: %s", e)
            risk, risky = self._classify_plan_risk(steps)
            return {"approved": risk < _PLAN_RISK_THRESHOLD,
                    "concerns": risky, "modified_steps": steps}

    async def _gate_plan(
        self, steps: List[Dict[str, Any]], user_input: str
    ) -> List[Dict[str, Any]]:
        """Gate a plan through Hive review before execution.

        Emits ``plan.proposed``; when blocked returns [] (chat fallback).
        """
        try:
            if not steps:
                return steps
            emit = getattr(self, "_emit_runtime_event", None)
            if callable(emit):
                try:
                    await emit("plan.proposed", "Plan proposed for review",
                               "pending", payload={"steps": len(steps)})
                except Exception:
                    logger.debug("V5ActiveLoop: suppressed error", exc_info=True)
            review = await self._hive_review_plan(steps, user_input)
            if not review.get("approved", True):
                concerns = review.get("concerns", [])
                self.logger.warning(
                    "V5ActiveLoop: plan blocked — concerns: %s",
                    "; ".join(concerns[:3]))
                if callable(emit):
                    try:
                        await emit("plan.blocked", "Plan blocked by review",
                                   "blocked", payload={"concerns": concerns[:5]})
                    except Exception:
                        logger.debug("V5ActiveLoop: suppressed error", exc_info=True)
                return []
            return review.get("modified_steps", steps)
        except Exception as e:
            logger.warning("V5ActiveLoop: plan gating failed: %s", e)
            return steps

    # ── HIVE-BASED SELF-REPAIR (items #26–#28) ──────────────────────────

    async def _hive_self_repair(
        self, result: Dict[str, Any], perceived: Any
    ) -> Optional[List[Dict[str, Any]]]:
        """Spawn ENGINEER + TESTER to propose a repair plan on failure.

        Returns new plan steps, or None when repair is not possible.
        """
        try:
            if not self._active_mode_enabled():
                return None
            repair_count = getattr(self, "_repair_count", 0)
            max_attempts = self._max_repair_attempts()
            if repair_count >= max_attempts:
                self.logger.info(
                    "V5ActiveLoop: repair budget exhausted (%d/%d)",
                    repair_count, max_attempts)
                return None
            self._repair_count = repair_count + 1

            hive_engine = self._hive_engine() if hasattr(self, "_hive_engine") else None
            if hive_engine is None:
                return None
            llm = self._hive_llm_call() if hasattr(self, "_hive_llm_call") else None
            if llm is not None:
                try:
                    hive_engine.set_llm_call(llm)
                except Exception:
                    logger.debug("V5ActiveLoop: suppressed error", exc_info=True)

            evidence_fn = getattr(self, "_failure_evidence", None)
            evidence = ""
            if callable(evidence_fn):
                evidence = evidence_fn(result)[:2000]
            user_input = str(getattr(perceived, "original_input", "") or "")[:500]

            tasks: List[Tuple[str, str]] = [
                ("You are the ENGINEER. The previous attempt failed. "
                 "Propose a repair plan as JSON steps. "
                 "Reply:\nREPAIR_PLAN: <json list of steps>\n"
                 f"\nTask: {user_input}\nFailure evidence:\n{evidence}", "ENGINEER"),
                ("You are the TESTER. Diagnose if this is a real bug or "
                 "transient error. Reply:\nDIAGNOSIS: <one sentence>\n"
                 f"IS_TRANSIENT: yes or no\n"
                 f"\nTask: {user_input}\nFailure evidence:\n{evidence}", "TESTER"),
            ]
            hive_id, agents = await hive_engine.spawn_hive(
                tasks, parent_run_id=getattr(self, "_current_turn_id", "self_repair"),
            )
            for agent in agents:
                if agent.persona == "ENGINEER":
                    text = str(agent.result or "")
                    for line in text.splitlines():
                        if line.strip().lower().startswith("repair_plan:"):
                            json_part = line.split(":", 1)[1].strip()
                            try:
                                parsed = json.loads(json_part)
                                if isinstance(parsed, list) and parsed:
                                    return parsed
                            except Exception:
                                logger.debug("V5ActiveLoop: suppressed error", exc_info=True)
            return None
        except Exception as e:
            logger.warning("V5ActiveLoop: hive self-repair failed: %s", e)
            return None

    # ── STALL-DRIVEN REPLAN (items #30–#31) ─────────────────────────────

    async def _hive_replan_on_stall(
        self, perceived: Any
    ) -> Optional[List[Dict[str, Any]]]:
        """When stall is detected, ask PLANNER sub-agent for a new plan.

        Uses ``_detect_stall`` from ``V5ParallelExecutor``.
        """
        try:
            if not self._active_mode_enabled():
                return None
            history = self._ledger_history()
            detect = getattr(self, "_detect_stall", None)
            if not callable(detect) or not detect(history):
                return None

            self.logger.info("V5ActiveLoop: stall detected — requesting replan")
            hive_engine = self._hive_engine() if hasattr(self, "_hive_engine") else None
            if hive_engine is None:
                return None
            llm = self._hive_llm_call() if hasattr(self, "_hive_llm_call") else None
            if llm is not None:
                try:
                    hive_engine.set_llm_call(llm)
                except Exception:
                    logger.debug("V5ActiveLoop: suppressed error", exc_info=True)

            user_input = str(getattr(perceived, "original_input", "") or "")[:500]
            stalled_summary = "\n".join(
                f"- {h.get('description', '?')} (tool={h.get('tool', '?')}, "
                f"success={h.get('success')})"
                for h in history[-5:]
            )[:1500]

            tasks: List[Tuple[str, str]] = [
                ("You are the PLANNER. Previous attempts stalled. "
                 "Create a DIFFERENT plan that avoids the failed steps. "
                 "Reply:\nNEW_PLAN: <json list of steps>\n"
                 f"\nTask: {user_input}\nStalled history:\n{stalled_summary}",
                 "PLANNER"),
            ]
            hive_id, agents = await hive_engine.spawn_hive(
                tasks, parent_run_id=getattr(self, "_current_turn_id", "replan"),
            )
            for agent in agents:
                text = str(agent.result or "")
                for line in text.splitlines():
                    if line.strip().lower().startswith("new_plan:"):
                        json_part = line.split(":", 1)[1].strip()
                        try:
                            parsed = json.loads(json_part)
                            if isinstance(parsed, list) and parsed:
                                return parsed
                        except Exception:
                            logger.debug("V5ActiveLoop: suppressed error", exc_info=True)
            return None
        except Exception as e:
            logger.warning("V5ActiveLoop: hive replan failed: %s", e)
            return None

