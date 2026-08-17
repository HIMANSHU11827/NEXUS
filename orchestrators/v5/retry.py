"""V5RetryPolicy - tool-enforcement retries for the V5 planner.

Ported from the unified loop's tool-enforcement ladder (``orchestrators/loop.py``
lines 916-968), ``_tool_enforcement_message`` (line 1806), and the intent
gating of ``_requires_real_tooling`` (line 1782): when a task almost certainly
requires real tool execution but the planner returned an empty plan, a
TOOL_ENFORCEMENT system message is appended and planning is retried using the
same message construction as ``_llm_plan``.

Mixed into ``NexusLoopV5``; no imports from ``core`` (avoids circular
imports). The host must provide ``_llm_plan``, ``_planning_system_prompt``,
``_parse_plan_json``, ``_plan_from_text``, ``_safe_model_call``,
``_repair_instruction``, ``self.tool_registry`` and ``self.logger``.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Dict, List


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


class V5RetryPolicy:
    """Tool-enforcement retry ladder for LLM plan generation."""

    _TOOL_INTENTS = {
        "read", "write", "edit", "file", "search", "web", "code",
        "test", "command", "git", "research", "tool",
    }
    _ACTION_VERBS = (
        "read", "create", "write", "update", "edit", "delete", "search",
        "find", "run", "execute", "list", "install", "test", "fix",
        "analyze file", "summarize",
    )
    _FILE_NOUNS = ("file", "code", "repo", "script", "project")

    # ────────────────────────────────────────────────────────────────────────
    # INTENT GATING (V5: loop._requires_real_tooling, line 1782)
    # ────────────────────────────────────────────────────────────────────────

    def _requires_real_tooling(self, perceived: Any) -> bool:
        """True when the task almost certainly needs real tool execution."""
        # Accept both the historical PerceivedInput object and the public
        # string form used by compatibility callers.  The live V5 direct loop
        # still lets the model choose the actual tool; this predicate only
        # decides whether an execution-capable path is warranted.
        if isinstance(perceived, str):
            intent = ""
            text = perceived.lower()
        else:
            intent = getattr(getattr(perceived, "intent", None), "value", "chat")
            try:
                text = str(getattr(perceived, "original_input", "")).lower()
            except Exception:
                text = ""
        if intent in self._TOOL_INTENTS:
            self.logger.debug(
                "[ENFORCEMENT] intent '%s' requires real tooling", intent
            )
            return True
        action_signals = self._ACTION_VERBS + (
            "build", "make", "code", "implement", "debug", "inspect", "compare", "review",
            "check", "design", "generate", "download", "deploy", "configure",
            "research", "install", "remove", "delete",
        )
        nouns = self._FILE_NOUNS + ("website", "game", "report", "agents", "dependency", "file", "terminal", "command", "web", "news", "old")
        if any(verb in text for verb in action_signals) and any(noun in text for noun in nouns):
            self.logger.debug(
                "[ENFORCEMENT] action verbs + file nouns in task text "
                "require real tooling"
            )
            return True
        self.logger.debug(
            "[ENFORCEMENT] task does not require real tooling (intent=%s)", intent
        )
        return False

    # ────────────────────────────────────────────────────────────────────────
    # ENFORCEMENT MESSAGE (V5: loop._tool_enforcement_message, line 1806)
    # ────────────────────────────────────────────────────────────────────────

    def _tool_enforcement_message(self, task: str) -> str:
        """System message forcing tool steps for a tool-requiring task."""
        return (
            "[TOOL_ENFORCEMENT] The task requires real tool execution against "
            f"the project: {task}\n"
            "The plan MUST contain concrete tool steps. Use ONLY the tools "
            "provided in the schemas above; never invent tool names. Never "
            "claim that tools are unavailable or that no tool fits - real "
            "tools exist and must be chosen. "
            "Return ONLY the JSON plan object with the exact shape "
            '{"steps": [{"description": "...", "tool": "<name>", '
            '"params": {...}}]}.'
        )

    # ────────────────────────────────────────────────────────────────────────
    # RETRY LADDER (V5: loop.py lines 916-968)
    # ────────────────────────────────────────────────────────────────────────

    async def _llm_plan_with_enforcement(
        self, perceived: Any, max_retries: int = 2
    ) -> List[Dict[str, Any]]:
        """Plan with tool-enforcement retries when the task needs tools.

        First attempts plain ``_llm_plan``; on an empty result for a
        tool-requiring task, retries with the enforcement message appended to
        the same system/user message construction ``_llm_plan`` uses.
        """
        try:
            steps = await self._llm_plan(perceived)
        except Exception as exc:
            self.logger.error("[ENFORCEMENT] initial plan failed: %s", exc)
            steps = []
        if steps:
            return steps
        if not self._requires_real_tooling(perceived):
            return steps

        task = str(getattr(perceived, "original_input", ""))
        intent = getattr(getattr(perceived, "intent", None), "value", "chat")
        backoff_base = _env_float("NEXUS_PLAN_RETRY_BACKOFF_BASE", 0.3, 0.0)
        backoff_max = _env_float("NEXUS_PLAN_RETRY_BACKOFF_MAX", 2.0, 0.0)
        for attempt in range(1, max_retries + 1):
            self.logger.info(
                f"[ENFORCEMENT] retry {attempt}/{max_retries} for task "
                f"requiring real tooling: {task[:120]}"
            )
            if attempt > 1 and (backoff_base > 0 or backoff_max > 0):
                delay = min(backoff_max, backoff_base * (2.0 ** (attempt - 1)))
                delay *= 1.0 + random.uniform(-0.25, 0.25)
                self.logger.info(
                    "[ENFORCEMENT] backing off %.2fs before retry %d",
                    delay, attempt,
                )
                await asyncio.sleep(delay)
            messages = [
                {"role": "system", "content": self._planning_system_prompt()},
                {
                    "role": "user",
                    "content": (
                        f"Task: {task}\n"
                        f"Detected intent: {intent}\n"
                        "Return ONLY the JSON plan."
                    ),
                },
                {
                    "role": "system",
                    "content": self._tool_enforcement_message(task),
                },
            ]
            try:
                raw = await self._safe_model_call(
                    messages,
                    timeout=90.0,
                    tools=self._get_tool_schemas(top_k=100),
                    tool_choice="auto",
                )
            except Exception as exc:
                self.logger.error(
                    "[ENFORCEMENT] retry %d model call failed: %s", attempt, exc
                )
                continue
            steps = self._parse_plan_json(raw)
            if not steps:
                steps = self._plan_from_text(raw, task)
            if steps:
                self.logger.info(
                    "[ENFORCEMENT] retry %d produced %d step(s)",
                    attempt,
                    len(steps),
                )
                return steps
        return []

    # ────────────────────────────────────────────────────────────────────────
    # SELF-REPAIR (roadmap item 3: corrective replan on verification failure)
    # ────────────────────────────────────────────────────────────────────────

    async def _repair_plan(
        self, perceived: Any, result: Dict[str, Any], attempt: int
    ) -> List[Dict[str, Any]]:
        """Corrective replan after verification failure (caller bounds it).

        Re-calls the planner with the failure evidence appended to the same
        system/user message construction ``_llm_plan`` uses, so errors are
        routed to the model in-band and the corrective plan fixes the root
        causes. Falls back to plain ``_llm_plan`` when the reply cannot be
        parsed. Never raises; returns [] on any failure.
        """
        instruction = self._repair_instruction(result, perceived)
        if not instruction:
            self.logger.debug("[REPAIR] no failure evidence; skipping replan")
            return []
        task = str(getattr(perceived, "original_input", "") or "")
        intent = getattr(getattr(perceived, "intent", None), "value", "chat")
        messages = [
            {"role": "system", "content": self._planning_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"Task: {task}\n"
                    f"Detected intent: {intent}\n"
                    "Return ONLY the JSON plan."
                    f"{instruction}"
                ),
            },
        ]
        try:
            raw = await self._safe_model_call(
                messages,
                timeout=90.0,
                tools=self._get_tool_schemas(top_k=100),
                tool_choice="auto",
            )
        except Exception as exc:
            self.logger.error(
                "[REPAIR] attempt %d model call failed: %s", attempt, exc
            )
            return []
        steps = self._parse_plan_json(raw)
        if steps:
            self.logger.info(
                "[REPAIR] attempt %d produced %d step(s)", attempt, len(steps)
            )
            return steps
        self.logger.warning(
            "[REPAIR] attempt %d plan unparseable; falling back to plain planning",
            attempt,
        )
        try:
            return await self._llm_plan(perceived)
        except Exception as exc:
            self.logger.error("[REPAIR] fallback planning failed: %s", exc)
            return []
