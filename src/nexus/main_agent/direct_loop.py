"""Bounded transcript-driven model/tool loop for V5."""

from __future__ import annotations

import asyncio
import json
import hashlib
import os
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from models.providers.core.reliability import redact_secrets
from reliability.failure import FailureClass
from .token_usage import (
    TokenUsage,
    estimate_cost_usd,
    estimate_messages_tokens,
    normalize_usage,
)

# Tool results larger than this are archived to a session file and replaced
# in the model transcript by a short preview. Keep the archive path under
# the project root so a future ``continue`` can read the full result.
MAX_TOOL_RESULT_CHARS = 50_000
TOOL_RESULT_PREVIEW_CHARS = 2_000
RECENT_MESSAGES_LIMIT = 12

# ── Explicit capability intent → registered tool mapping ────────────────────
# When the user explicitly names a capability (e.g. "use web search", "search
# the web", "latest news"), the loop must EXECUTE that capability rather than
# accept a prose narration. These patterns map natural-language intent to a
# concrete registered tool name plus an argument builder, so the loop can force
# or synthesize the tool call deterministically. Matching is by substring/word
# only; the tool is only used if it is actually present in the live schema.
CAPABILITY_INTENT_PATTERNS: List[Tuple[str, "re.Pattern[str]", str]] = [
    # (tool_name, compiled_pattern, arg_key)
    ("web_search", re.compile(
        r"\b(?:use|run|call|invoke|do|perform|with|via|using)\s+(?:the\s+)?"
        r"web[ _-]?search\b|\bweb[ _-]?search\b|\bsearch\s+(?:the\s+)?web\b|"
        r"\b(?:latest|today'?s|current|recent|breaking|world)\s+news\b|"
        r"\bnews\s+(?:about|on|regarding|headlines?)\b|\bsearch\s+for\s+news\b|"
        r"\bgoogle\s+(?:it|that|for)\b|\bbrowse\s+(?:the\s+)?web\b|"
        r"\blook\s+(?:it|that)\s+up\s+(?:online|on\s+the\s+web)\b",
        re.IGNORECASE,
    ), "query"),
    ("web_fetch", re.compile(
        r"\b(?:fetch|open|get|read|visit|load)\s+(?:the\s+)?(?:url|link|page|website)\b|"
        r"\bopen\s+this\s+(?:url|link)\b|\bfetch\s+url\b",
        re.IGNORECASE,
    ), "url"),
    ("code_search", re.compile(
        r"\b(?:search|grep|find)\s+(?:the\s+)?(?:code|codebase|repo(?:sitory)?|source)\b|"
        r"\bcode[ _-]?search\b|\bgrep\s+the\s+(?:code|repo)\b",
        re.IGNORECASE,
    ), "query"),
]

# Legacy hardcoded system prompt — the exact text the direct loop used before
# the live prompt engine. Kept as the soft-degrade fallback so a prompt-engine
# failure never changes the loop's behavior.
_LEGACY_SYSTEM_PROMPT = (
    "You are Nexus, a local autonomous agent. For ordinary conversation, "
    "answer naturally and do not call tools. For actionable work, choose "
    "from the discovered tool schemas, execute the work, inspect results, "
    "and continue until verified. After a successful tool result, prefer "
    "a final answer; only call another tool when it is directly required "
    "by the original request. Never use unrelated discovery tools and "
    "never claim an action without a real tool result. Skills are guidance "
    "only, not executable tools; do not call a skill name as a function. "
    "Use an actual registered tool. When you need clarification, information, "
    "or a choice from the user, call the ask_question tool with a concise "
    "prompt and options; do not ask through ordinary prose or emit a "
    "[QUESTION:...] marker yourself, and wait for the user's answer. Verify "
    "any external CLI exists "
    "before saying it ran. On Windows, terminal uses cmd.exe by default: use "
    "& or && instead of an unquoted semicolon, avoid Unix-only head/tail, "
    "and choose shell='powershell' explicitly when PowerShell syntax is needed."
)

# Per-process prompt-engine cache keyed on root_dir so successive turns never
# rebuild the identical system prompt.
_live_system_prompt_cache: Dict[str, str] = {}


def _live_system_prompt(root_dir: str, *, role: str = "ARCHITECT",
                        intent: str = "chat", complexity: str = "simple",
                        needs_tools: bool = False) -> str:
    """Return the (cached) live system prompt from the NexusPromptEngine.

    Soft-degrade: if the engine import or call fails, or produces an empty
    prompt, fall back EXACTLY to the legacy hardcoded string. Only successful
    engine prompts are cached, so a transient failure still recovers next turn.
    """
    try:
        cached = _live_system_prompt_cache.get(root_dir)
        if cached is not None:
            return cached
        from nexus.conversation.prompts import NexusPromptEngine
        prompt = NexusPromptEngine.build_live_system_prompt(
            root_dir, role=role, intent=intent,
            complexity=complexity, needs_tools=needs_tools,
        )
        if not prompt or not prompt.strip():
            return _LEGACY_SYSTEM_PROMPT
        _live_system_prompt_cache[root_dir] = prompt
        return prompt
    except Exception:
        return _LEGACY_SYSTEM_PROMPT


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Read a positive integer limit from the environment with a safe default.

    Invalid or unset values fall back to ``default`` so a bad env var can
    never take the loop down or set an accidental zero/negative budget.
    """
    try:
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            return default
        return max(minimum, int(str(raw).strip()))
    except (TypeError, ValueError):
        return default


class V5DirectModelToolLoop:
    """Hermes-style loop: model response owns tool choice; events only observe."""

    # Round budget — Claude Code/Cursor semantics: UNLIMITED by default.
    # The loop ends when the model stops requesting tools (natural
    # termination), never because an arbitrary counter expired. The previous
    # hardcoded 8-round cap was the primary cause of runs dying mid-task
    # while work was still verifiably progressing.
    # Set NEXUS_DIRECT_LOOP_MAX_ROUNDS only to opt into an explicit ceiling.
    direct_loop_max_rounds = _env_int("NEXUS_DIRECT_LOOP_MAX_ROUNDS", 1_000_000)
    # Anti-runaway safety ceiling, far beyond any legitimate task. This is
    # NOT a task-size limit — it exists only so a pathological model loop can
    # never spin forever without the user noticing. The real stop signals are
    # the stagnation detector, abort, deadline, and (opt-in) token budget.
    direct_loop_hard_cap = _env_int("NEXUS_DIRECT_LOOP_HARD_CAP", 1_000_000)
    # No extension gimmicks: at the unlimited default the loop ends naturally
    # when the model stops calling tools; an explicitly configured bound is a
    # strict instruction and is always respected.
    # Repair budget is per failure signature: one broken call may be retried
    # this many times; unrelated failures do not share one global budget.
    # This is an anti-stuck valve, not a task-size limit.
    repair_attempt_budget = _env_int("NEXUS_REPAIR_ATTEMPT_BUDGET", 5)
    # No-progress detector: how many times the identical (tool, params)
    # signature may execute with unchanged results in one turn before the
    # loop stops spending provider requests on a non-progressing strategy.
    # This is the safety valve that replaces the old global round cap.
    repeat_call_budget = _env_int("NEXUS_REPEAT_CALL_BUDGET", 4)
    # Circuit breaker: consecutive rounds in which every executed action
    # failed (no verified success in between) before the loop stops. Catches
    # the "fails differently every round" case that per-signature repair
    # budgets and the identical-call detector cannot. Anti-stuck valve, not
    # a task-size limit. Override via NEXUS_FAILURE_STREAK_LIMIT.
    failure_streak_limit = _env_int("NEXUS_FAILURE_STREAK_LIMIT", 5)
    # Ping-pong loop detector (OpenClaw semantics): a run alternating between
    # two distinct (tool, params) signatures whose outcomes are stable on
    # BOTH sides is not making progress. Warn the model once at
    # ``pingpong_warning_streak`` alternating calls, stop at
    # ``pingpong_stop_streak``. Anti-stuck valve, not a task-size limit.
    pingpong_warning_streak = _env_int("NEXUS_PINGPONG_WARNING", 6)
    pingpong_stop_streak = _env_int("NEXUS_PINGPONG_LIMIT", 10)

    def _is_run_level_cancellation(self) -> bool:
        """Return whether cancellation belongs to the active NEXUS run.

        A tool may cancel its own operation (for example when a child process
        exits or a provider closes a stream).  That is a recoverable tool
        observation.  Cancellation requested through the active run control,
        or cancellation of the loop task itself, is intentionally preserved
        as a run-level stop.
        """
        try:
            registry = getattr(self, "_run_controls", None)
            turn_id = str(getattr(self, "_current_turn_id", "") or "")
            control = registry.get(turn_id) if registry is not None and turn_id else None
            if control is not None and bool(getattr(control, "cancelled", False)):
                return True
            task = asyncio.current_task()
            return bool(task is not None and task.cancelling())
        except Exception:
            # If cancellation ownership cannot be determined, keep the
            # conservative run-level behavior rather than swallowing a stop.
            return True

    @staticmethod
    def _call_signature(name: Any, params: Any) -> str:
        """Stable identity for one (tool, arguments) action.

        Used only for stagnation detection; never for routing. Falls back to
        ``repr`` so an unserializable parameter cannot raise inside the loop.
        """
        try:
            encoded = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            encoded = repr(params)
        return f"{str(name or '')}:{encoded}"

    def _stagnation_response(self, name: str, count: int, actions: List[Dict[str, Any]]) -> str:
        """Truthful terminal text for a detected non-progressing repeat loop."""
        summary = getattr(self, "_repair_exhausted_response", None)
        detail = ""
        if callable(summary):
            try:
                detail = str(summary(actions) or "")
            except Exception:
                detail = ""
        message = (
            f"I stopped because the same `{name}` call with identical arguments "
            f"was executed {count} times without changing the outcome. Repeating "
            "it again would not make progress, so no further provider requests "
            "were spent. Change the approach, the arguments, or the tool to continue."
        )
        return f"{message}\n\n{detail}".strip()

    @staticmethod
    def _repeat_outcome_hash(action: Dict[str, Any]) -> str:
        """Normalized identity of one tool OUTCOME, not its raw transcript text.

        Mirrors OpenClaw's outcome-aware no-progress hashing: identical
        (tool, params) calls count as non-progress only when their *outcome
        facts* match. Structured facts (exit code, failure signature) are
        preferred over the result text so trivial output variance (a changing
        timestamp, a progress percentage) does not mask a real loop, while a
        byte-identical transcript alone never proves progress.
        """
        try:
            if not action.get("success"):
                signature = str(action.get("failure_signature") or "").strip()
                return f"error:{signature[:64]}" if signature else "error"
            head = str(action.get("output") or "")[:4000]
            digest = hashlib.sha256(head.encode("utf-8", errors="replace")).hexdigest()[:16]
            exit_code = action.get("exit_code")
            if exit_code is not None:
                try:
                    exit_code = int(exit_code)
                except (TypeError, ValueError):
                    pass
                return f"ok:exit={exit_code}:{digest}"
            return f"ok:{digest}"
        except Exception:
            return "ok"

    @staticmethod
    def _pingpong_signal(history: List[Tuple[str, str]]) -> Optional[Tuple[str, str, int]]:
        """Detect an alternating two-signature call pattern with stable
        outcomes on BOTH sides (OpenClaw ping-pong semantics).

        ``history`` is a list of (signature, outcome_hash) executed-call
        pairs. Returns ``(signature_a, signature_b, alternating_count)``
        when the recent tail alternates A,B,A,B,... with each side's outcome
        unchanged, or None. A legitimately advancing A/B workflow changes at
        least one side's outcome, which breaks the pattern immediately.
        """
        if not isinstance(history, list) or len(history) < 6:
            return None
        tail = history[-16:]
        signature_a, outcome_a = tail[0]
        signature_b, outcome_b = tail[1]
        if signature_a == signature_b:
            return None
        alternating = 0
        for index, (signature, outcome) in enumerate(tail):
            if index % 2 == 0:
                if signature != signature_a or outcome != outcome_a:
                    break
            elif signature != signature_b or outcome != outcome_b:
                break
            alternating += 1
        if alternating < 6:
            return None
        return signature_a, signature_b, alternating

    @staticmethod
    def _pingpong_response(signature_a: str, signature_b: str, count: int) -> str:
        tool_a = str(signature_a).split(":", 1)[0] or "tool"
        tool_b = str(signature_b).split(":", 1)[0] or "tool"
        return (
            f"I stopped because the run alternated between `{tool_a}` and "
            f"`{tool_b}` calls {count} times with identical outcomes on both "
            "sides — a ping-pong loop that never advances the task. Change the "
            "strategy, the arguments, or ask for guidance; no further provider "
            "requests were spent."
        )

    def _repeat_warning_message(self, name: str, count: int) -> str:
        return (
            f"LOOP WARNING: `{name}` has now executed {count} times with "
            "identical arguments and the SAME outcome. This looks like a "
            "non-progressing loop: if the next identical call returns the same "
            "outcome again, the run will stop. Change the arguments, the tool, "
            "or the approach now."
        )

    def _pingpong_warning_message(self, tool_a: str, tool_b: str, count: int) -> str:
        return (
            f"LOOP WARNING: the run is alternating between `{tool_a}` and "
            f"`{tool_b}` calls ({count} consecutive alternations) with stable "
            "outcomes on both sides. This looks like a ping-pong loop: change "
            "the strategy now, or the run will stop."
        )

    async def _skip_remaining_batch_calls(
        self, calls: List[Any], start_slot: int, round_index: int, reason: str,
        actions: List[Dict[str, Any]], batch_outcomes: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
    ) -> int:
        """Record explicit skipped results for every call after ``start_slot``.

        OpenAI-compatible providers require one tool result per assistant
        tool call in a batch, so a mid-batch stop must still persist a valid
        envelope. Returns the number of skipped calls recorded.
        """
        persist_direct = getattr(self, "_persist_direct_message", None)
        persist_direct_async = getattr(self, "_persist_direct_message_async", None)
        skipped = 0
        for skipped_slot, skipped_call in enumerate(calls[start_slot + 1:], start=start_slot + 1):
            skipped_id = str(
                getattr(skipped_call, "call_id", "") or f"call_v5_r{round_index}_n{skipped_slot}"
            )
            skipped_action = {
                "tool": skipped_call.name, "name": skipped_call.name,
                "params": dict(skipped_call.params or {}), "call_id": skipped_id,
                "output": "", "error": reason, "success": False,
                "status": "skipped", "model_round": round_index,
            }
            actions.append(skipped_action)
            batch_outcomes.append(skipped_action)
            messages.append({
                "role": "tool", "name": skipped_call.name,
                "tool_call_id": skipped_id, "content": reason,
            })
            self._stamp_recent_messages(messages)
            if callable(persist_direct):
                if callable(persist_direct_async):
                    await persist_direct_async(
                        messages[-1],
                        str(getattr(self, "_current_turn_id", "") or ""),
                    )
                else:
                    persist_direct(messages[-1], str(getattr(self, "_current_turn_id", "") or ""))
            skipped += 1
        return skipped

    async def _direct_loop_state(self, state_name: str) -> None:
        """Publish loop phases without adding a second planner or router."""
        transition = getattr(self, "_transition_to", None)
        if not callable(transition):
            return
        try:
            from .core import V5LoopState
            await transition(V5LoopState[state_name])
        except Exception:
            # UI/checkpoint telemetry must never fail a valid turn.
            return

    async def _emit_tool_progress(
        self, call: Any, phase: str, outcome: str = "", *,
        evidence: str = "", retry_reason: str = "", plan_link: Dict[str, Any] | None = None,
    ) -> None:
        """Publish a short, safe status update around one real tool action.

        These are execution summaries, not model reasoning. They make the
        live chat read as an ordered transcript: status, one tool card, status,
        next tool card, and finally the model's answer.
        """
        emitter = getattr(self, "_emit_runtime_event", None)
        if not callable(emitter):
            return
        name = str(getattr(call, "name", "tool") or "tool")
        params = dict(getattr(call, "params", {}) or {})
        try:
            kind = self._work_kind_for_call(name, params)
            action = self._work_action_for_call(kind, name, params)
        except Exception:
            action = "Use tool"
        label = action[:1].lower() + action[1:]
        if phase == "started":
            note = f"I’m starting the {label}."
            next_action = "execute"
        elif outcome == "success":
            note = f"The {label} completed. I’m reviewing the result before continuing."
            next_action = "continue"
        else:
            note = f"The {label} failed. I’m checking the error before deciding whether to retry."
            next_action = "retry_or_stop"
        turn_id = str(getattr(self, "_current_turn_id", "") or getattr(self, "session_id", "run"))
        call_id = str(getattr(call, "call_id", "tool") or "tool")
        event_id = f"progress_{turn_id}_{call_id}_{phase}"
        try:
            await emitter(
                "assistant.progress",
                note,
                "running",
                event_id=event_id,
                parent_id=f"run_{turn_id}",
                payload={
                    "projection": "deterministic-v1",
                    "note": note,
                    "text": note,
                    "current_action": action,
                    "phase": "tool_result" if phase != "started" else "tool_start",
                    "tool": name,
                    "outcome": outcome or "starting",
                    "evidence": redact_secrets(str(evidence or ""))[:600],
                    "retry_reason": redact_secrets(str(retry_reason or ""))[:400],
                    "next_action": next_action,
                    **dict(plan_link or {}),
                },
            )
        except Exception:
            # Progress telemetry must never change whether the real tool runs.
            return

    async def _emit_tool_batch_progress(self, actions: List[Dict[str, Any]]) -> None:
        """Summarize a completed sequence while keeping action cards separate."""
        if not actions:
            return
        emitter = getattr(self, "_emit_runtime_event", None)
        if not callable(emitter):
            return
        labels: List[str] = []
        for action in actions:
            name = str(action.get("name") or action.get("tool") or "tool")
            try:
                params = dict(action.get("params") or {})
                kind = self._work_kind_for_call(name, params)
                label = self._work_action_for_call(kind, name, params)
            except Exception:
                label = "Use tool"
            if label not in labels:
                labels.append(label)
        subject = ", ".join(label.lower() for label in labels)
        failed = any(not bool(action.get("success")) for action in actions)
        note = (
            f"The {subject} {'failed' if failed else 'completed'}. "
            f"I’m reviewing the {'error' if failed else 'combined results'} before continuing."
        )
        turn_id = str(getattr(self, "_current_turn_id", "") or getattr(self, "session_id", "run"))
        call_ids = "_".join(str(action.get("call_id") or "tool") for action in actions)
        try:
            await emitter(
                "assistant.progress",
                note,
                "running",
                event_id=f"progress_{turn_id}_batch_{call_ids}",
                parent_id=f"run_{turn_id}",
                payload={
                    "projection": "deterministic-v1",
                    "note": note,
                    "text": note,
                    "current_action": note,
                    "phase": "tool_batch_result",
                    "tools": [str(action.get("name") or action.get("tool") or "tool") for action in actions],
                    "outcome": "failed" if failed else "success",
                    "next_action": "retry_or_stop" if failed else "continue",
                },
            )
        except Exception:
            return

    def _verification_payload(self, actions: List[Dict[str, Any]], calls_executed: int,
                              response: str, protocol_error: str = "") -> Dict[str, Any]:
        """Build a truthful verdict from the direct loop's real evidence."""
        failed = [item for item in actions
                  if str(item.get("status") or "failed") != "skipped"
                  and not bool(item.get("success")) and not item.get("repaired")]
        verified = sum(1 for item in actions
                       if str(item.get("status") or "") != "skipped"
                       and (bool(item.get("success")) or item.get("repaired")))
        plan = getattr(self, "_active_execution_plan", {}) or {}
        plan_id = str(plan.get("plan_id") or "")
        planned_steps = [
            step for step in (plan.get("steps") or [])
            if isinstance(step, dict) and str(step.get("tool") or "").strip()
        ]
        completed_step_ids = {
            str(action.get("step_id") or "")
            for action in actions
            if (action.get("success") or action.get("repaired"))
            and str(action.get("step_id") or "")
        }
        step_ids = [
            str(step_id or "") for step_id in (plan.get("step_ids") or [])
        ]
        required_step_ids = step_ids[:len(planned_steps)]
        uncompleted = [
            step_id for step_id in required_step_ids
            if step_id and step_id not in completed_step_ids
        ]
        plan_complete = not plan_id or not uncompleted
        ok = bool(response.strip()) and not protocol_error and not failed and plan_complete
        payload = {
            "success": ok,
            "mode": "conversation" if calls_executed == 0 else "tool_loop",
            "evidence_ok": ok,
            "total_actions": len(actions),
            "verified_actions": verified,
            "failed_actions": len(failed),
        }
        if plan_id:
            payload.update({
                "plan_id": plan_id,
                "planned_steps": len(planned_steps),
                "completed_plan_steps": len(completed_step_ids),
                "uncompleted_step_ids": uncompleted,
                "plan_complete": plan_complete,
            })
        return payload

    def _plan_link_for_call(
        self, call: Any, actions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Match a model tool call to the next durable plan step."""
        plan = getattr(self, "_active_execution_plan", {}) or {}
        plan_id = str(plan.get("plan_id") or "")
        if not plan_id:
            return {}
        steps = [step for step in (plan.get("steps") or []) if isinstance(step, dict)]
        step_ids = [str(value or "") for value in (plan.get("step_ids") or [])]
        if not steps or not step_ids:
            return {}
        tool_name = str(getattr(call, "name", "") or "")
        used = {
            str(action.get("step_id") or "")
            for action in actions
            if action.get("plan_id") == plan_id
        }
        # A corrected retry belongs to the failed step it repairs.
        previous = self._last_unrepaired_failure(actions)
        if previous is not None:
            if previous.get("plan_id") == plan_id and previous.get("step_id"):
                previous_tool = str(previous.get("tool") or previous.get("name") or "")
                if previous_tool == tool_name:
                    return {
                        "plan_id": plan_id,
                        "step_id": str(previous["step_id"]),
                        "plan_step_index": previous.get("plan_step_index"),
                    }
        for index, step in enumerate(steps):
            if index >= len(step_ids) or step_ids[index] in used:
                continue
            declared_tool = str(step.get("tool") or "").strip()
            if declared_tool and declared_tool != tool_name:
                continue
            return {
                "plan_id": plan_id,
                "step_id": step_ids[index],
                "plan_step_index": index + 1,
            }
        return {}

    def _transition_plan_step(self, link: Dict[str, Any], status: str, *, evidence: Dict[str, Any] | None = None) -> None:
        """Persist plan-step execution state without making it a tool side effect."""
        plan_id = str(link.get("plan_id") or "")
        step_id = str(link.get("step_id") or "")
        if not plan_id or not step_id:
            return
        try:
            from nexus.control_plane import load_plan, transition_step

            root = str(getattr(self, "root_dir", "") or ".")
            session_id = str(getattr(self, "session_id", "default") or "default")
            run_id = str(getattr(self, "_current_turn_id", "") or "")
            plan = load_plan(root, session_id, plan_id)
            if plan is None:
                return
            current = plan.step(step_id).status
            if status == "running" and current in {"pending", "failed", "blocked"}:
                transition_step(root=root, session_id=session_id, plan_id=plan_id,
                                step_id=step_id, status="ready", reason="direct loop selected step")
                current = "ready"
            if status == "running" and current == "ready":
                transition_step(root=root, session_id=session_id, plan_id=plan_id,
                                step_id=step_id, status="running", run_id=run_id,
                                reason="direct loop started tool")
            elif status in {"succeeded", "failed"} and current == "running":
                transition_step(root=root, session_id=session_id, plan_id=plan_id,
                                step_id=step_id, status=status, run_id=run_id,
                                evidence=evidence or {}, reason=f"direct loop {status}")
        except Exception as exc:
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.warning("Plan-step transition failed for %s/%s: %s", plan_id, step_id, exc)

    @staticmethod
    def _tool_budget_response(actions: List[Dict[str, Any]], bound: int) -> str:
        """Return truthful evidence when a model ignores the finalization turn."""
        completed = [str(item.get("name") or item.get("tool") or "tool")
                     for item in actions if item.get("success") or item.get("repaired")]
        failed = [str(item.get("name") or item.get("tool") or "tool")
                  for item in actions if not item.get("success") and not item.get("repaired")]
        details = []
        if completed:
            details.append("completed: " + ", ".join(completed))
        if failed:
            details.append("failed: " + ", ".join(failed))
        evidence = "; ".join(details) or "no tool result was recorded"
        return (
            f"I reached the {bound}-round execution limit before the model produced "
            f"a final response. Tool evidence: {evidence}. The work is not reported "
            "as fully verified; continue from the recorded results."
        )

    @staticmethod
    def _last_unrepaired_failure(
        actions: List[Dict[str, Any]],
    ) -> Dict[str, Any] | None:
        """Return the latest executed failure, ignoring batch-skip records."""
        return next(
            (
                action
                for action in reversed(actions)
                if not action.get("success")
                and not action.get("repaired")
                and str(action.get("status") or "") != "skipped"
            ),
            None,
        )

    @staticmethod
    def _mark_repaired_actions(actions: List[Dict[str, Any]], tool_name: str,
                               model_round: int | None = None) -> None:
        """Mark only the immediately preceding matching failed attempt.

        A model-driven retry is valid evidence when the corrected call for the
        same tool succeeds. The failed attempt remains visible in the audit
        trail, but no longer blocks the final verification verdict.
        """
        action = next(
            (
                item
                for item in reversed(actions)
                if not item.get("success")
                and not item.get("repaired")
                and str(item.get("status") or "") != "skipped"
                and str(item.get("name") or item.get("tool") or "") == str(tool_name)
            ),
            None,
        )
        if action is None:
            return
        # Multiple calls in one assistant response have not observed one
        # another's results yet.  Treating the second call as a repair would
        # hide a real failure from verification.  A repair is valid only after
        # the model has received the failed tool result in a later round.
        previous_round = action.get("model_round")
        if model_round is not None and previous_round is not None:
            try:
                if int(previous_round) >= int(model_round):
                    return
            except (TypeError, ValueError):
                return
        action["repaired"] = True

    @staticmethod
    def _schema_tokens(value: Any) -> set[str]:
        """Return generic lexical tokens for registry-backed candidate ranking.

        This is a transport-size guard for small local models, not a tool
        router: the model still chooses the executable tool from the returned
        registry schemas, and execution remains registry-authoritative.
        """
        stop = {
            "a", "an", "and", "are", "do", "for", "from", "give", "i",
            "in", "is", "it", "me", "my", "of", "on", "please", "show",
            "that", "the", "this", "to", "use", "with", "you",
        }
        return {
            token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
            if len(token) > 1 and token not in stop
        }

    @staticmethod
    def _explicit_question_request(value: Any) -> bool:
        """Detect an explicit request for the interactive question tool.

        ``tool_choice=auto`` is intentionally retained for ordinary chat, but
        small/local models frequently answer a direct "ask me a question"
        request as prose.  This narrow intent gate makes that interaction
        deterministic without forcing the tool for normal factual questions.
        """
        text = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if not text:
            return False
        return bool(re.search(
            r"\b(?:ask|pose|give|tell)\s+(?:(?:me|the user|a user)\s+)?"
            r"(?:a\s+|one\s+)?question\b"
            r"|\b(?:use|call|invoke)\s+(?:the\s+)?"
            r"(?:ask[_ -]?question|question)\s+tool\b"
            r"|\bask[_ -]?question\b",
            text,
        ))

    @staticmethod
    def _capability_args(tool_name: str, arg_key: str, task_desc: str) -> Dict[str, Any]:
        """Build the argument dict for a synthesized capability call.

        The argument is derived from the original request so the tool runs on
        the user's actual intent (e.g. web_search gets the user's query, not a
        generic placeholder). Falls back to the raw task when no cleaner signal
        can be extracted.
        """
        task = re.sub(r"\s+", " ", str(task_desc or "")).strip()
        if arg_key == "url":
            m = re.search(r"https?://[^\s)'\"\]>]+", task)
            return {"url": m.group(0) if m else task}
        return {arg_key: task}

    def _explicit_capability_request(self, task_desc: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Detect an explicit capability request and map it to a tool call.

        Returns ``(tool_name, args)`` when the user clearly asked for a concrete
        registered capability (web search, web fetch, code search, ...), else
        ``None``. This is the deterministic intent gate that guarantees a named
        capability is actually executed instead of narrated -- the model may
        still call it on its own via ``tool_choice="auto"``; when it does not,
        the loop forces or synthesizes the call.
        """
        text = re.sub(r"\s+", " ", str(task_desc or "")).strip()
        if not text:
            return None
        for tool_name, pattern, arg_key in CAPABILITY_INTENT_PATTERNS:
            if pattern.search(text):
                return (tool_name, self._capability_args(tool_name, arg_key, task_desc))
        return None

    def _get_direct_tool_schemas(self, top_k: int | None = None, *, query: str = "",
                                 provider: str | None = None) -> List[Dict[str, Any]]:
        """Return every executable registry schema without query-based routing.

        Tool choice belongs to the model. ``top_k`` and the explicit environment
        limit are retained only as deterministic transport caps for callers that
        opt into them; they never rank or omit tools based on the user query.
        """
        registry = getattr(self, "tool_registry", None)
        if registry is None:
            return []
        schemas: List[Dict[str, Any]] = []
        names = sorted(registry.list_tools(include_unavailable=False))
        for name in names:
            entry = registry.get(name)
            meta = getattr(entry, "schema", None) if entry is not None else None
            if not isinstance(meta, dict):
                continue
            # SKILL.md records are prompt guidance, not executable handlers.
            # Exposing them as function tools makes the model call a fake
            # "claude-code"/skill action that only returns [SKILL_ACTIVE].
            # Skills remain available through the injected skill context and
            # slash routing; only real registry handlers belong here.
            if str(meta.get("category") or "").strip().lower() == "skill":
                continue
            params = meta.get("params") or {}
            properties = {}
            required = []
            for key, value in params.items():
                if key == "additionalProperties" and isinstance(value, bool):
                    continue
                value = value if isinstance(value, dict) else {}
                # Preserve the JSON-Schema constraints authored by the tool.
                # Dropping enum/items/object bounds makes malformed model
                # calls far more likely and wastes the repair budget.
                allowed = {
                    "type", "description", "enum", "const", "default",
                    "items", "properties", "additionalProperties", "required",
                    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                    "minLength", "maxLength", "pattern", "format",
                    "minItems", "maxItems", "uniqueItems", "oneOf", "anyOf", "allOf",
                }
                definition = {
                    schema_key: schema_value
                    for schema_key, schema_value in value.items()
                    if schema_key in allowed
                    and not (schema_key == "required" and isinstance(schema_value, bool))
                }
                definition.setdefault("type", "string")
                if "description" in definition:
                    definition["description"] = str(definition["description"])[:160]
                properties[key] = definition
                if value.get("required"):
                    required.append(key)
            for key in meta.get("required") or []:
                if key not in required and key in properties:
                    required.append(key)
            parameter_schema = {
                "type": "object", "properties": properties, "required": required,
            }
            strict = meta.get("additionalProperties")
            if strict is None and isinstance(params, dict):
                strict = params.get("additionalProperties")
            if isinstance(strict, bool):
                parameter_schema["additionalProperties"] = strict
            schemas.append({"type": "function", "function": {
                "name": name,
                "description": str(meta.get("description", ""))[:240],
                "parameters": parameter_schema,
            }})
        try:
            configured_limit = int(os.environ.get("NEXUS_TOOL_SCHEMA_LIMIT", "0") or 0)
        except (TypeError, ValueError):
            configured_limit = 0
        limit = max(0, int(top_k or configured_limit or 0))
        if not limit:
            return schemas
        # Feed tool-health back into selection (close the "tool health -> but no
        # routing influence" loop). When the registry has outcome telemetry we order
        # candidates by a success-rate signal BEFORE the deterministic transport cap,
        # so a small-context local model meets the healthiest tools first. A cap always
        # truncates SOME tools (that is its job); the ordering only changes WHICH ones
        # survive, never the set available to an uncapped request, and the model still
        # makes the final pick (registry remains authoritative).
        #
        # A single transient failure on a low-sample tool must not permanently bury it:
        # smooth the observed rate toward neutral (Laplace / pseudo-count) so one bad
        # call is outweighed by later successes as they accrue, while sustained
        # failures still rank low. Unobserved tools stay at 0.0 (neutral) and tie-break
        # by their original alphabetical order via Python's stable sort.
        registry = getattr(self, "tool_registry", None)
        if registry is not None and callable(getattr(registry, "get_tool_stats", None)):
            try:
                def _health_key(schema):
                    name = str((schema.get("function") or {}).get("name", ""))
                    stats = registry.get_tool_stats(name)
                    if not stats or not stats.get("total_calls"):
                        return 0.0
                    rate = float(stats.get("success_rate", 0) or 0) / 100.0
                    latency_penalty = min(0.2, (float(stats.get("avg_latency_ms", 0) or 0) / 1000.0) * 0.02)
                    return round(rate - latency_penalty, 4)
                schemas = sorted(schemas, key=_health_key, reverse=True)
            except Exception:
                pass
        return schemas[:limit]

    def _parallel_reads_enabled(self) -> bool:
        """Whether concurrent read-tool execution is allowed.

        Other agent runtimes (Claude Code, Codex, Cline) run independent
        read-only tools in parallel to cut latency; this applies the same
        policy. Disable for strict single-threaded behavior via
        ``NEXUS_PARALLEL_READS=0``.
        """
        try:
            raw = os.environ.get("NEXUS_PARALLEL_READS", "")
            if str(raw).strip():
                return str(raw).strip().lower() not in {"0", "false", "no", "off"}
        except Exception:
            pass
        return True

    def _batch_is_parallelizable(self, calls) -> bool:
        """True only for a multi-call batch of read-only tools.

        This is the Claude Code/Codex read-gather rule: independent reads run
        concurrently; anything that might mutate runs sequentially to avoid
        state collisions. Conservative by default (a missing registry, an
        unknown tool, or any non-read-only tool disables parallelism).
        """
        if not self._parallel_reads_enabled():
            return False
        if not isinstance(calls, list) or len(calls) < 2:
            return False
        try:
            registry = getattr(self, "tool_registry", None)
            if registry is None:
                return False
            for call in calls:
                name = str(getattr(call, "name", "") or "")
                entry = registry.get(name) if registry is not None else None
                if entry is None:
                    return False
                is_ro = getattr(entry, "is_read_only", None)
                if callable(is_ro):
                    read_only = bool(is_ro(getattr(call, "params", None) or {}))
                else:
                    read_only = False
                if not read_only:
                    return False
            return True
        except Exception:
            return False

    async def _gather_read_parallel(self, calls, remaining) -> Dict[str, tuple]:
        """Run a parallelizable (all-read) batch concurrently.

        Returns ``{call_id: (ok: bool, content_or_error: str)}`` in original
        order. Errors are returned as ``(False, message)`` so the caller's
        normal per-call error handling runs unchanged; a single read failure
        can never cancel the whole gather.
        """
        out: Dict[str, tuple] = {}

        async def run_one(call) -> None:
            cid = str(getattr(call, "call_id", "") or "")
            try:
                task = asyncio.ensure_future(self._run_tool(call))
                if remaining is not None:
                    value = await asyncio.wait_for(task, timeout=max(0.001, remaining))
                else:
                    value = await task
                out[cid] = (True, redact_secrets(value))
            except asyncio.CancelledError:
                if self._is_run_level_cancellation():
                    raise
                out[cid] = (False, "Error: the tool cancelled its operation")
            except Exception as exc:
                out[cid] = (False, f"Error: {redact_secrets(exc)[:4000]}")

        await asyncio.gather(*[run_one(c) for c in calls])
        return out

    @staticmethod
    def _bounded_model_messages(messages: List[Dict[str, Any]], provider: str | None) -> List[Dict[str, Any]]:
        """Keep local OpenAI-compatible prompts below small context windows.

        The durable transcript remains complete in memory/storage.  This only
        bounds the request snapshot sent to a weak local model, preserving the
        system message and newest evidence instead of allowing old chat turns
        to make the provider reject the entire request.  For cloud providers
        it trims oldest turns only when the estimated token usage exceeds the
        provider's declared context window (see ``_cloud_bounded_model_messages``).
        """
        provider_id = str(provider or "").strip().lower().replace("-", "_")
        if provider_id not in {"lm_studio", "lmstudio", "ollama", "local"}:
            return V5DirectModelToolLoop._cloud_bounded_model_messages(messages, provider)
        try:
            budget = max(2000, int(os.environ.get("NEXUS_LOCAL_CONTEXT_CHARS", "6500")))
        except (TypeError, ValueError):
            budget = 6500
        if not messages:
            return messages
        system = [messages[0]] if messages[0].get("role") == "system" else []
        used = sum(len(str(item.get("content") or "")) for item in system)
        tail: List[Dict[str, Any]] = []
        for item in reversed(messages[len(system):]):
            cost = len(str(item.get("content") or "")) + 120
            if tail and used + cost > budget:
                break
            tail.append(item)
            used += cost
        tail.reverse()
        # Never send a tool result without the assistant tool call that
        # introduced it. OpenAI-compatible APIs validate this envelope and
        # reject an orphaned ``tool`` message. If the matching assistant call
        # is outside the retained tail, restore it; if it cannot be found,
        # discard the orphan rather than emitting an invalid transcript.
        while tail and tail[0].get("role") == "tool":
            orphan = tail[0]
            tool_call_id = str(orphan.get("tool_call_id") or "")
            match_index = next(
                (
                    index for index, candidate in enumerate(messages)
                    if candidate.get("role") == "assistant"
                    and any(
                        str(call.get("id") or "") == tool_call_id
                        for call in (candidate.get("tool_calls") or [])
                        if isinstance(call, dict)
                    )
                ),
                None,
            )
            if match_index is None:
                tail.pop(0)
                continue
            assistant = messages[match_index]
            tail.insert(0, assistant)
            # Keep the pair even if its rough size is larger than the local
            # budget; the result is already bounded before this function.
            break
        return system + tail

    @staticmethod
    def _context_window_for_provider(provider: str | None, model: str | None = None) -> int:
        """Resolve the active provider's context-window cap; 128_000 fallback.

        Prefers the data-driven registry from ``providers/model_capabilities.py``
        (per-model context windows loaded from ``config/provider.yml``).  Any
        failure — import, registry, or a missing/zero window — falls back to a
        conservative 128k so unknown cloud providers still get headroom instead
        of unbounded prompts.
        """
        try:
            configured = os.environ.get("NEXUS_CLOUD_CONTEXT_WINDOW", "")
            if configured:
                window = int(configured)
                if window > 0:
                    return window
        except (TypeError, ValueError):
            pass
        try:
            from models.providers.core.model_capabilities import ModelCapabilityRegistry
            registry = ModelCapabilityRegistry.from_loader()
            capability = registry.get(str(provider or ""), str(model or ""))
            window = int(getattr(capability, "context_window", 0) or 0)
            if window > 0:
                return window
        except Exception:
            pass
        return 128000

    def _record_model_usage(self, raw: Any) -> TokenUsage:
        """Accumulate provider-reported usage for the current V5 turn.

        A missing usage block is deliberately not replaced with an estimate;
        callers may still use the estimate for internal safety budgets, but it
        must never be presented to the user as measured provider telemetry.
        """
        usage = normalize_usage(raw)
        if usage.total_tokens <= 0:
            return usage
        previous = getattr(self, "_last_turn_usage", None) or {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "context_tokens": 0,
        }
        self._last_turn_usage = {
            "input_tokens": int(previous.get("input_tokens", 0)) + usage.input_tokens,
            "output_tokens": int(previous.get("output_tokens", 0)) + usage.output_tokens,
            "reasoning_tokens": int(previous.get("reasoning_tokens", 0)) + usage.reasoning_tokens,
            # Context is the prompt size of the latest provider request, not
            # the sum of all tool-loop requests in this turn.
            "context_tokens": usage.input_tokens,
        }
        return usage

    @staticmethod
    def _cloud_bounded_model_messages(messages: List[Dict[str, Any]],
                                      provider: str | None) -> List[Dict[str, Any]]:
        """Trim a cloud prompt only when estimated usage exceeds the window.

        Estimate is ``len(text) // 4`` per message (roughly the convention used
        throughout the codebase).  When over-budget, drop the oldest non-system
        turns first but never the most recent user+assistant+tool tail, and
        prepend a one-line marker so the model knows earlier context was
        compacted.  Degrades softly: any error returns the input unchanged.
        """
        if not isinstance(messages, list) or not messages:
            return messages
        try:
            window = V5DirectModelToolLoop._context_window_for_provider(provider)
            estimated = sum(len(str(item.get("content") or "")) for item in messages) // 4
            if estimated <= window:
                return messages
            # Find the newest user turn; its assistant/tool tail must survive.
            tail_start = 0
            for idx in range(len(messages) - 1, -1, -1):
                if messages[idx].get("role") == "user":
                    tail_start = idx
                    break
            keep_tail = messages[tail_start:]
            # Never strip the system prompt.
            head = [m for m in messages[:tail_start] if m.get("role") != "system"]
            system = [m for m in messages[:tail_start] if m.get("role") == "system"]
            # Drop oldest non-system turns until the estimate fits the window.
            kept_head: List[Dict[str, Any]] = []
            dropped = 0
            for item in head:
                candidate = kept_head + [item] + keep_tail
                if sum(len(str(m.get("content") or "")) for m in candidate) // 4 <= window:
                    kept_head.append(item)
                else:
                    dropped += 1
            if dropped <= 0:
                return messages
            marker = {"role": "system",
                      "content": f"[dropped {dropped} earlier turns to fit context]"}
            return system + [marker] + kept_head + keep_tail
        except Exception:
            return messages

    @staticmethod
    def _tool_result_archive_path(turn_id: str, call_slot: int, root_dir: str = "") -> str:
        """Resolve the archive file path for one oversized tool result."""
        safe_turn = re.sub(r"[^A-Za-z0-9_-]", "_", str(turn_id or "live")) or "live"
        return os.path.join(root_dir, ".nexus", "context_archive", "tool-results",
                            f"{safe_turn}_{int(call_slot)}.txt")

    @classmethod
    def _bounded_tool_result(cls, content: str, tool_name: str, turn_id: str,
                             call_slot: int, root_dir: str = "") -> str:
        """Bound one tool result before it enters the model transcript.

        Oversized results (> ``MAX_TOOL_RESULT_CHARS``) are persisted to
        ``.nexus/context_archive/tool-results/<turn>_<slot>.txt`` and replaced by a
        preview line so the prompt stays cheap while the full result remains
        readable by a future ``continue``.  Empty/whitespace results become an
        explicit "(name completed with no output)" marker.  Every failure here
        degrades to the original content so the loop is never worse for it.
        """
        try:
            if not content or not content.strip():
                return f"({tool_name} completed with no output)"
            if len(content) <= MAX_TOOL_RESULT_CHARS:
                return content
            root_dir = root_dir or os.getcwd()
            base = os.path.join(root_dir, ".nexus", "context_archive", "tool-results")
            os.makedirs(base, exist_ok=True)
            path = cls._tool_result_archive_path(turn_id, call_slot, root_dir)
            with open(path, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(content)
            preview = content[:TOOL_RESULT_PREVIEW_CHARS]
            rel = os.path.join(".nexus", "context_archive", "tool-results",
                               os.path.basename(path)).replace("\\", "/")
            return (f"[result {len(content)} chars persisted to {rel}; "
                    f"showing first {TOOL_RESULT_PREVIEW_CHARS} chars]\n{preview}")
        except Exception:
            return content

    @classmethod
    async def _bounded_tool_result_async(cls, content: str, tool_name: str,
                                         turn_id: str, call_slot: int,
                                         root_dir: str = "") -> str:
        """Bound and archive a tool result without blocking the event loop."""
        return await asyncio.to_thread(
            cls._bounded_tool_result, content, tool_name, turn_id, call_slot, root_dir
        )

    @classmethod
    def _compact_oldest_half(cls, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collapse the oldest half of *messages* into one system summary.

        First tries the call/result-safe ``context.compact_messages`` compactor
        so a tool_call is never split from its tool_result. When it reports
        nothing dropped (or on any error) it falls back to the LLM-free
        heuristic below: each dropped turn contributes its role plus the first
        200 chars of content, joined into a single system message. The original
        system prompt always survives, and the newest half (the most recent
        user+assistant+tool tail) is preserved so a compact-and-retry still has
        the current exchange. Never raises.
        """
        if not isinstance(messages, list) or len(messages) < 2:
            return messages
        try:
            from nexus.context import compact_messages
            compacted, dropped = compact_messages(
                messages, budget_tokens=128000, keep_recent=6,
            )
            if dropped > 0 and isinstance(compacted, list):
                return compacted
        except Exception:
            pass
        try:
            system = [messages[0]] if messages[0].get("role") == "system" else []
            rest = messages[len(system):]
            if not rest:
                return messages
            drop_count = max(1, len(rest) // 2)
            dropped_msgs = rest[:drop_count]
            kept = rest[drop_count:]
            parts = []
            for item in dropped_msgs:
                role = str(item.get("role") or "message")
                content = str(item.get("content") or "")[:200]
                if content.strip():
                    parts.append(f"[{role}] {content.strip()}")
            if not parts:
                parts.append("earlier turns omitted")
            summary = {"role": "system",
                       "content": "[compacted earlier turns: " + "; ".join(parts) + "]"}
            return system + [summary] + kept
        except Exception:
            return messages

    async def _append_project_context(self, system_prompt: str, *, max_chars: int = 2000) -> str:
        """Append a short ``=== PROJECT CONTEXT ===`` block to the system prompt.

        Uses the loop's existing ContextManager when present, else a lazy
        manager from root_dir. Project files are loaded once per instance and
        cached so successive turns reuse the same block. Any error degrades to
        no context so the prompt never loses the loop.
        """
        try:
            manager = getattr(self, "_context_manager", None) or getattr(
                self, "context_manager", None)
            if manager is None:
                from .context_manager import ContextManager
                manager = ContextManager(
                    str(getattr(self, "root_dir", "") or "") or os.getcwd()
                )
            if not getattr(self, "_project_context_built", False):
                try:
                    snapshot = await manager.load_context()
                except Exception:
                    snapshot = None
                context = manager.get_context() if getattr(snapshot, "files_loaded", None) else ""
                scrubber = getattr(manager, "scrub_context", None)
                if context and callable(scrubber):
                    context = scrubber(context)
                self._project_context = context
                self._project_context_built = True
            context = getattr(self, "_project_context", "") or ""
            if not context:
                return system_prompt
            trimmed = context[:max_chars] + "\n...[truncated]" if len(context) > max_chars else context
            return f"{system_prompt}\n\n=== PROJECT CONTEXT ===\n{trimmed}"
        except Exception:
            return system_prompt

    def _stamp_recent_messages(self, messages: List[Dict[str, Any]]) -> None:
        """Remember the tail of the live transcript for checkpoint persistence."""
        try:
            if isinstance(messages, list):
                self._recent_messages = list(messages[-RECENT_MESSAGES_LIMIT:])
        except Exception:
            pass

    async def _prompt_too_long_retry(self, request_messages: List[Dict[str, Any]],
                                     model_kwargs: Dict[str, Any]) -> Any:
        """Compact-and-retry once when a provider rejects the prompt as too long.

        Detection uses the explicit length/context markers the spec names
        ("context", "too long", "length", "413", "prompt is too long") and only
        fires on an error-like envelope with no tool calls, so ordinary answers
        (even ones containing the word "context") never trigger a retry.  Generic
        provider/router failures handled by ``_is_provider_error_text`` keep
        their existing recovery path untouched.  On a hit, collapse the oldest
        half of the message list into one system summary and retry exactly once.
        If the retry fails again the current result is returned so the caller
        surfaces the original error.
        """
        raw = await self._safe_model_call_raw(request_messages, **model_kwargs)
        text, calls = self._model_turn_parts(raw)
        if not calls and self._is_prompt_too_long_error(text):
            try:
                compacted = self._compact_oldest_half(request_messages)
                if isinstance(compacted, list) and compacted != request_messages:
                    # A compaction is a stall symptom, not progress: record it
                    # so the loop's stall watchdog can stop a compaction loop
                    # (repeated compact-and-retry without verified progress)
                    # instead of burning provider requests forever.
                    record_compaction = getattr(self, "_progress_record", None)
                    if callable(record_compaction):
                        try:
                            record_compaction(
                                "compaction", signature="prompt_too_long_retry",
                                status="compacted",
                            )
                        except Exception:
                            pass
                    retried = await self._safe_model_call_raw(compacted, **model_kwargs)
                    retried_text, _retried_calls = self._model_turn_parts(retried)
                    if not self._is_prompt_too_long_error(retried_text):
                        return retried
            except Exception:
                pass
        return raw

    @staticmethod
    def _is_prompt_too_long_error(value: Any) -> bool:
        """True when provider text signals a prompt/context-too-long failure.

        The markers mirror the lengths most providers use when a request
        exceeds the context window: "context", "too long", "length", the HTTP
        413 status, and the canonical "prompt is too long" phrase.
        """
        text = str(value or "")
        head = text[:2000].lower()
        markers = ("context", "too long", "length", "413", "prompt is too long")
        return any(marker in head for marker in markers)

    @staticmethod
    def _provider_recovery_messages(messages: List[Dict[str, Any]], task_desc: str) -> List[Dict[str, Any]]:
        """Build one safe retry transcript after a provider rejects history."""
        system = next((item for item in messages
                       if isinstance(item, dict) and item.get("role") == "system"), None)
        recovered: List[Dict[str, Any]] = []
        evidence = [
            str(item.get("content") or "")[:1800]
            for item in messages[-4:]
            if isinstance(item, dict) and item.get("role") == "tool" and item.get("content")
        ]
        if system:
            system_text = str(system.get("content") or "")
            if evidence:
                system_text += (
                    "\n\nRecovery evidence from successful tool calls. Use it as evidence; "
                    "do not repeat the same successful call unless necessary:\n- "
                    + "\n- ".join(evidence)
                )
            recovered.append({"role": "system", "content": system_text})
        recovered.append({"role": "user", "content": str(task_desc or "")})
        return recovered

    async def _run_direct_model_tool_loop(self, task_desc: str, *, context_summary: str = "",
                                          conversation_history: List[Dict[str, Any]] | None = None,
                                          max_rounds: int | None = None,
                                          provider: str | None = None, profile: str | None = None,
                                          model: str | None = None, max_tokens: int | None = None) -> Dict[str, Any]:
        # Never let usage from a previous turn leak into a new result.
        self._last_turn_usage = None
        # Stall detection is scoped to this run: call/error counters from a
        # previous turn (or a previous process restart) must not make a fresh
        # run look stalled on its first round.
        self._reset_progress()
        # Prompt making now comes from the live prompt engine (NOT a hardcoded
        # string): a compact, token-budgeted system prompt assembled from the
        # identity/role/collaboration/rules/special-focus segments, with
        # project-context injected from the loop's ContextManager. Both steps
        # soft-degrade — to the legacy hardcoded text and to no-context — so a
        # prompt-engine or context-load failure never breaks a valid turn.
        requires_planning = False
        requires_planning_fn = getattr(self, "_requires_planning", None)
        if callable(requires_planning_fn):
            try:
                requires_planning = bool(requires_planning_fn(task_desc))
            except Exception:
                requires_planning = False
        requires_tooling = requires_planning
        requires_tooling_fn = getattr(self, "_requires_real_tooling", None)
        if callable(requires_tooling_fn):
            try:
                # ``_requires_real_tooling`` is intentionally conservative
                # for compatibility callers; the actionable boundary above is
                # the stronger signal for the live V5 loop.
                requires_tooling = requires_planning or bool(
                    requires_tooling_fn(task_desc)
                )
            except Exception:
                requires_tooling = requires_planning
        system = _live_system_prompt(
            str(getattr(self, "root_dir", "") or "") or os.getcwd(),
            intent="task" if requires_planning else "chat",
            complexity="complex" if requires_planning else "simple",
            needs_tools=requires_planning,
        )
        system = await self._append_project_context(system)
        # Aider-style repo map: inject symbol-level code overview for the planner
        if requires_planning:
            try:
                from .repo_map import build_repo_map_async, inject_repo_map
                repo_map = await build_repo_map_async(
                    str(getattr(self, "root_dir", "") or "") or os.getcwd(),
                    max_chars=6000,
                )
                if repo_map:
                    system = inject_repo_map(system, repo_map)
            except Exception:
                pass  # repo map is best-effort; never blocks the loop
        provider_id = str(provider or "").strip().lower().replace("-", "_")
        context_limit = 2500 if provider_id in {"lm_studio", "lmstudio", "ollama", "local"} else 6000
        if context_summary:
            system += f"\n\nPersisted context:\n{context_summary[:context_limit]}"
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        pending_tool_calls: Dict[str, str] = {}
        if conversation_history:
            # Reuse the canonical transcript so a fresh process can continue a
            # conversation instead of relying only on a lossy memory summary.
            for item in conversation_history:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "")
                content = item.get("content", "")
                if role in {"user", "assistant", "tool"} and (
                    isinstance(content, str)
                    or (role == "assistant" and item.get("tool_calls"))
                ):
                    if not isinstance(content, str):
                        content = ""
                    restored = {"role": role, "content": content}
                    if item.get("turn_id"):
                        restored["turn_id"] = item["turn_id"]
                    if role == "assistant" and item.get("tool_calls"):
                        restored["tool_calls"] = item["tool_calls"]
                        for raw_call in item.get("tool_calls") or []:
                            if not isinstance(raw_call, dict):
                                continue
                            call_id = str(raw_call.get("id") or raw_call.get("call_id") or "")
                            function = raw_call.get("function") or {}
                            name = str(function.get("name") or raw_call.get("name") or "tool")
                            if call_id:
                                pending_tool_calls[call_id] = name
                    for key in ("name", "tool_call_id"):
                        if item.get(key):
                            restored[key] = item[key]
                    if role == "tool" and item.get("tool_call_id"):
                        pending_tool_calls.pop(str(item["tool_call_id"]), None)
                    messages.append(restored)
            # A process can die after the assistant decision was flushed but
            # before the side effect returns.  Preserve that uncertainty as a
            # tool observation so the model can inspect/repair it; never
            # replay an orphaned call automatically.
            for call_id, name in pending_tool_calls.items():
                messages.append({
                    "role": "tool",
                    "name": name,
                    "tool_call_id": call_id,
                    "content": (
                        "UNKNOWN: the previous process stopped before recording a result "
                        f"for {name}. Do not assume it succeeded; inspect state before retrying."
                    ),
                })
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != task_desc:
            messages.append({"role": "user", "content": task_desc})
        # ``bound`` limits tool-decision rounds.  A separate finalization turn
        # is required after the last tool result; otherwise a valid tool call
        # emitted on the final round is mistaken for an unfinished protocol
        # envelope (the original failure seen after code_search).
        base_bound = max(1, int(max_rounds or self.direct_loop_max_rounds))
        # Scale the round budget with the active plan: each planned step may
        # need a tool round plus a verification/repair round, so a multi-step
        # plan gets a larger budget than a single-command task. Bounded by the
        # hard cap so a pathological plan cannot create an unbounded run.
        plan_step_count = 0
        try:
            _plan = getattr(self, "_active_execution_plan", {}) or {}
            plan_step_count = len([
                step for step in (_plan.get("steps") or [])
                if isinstance(step, dict)
            ])
        except Exception:
            plan_step_count = 0
        bound = base_bound
        if plan_step_count > 0:
            bound = min(self.direct_loop_hard_cap,
                        base_bound + min(plan_step_count, 16) * 2)
        calls_executed = 0
        actions: List[Dict[str, Any]] = []
        unavailable_retries: Dict[Tuple[str, str], int] = {}
        # Closed loop-detection state: how many times each identical
        # (tool, params) signature has actually been executed this turn.
        repeat_counts: Dict[str, int] = {}
        # Outcome-aware non-progress tracking: (outcome_hash, consecutive
        # stable streak) per (tool, params) signature. The streak resets when
        # the outcome changes, so a genuinely advancing poll is never stopped.
        repeat_outcomes: Dict[str, Tuple[str, int]] = {}
        repeat_warned: set = set()
        # Executed-call history (signature, outcome_hash) for ping-pong
        # detection; only this run's calls, never a previous turn's.
        executed_signatures: List[Tuple[str, str]] = []
        pingpong_warned = False
        repair_attempts_by_signature: Dict[str, int] = {}
        # Consecutive rounds in which every executed action failed. Reset by
        # any verified success; bounded by ``failure_streak_limit``.
        failure_streak = 0
        tool_enforcement_attempts = 0
        hive_repair_applied = False
        replan_applied = False
        init_ledger = getattr(self, "_init_task_ledger", None)
        if callable(init_ledger):
            init_ledger()
        self._last_run_had_tool_execution = False
        last_text = ""
        self._stamp_recent_messages(messages)
        # Reserve one finalization turn, but allow a failed action at the
        # boundary to receive a model-driven repair turn first. Without this
        # extra recovery window, the loop could report failure immediately
        # after the last tool round even though repair budget remained.
        # The window is self-bounding relative to the (plan-scaled) bound:
        # ``bound`` tool rounds plus the repair window plus one finalization
        # turn. At the unlimited default the loop ends naturally when the
        # model stops requesting tools — never at an arbitrary counter.
        for round_index in range(bound + self.repair_attempt_budget + 1):
            pending_failure = self._last_unrepaired_failure(actions)
            pending_signature = str((pending_failure or {}).get("failure_signature") or "")
            pending_attempts = repair_attempts_by_signature.get(pending_signature, 0)
            recovery_pending = bool(
                pending_failure is not None
                and pending_attempts < self.repair_attempt_budget
            )
            finalization_round = round_index >= bound and not recovery_pending
            # Circuit breaker: several consecutive rounds where every executed
            # action failed (with no verified success in between) means the
            # current strategy is not working at all. Stop with truthful
            # evidence instead of burning provider requests without limit.
            if failure_streak >= self.failure_streak_limit:
                response = (
                    "I stopped because the last "
                    f"{failure_streak} execution rounds all failed without any "
                    "verified progress. The current approach is not working; "
                    "change the tool, the parameters, or the strategy.\n\n"
                    + self._repair_exhausted_response(actions)
                )
                verification = self._verification_payload(
                    actions, calls_executed, response,
                    "consecutive failed rounds circuit breaker",
                )
                return {
                    "success": False, "response": response, "actions": actions,
                    "tool_rounds": round_index, "calls_executed": calls_executed,
                    "messages": messages, "verification": verification,
                    "degradation": ["stopped by consecutive-failure circuit breaker"],
                    "error": "consecutive failed rounds circuit breaker",
                }
            check_abort = getattr(self, "_check_abort", None)
            if callable(check_abort):
                check_abort()
            check_deadline = getattr(self, "_check_deadline", None)
            if callable(check_deadline):
                check_deadline()
            await self._direct_loop_state("REFLECTING" if round_index else "ACTING")
            # Wall-clock stall detection: a loop that keeps producing calls
            # but no meaningful progress (no new artifacts, no state changes,
            # no new successful tool signatures) must not run unbounded. The
            # first stalls inject model-visible guidance; exhausting the hint
            # budget returns an honest stall envelope instead of a fake
            # success.
            stall_signal, stall_hint = self._stall_check_and_hint()
            if stall_signal is not None and not finalization_round:
                if stall_hint is None:
                    response = (
                        "The run stalled: repeated operations produced no "
                        "meaningful progress and the stall guidance budget was "
                        "exhausted. The ineffective strategy has been frozen. "
                        "Ask the user how to proceed or restart with a "
                        "different approach."
                    )
                    verification = self._verification_payload(
                        actions, calls_executed, response,
                        "stall detected: no meaningful progress",
                    )
                    return {
                        "success": False, "response": response,
                        "actions": actions, "tool_rounds": round_index,
                        "calls_executed": calls_executed,
                        "messages": messages, "verification": verification,
                        "stall": {
                            "kind": stall_signal.kind,
                            "detail": str(stall_signal.detail)[:400],
                        },
                        "error": "stall detected: no meaningful progress",
                    }
                messages.append({"role": "system", "content": stall_hint})
                self._stamp_recent_messages(messages)
            # The direct loop already owns bounded tool repair. In active Hive
            # mode, add at most one independent stall replan as model-visible
            # guidance; never execute the proposal blindly.
            if not replan_applied and not finalization_round:
                active_mode = getattr(self, "_active_mode_enabled", None)
                replan = getattr(self, "_hive_replan_on_stall", None)
                if callable(active_mode) and callable(replan):
                    try:
                        if active_mode():
                            proposed = await replan(
                                SimpleNamespace(original_input=task_desc)
                            )
                            if isinstance(proposed, list) and proposed:
                                bounded_proposal = [
                                    step for step in proposed[:8]
                                    if isinstance(step, dict)
                                    and str(step.get("description") or "").strip()
                                ]
                                if bounded_proposal:
                                    replan_applied = True
                                    messages.append({
                                        "role": "system",
                                        "content": (
                                            "HIVE REPLAN PROPOSAL: prior attempts stalled. "
                                            "Inspect this alternative plan, validate every "
                                            "tool and parameter, and execute only justified "
                                            "steps. Do not claim completion without evidence.\n"
                                            + json.dumps(
                                                bounded_proposal,
                                                ensure_ascii=False,
                                                default=str,
                                            )[:6000]
                                        ),
                                    })
                                    self._stamp_recent_messages(messages)
                    except Exception as exc:
                        self.logger.debug("Hive stall replan unavailable: %s", exc)
            budget_exceeded = getattr(self, "_budget_exceeded", None)
            if callable(budget_exceeded) and budget_exceeded():
                # Graceful wind-down instead of sudden death: do not spend
                # another provider request, but report every verified action
                # truthfully as a partial result instead of a bare failure.
                verified_tools = [
                    str(item.get("name") or item.get("tool") or "tool")
                    for item in actions if item.get("success") or item.get("repaired")
                ]
                response = (
                    "The run budget was reached before the task finished. "
                    + (
                        "Verified completed work: " + ", ".join(verified_tools) + ". "
                        if verified_tools else "No verified work was recorded yet. "
                    )
                    + "Continue with a new run to finish the remaining steps."
                )
                verification = self._verification_payload(
                    actions, calls_executed, response, "run budget exceeded"
                )
                return {
                    "success": False, "partial": bool(verified_tools),
                    "status": "completed_partial" if verified_tools else "failed",
                    "response": response, "actions": actions,
                    "tool_rounds": round_index, "calls_executed": calls_executed,
                    "messages": messages, "verification": verification,
                    "degradation": ["run budget exhausted before completion"],
                    "error": "run budget exceeded",
                }
            # A failed last-round action has no safe provider continuation:
            # surface its evidence instead of spending another request on a
            # model that may repeat the same invalid call.
            if finalization_round and pending_failure is not None:
                response = self._tool_budget_response(actions, bound)
                verification = self._verification_payload(
                    actions, calls_executed, response, "tool loop ended after a failed action"
                )
                verified_any = bool(verification.get("verified_actions"))
                return {
                    "success": False,
                    "partial": verified_any,
                    "status": "completed_partial" if verified_any else "failed",
                    "response": response, "actions": actions,
                    "tool_rounds": bound, "calls_executed": calls_executed,
                    "messages": messages, "verification": verification,
                    "degradation": ["loop ended with an unrepaired failed action"],
                    "error": "tool loop ended after a failed action",
                }
            schemas = [] if finalization_round else self._get_direct_tool_schemas(
                query=task_desc, provider=provider,
            )
            model_kwargs: Dict[str, Any] = {
                # Timeout was hardcoded 90s; slow local/thinking models need
                # more. NEXUS_MODEL_TIMEOUT overrides; default matches
                # model.py's own 180s default.
                "timeout": float(_env_int("NEXUS_MODEL_TIMEOUT", 180)),
                "provider": provider, "profile": profile,
                "model": model, "max_tokens": max_tokens,
            }
            if finalization_round:
                messages.append({
                    "role": "system",
                    "content": (
                        "FINALIZATION REQUIRED: inspect the tool results already in the "
                        "conversation and return a concise final answer now. Do not call "
                        "another tool; report completed work, failed checks, and remaining "
                        "issues truthfully."
                    ),
                })
            if schemas:
                model_kwargs["tools"] = schemas
                available_names = {
                    str(item.get("function", {}).get("name") or "")
                    for item in schemas
                    if isinstance(item, dict) and isinstance(item.get("function"), dict)
                }
                force_question = (
                    round_index == 0
                    and self._explicit_question_request(task_desc)
                    and "ask_question" in available_names
                )
                # Explicit capability intent (e.g. "use web search") must be
                # executed, not narrated. Force the matching tool on round 0 so
                # the provider is required to emit that tool call. Falls back to
                # the question-tool force, then to auto.
                capability = None
                if round_index == 0:
                    cap = self._explicit_capability_request(task_desc)
                    if cap is not None and cap[0] in available_names:
                        capability = cap
                if capability is not None:
                    model_kwargs["tool_choice"] = {
                        "type": "function",
                        "function": {"name": capability[0]},
                    }
                else:
                    model_kwargs["tool_choice"] = (
                        {"type": "function", "function": {"name": "ask_question"}}
                        if force_question else "auto"
                    )
            request_messages = self._bounded_model_messages(messages, provider)
            # A cloud provider may reject the prompt as too long once the
            # transcript grows. Compact-and-retry exactly once before treating
            # this as a hard provider failure; the call returns the retried
            # result when it succeeds and the original error otherwise.
            raw = await self._prompt_too_long_retry(request_messages, model_kwargs)
            budget_tick = getattr(self, "_budget_tick", None)
            if callable(budget_tick):
                usage = self._record_model_usage(raw)
                input_tokens = usage.input_tokens or estimate_messages_tokens(request_messages)
                cost = estimate_cost_usd(provider, model, input_tokens, usage.output_tokens)
                budget_tick(tokens=input_tokens + usage.output_tokens, cost=cost)
            else:
                self._record_model_usage(raw)
            text, calls = self._model_turn_parts(raw)
            # ── Capability execution enforcement ───────────────────────────────
            # The user explicitly requested a capability (e.g. "use web search")
            # but the model returned no tool call -- either it narrated, or the
            # provider silently dropped the tool. Do NOT accept the prose as the
            # answer. Synthesize the requested tool call and execute it through
            # the shared ``_run_tool`` pipeline so the real result is produced
            # and fed back for a truthful final answer. This is the hard
            # guarantee behind "execute the capability, don't just describe it".
            if (
                not calls
                and schemas
                and not finalization_round
                and capability is not None
                and capability[0] in available_names
            ):
                from .tools import _TextToolCall
                synthesized = _TextToolCall(capability[0], dict(capability[1] or {}))
                await self._emit_tool_event(synthesized, status="running")
                if getattr(self, "logger", None) is not None:
                    self.logger.info(
                        "Capability enforcement: synthesizing tool call %s for request",
                        capability[0],
                    )
                calls = [synthesized]
            # Some OpenAI-compatible gateways accept the first tool catalogue
            # but reject a later request after tool results expand the
            # transcript. Recover with a deterministic transport cap; this is
            # not query routing and does not silently discard a matching tool
            # based on lexical overlap.
            if not calls and schemas:
                classifier = getattr(self, "_is_provider_error_text", None)
                is_provider_error = False
                if callable(classifier):
                    try:
                        is_provider_error = bool(classifier(text))
                    except Exception:
                        is_provider_error = False
                if is_provider_error and (len(schemas) > 24 or len(messages) > 3):
                    # Preserve the complete model-visible catalogue on
                    # recovery. A hidden deterministic slice can omit the
                    # one tool needed by the user's request.
                    compact_schemas = schemas
                    if compact_schemas:
                        retry_kwargs = dict(model_kwargs)
                        retry_kwargs["tools"] = compact_schemas
                        retry_kwargs["tool_choice"] = "auto"
                        recovery_messages = self._provider_recovery_messages(messages, task_desc)
                        recovered = await self._safe_model_call_raw(
                            recovery_messages, **retry_kwargs
                        )
                        self._record_model_usage(recovered)
                        record_compaction = getattr(self, "_progress_record", None)
                        if callable(record_compaction):
                            try:
                                record_compaction(
                                    "compaction", signature="provider_recovery",
                                    status="compacted",
                                )
                            except Exception:
                                pass
                        recovered_text, recovered_calls = self._model_turn_parts(recovered)
                        if recovered_calls or not self._is_provider_error_text(recovered_text):
                            raw, text, calls = recovered, recovered_text, recovered_calls
            last_text = text
            if not calls:
                provider_error = str(getattr(self, "_last_model_error", "") or "")
                classifier = getattr(self, "_is_provider_error_text", None)
                if callable(classifier):
                    try:
                        if classifier(text):
                            provider_error = "provider failure returned no usable model response"
                    except Exception:
                        pass
                if provider_error:
                    provider_label = str(provider or "configured provider").strip() or "configured provider"
                    model_label = str(model or "default model").strip() or "default model"
                    detail = re.sub(r"\s+", " ", str(text or "")).strip()
                    # Do not expose raw provider payloads (they may contain
                    # headers or credential-shaped text), but preserve a
                    # short actionable diagnostic for the UI.
                    detail = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", detail)
                    detail = redact_secrets(detail)
                    detail = detail[:240]
                    response = (
                        f"I couldn't reach provider `{provider_label}` with model "
                        f"`{model_label}`. No verified result was produced. "
                        "Check the provider credentials, offline mode, or local model server."
                    )
                    if detail:
                        response += f" Diagnostic: {detail}"
                    protocol_error = provider_error
                else:
                    response, protocol_error = self._safe_terminal_response(text, actions)
                if (
                    requires_tooling
                    and calls_executed == 0
                    and not provider_error
                    and not finalization_round
                    and tool_enforcement_attempts < 2
                ):
                    # A tool-requiring request cannot be completed by a prose
                    # answer alone. Give the model a small, explicit recovery
                    # window before returning a truthful failure.
                    tool_enforcement_attempts += 1
                    messages.append({
                        "role": "system",
                        "content": (
                            "TOOL ACTION REQUIRED: this request requires real work in the "
                            "workspace or an external source. Your previous response did "
                            "not call a tool. Select a relevant registered tool, execute it, "
                            "and inspect its result before answering. Never claim completion "
                            "without a real tool result."
                        ),
                    })
                    self._stamp_recent_messages(messages)
                    continue
                if requires_tooling and calls_executed == 0 and not provider_error:
                    response = (
                        "I couldn't complete this actionable request because the model "
                        "did not produce a tool action. No verified workspace result was "
                        "created."
                    )
                    protocol_error = "no tool action for actionable request"
                # Conversation is a valid completed turn even when no tool is
                # needed.  Once a tool is requested, however, every executed
                # tool must succeed before actionable work can be reported as
                # complete.
                verification = self._verification_payload(
                    actions, calls_executed, response, protocol_error
                )
                result = {"success": bool(verification["success"]),
                          "response": response, "actions": actions,
                          "tool_rounds": round_index, "calls_executed": calls_executed,
                          "messages": messages,
                          "verification": verification}
                if protocol_error:
                    result["error"] = protocol_error
                try:
                    if provider_error:
                        await self._recovery_for_failure(
                            exc=RuntimeError(str(provider_error)[:400]),
                            component_type="provider",
                            component_id=provider_label,
                            operation="model_call",
                            provider=provider,
                            model=model,
                        )
                except Exception:
                    pass
                return result
            if finalization_round:
                # An explicitly configured bound is a strict instruction and
                # is always respected. At the unlimited default this branch is
                # unreachable because the loop ends naturally when the model
                # stops requesting tools (Claude Code/Cursor semantics).
                response = self._tool_budget_response(actions, bound)
                verification = self._verification_payload(
                    actions, calls_executed, response,
                    "model requested another tool during finalization",
                )
                verified_any = bool(verification.get("verified_actions"))
                return {
                    "success": False,
                    "partial": verified_any,
                    "status": "completed_partial" if verified_any else "failed",
                    "response": response, "actions": actions,
                    "tool_rounds": bound, "calls_executed": calls_executed,
                    "messages": messages, "verification": verification,
                    "degradation": ["round budget exhausted; model still had pending tool work"],
                    "error": "model requested another tool during finalization",
                }
            # Text-format tool calls often have no provider-generated ID. A
            # constant fallback (``call_v5``) is invalid once a response has
            # more than one call or a later turn adds another tool result.
            # Normalize IDs before persisting the assistant message so the
            # assistant and every tool result refer to the same unique ID.
            seen_call_ids = set()
            for call_index, call in enumerate(calls):
                existing_id = str(getattr(call, "call_id", "") or "")
                call_id = existing_id or f"call_v5_r{round_index}_n{call_index}"
                if call_id in seen_call_ids:
                    call_id = f"{call_id}_r{round_index}_n{call_index}"
                setattr(call, "call_id", call_id)
                seen_call_ids.add(call_id)
            assistant_message = {
                "role": "assistant", "content": text or None,
                "tool_calls": [self._tool_call_dict(call) for call in calls],
            }
            # DeepSeek (and other thinking-mode providers) REQUIRE the
            # ``reasoning_content`` of a prior assistant turn to be echoed back
            # on the next request; otherwise the API rejects the turn with 400
            # ("reasoning_content in the thinking mode must be passed back").
            # Drop only when the provider actually returned reasoning.
            _reasoning_echo = getattr(self, "_last_reasoning_content", None)
            if _reasoning_echo:
                assistant_message["reasoning_content"] = _reasoning_echo
            messages.append(assistant_message)
            self._stamp_recent_messages(messages)
            persist_direct = getattr(self, "_persist_direct_message", None)
            persist_direct_async = getattr(self, "_persist_direct_message_async", None)
            if callable(persist_direct):
                if callable(persist_direct_async):
                    await persist_direct_async(
                        assistant_message,
                        str(getattr(self, "_current_turn_id", "") or ""),
                    )
                else:
                    persist_direct(assistant_message, str(getattr(self, "_current_turn_id", "") or ""))
            batch_outcomes: List[Dict[str, Any]] = []
            # Claude Code/Codex read-gather: when the whole batch is safe
            # independent read-only tools, launch them concurrently up front
            # and replay results in original call order below, so a multi-read
            # round costs roughly one latency unit instead of N.
            parallel_batch: Optional[Dict[str, tuple]] = None
            if self._batch_is_parallelizable(calls):
                try:
                    _reg_control = getattr(self, "_run_controls", None)
                    _cur = str(getattr(self, "_current_turn_id", "") or "")
                    _ctrl = _reg_control.get(_cur) if _reg_control is not None and _cur else None
                    parallel_batch = await self._gather_read_parallel(
                        calls, getattr(_ctrl, "remaining", None) if _ctrl is not None else None
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    parallel_batch = None  # fall back to serial on any error
            for call_slot, call in enumerate(calls):
                if callable(check_abort):
                    check_abort()
                check_deadline = getattr(self, "_check_deadline", None)
                if callable(check_deadline):
                    check_deadline()
                call_id = str(getattr(call, "call_id", "") or "call_v5")
                plan_link = self._plan_link_for_call(call, actions)
                self._transition_plan_step(plan_link, "running")
                await self._emit_tool_progress(call, "started")
                # Resolve the run-control deadline once for this call.
                _registry = getattr(self, "_run_controls", None)
                _current = str(getattr(self, "_current_turn_id", "") or "")
                _control = _registry.get(_current) if _registry is not None and _current else None
                remaining = getattr(_control, "remaining", None) if _control is not None else None
                # Retry a retryable tool failure directly (up to the configured
                # limit) before recording it as failed. This implements the
                # "if a capability fails, retry it, then fall back" contract
                # without waiting for the model to re-issue the call. A hard
                # "tool unavailable" error is not retried (it would never
                # succeed); only transient/retryable failures are retried.
                tool_max_retries = max(0, int(os.environ.get("NEXUS_TOOL_MAX_RETRIES", "2")))
                _ran_ok = False
                _last_exc = None
                content = ""
                try:
                    for _attempt in range(1, tool_max_retries + 1):
                        try:
                            if parallel_batch is not None and call_id in parallel_batch:
                                _ok, _c = parallel_batch[call_id]
                                if not _ok:
                                    raise RuntimeError(_c)  # normal error handling below
                            else:
                                tool_task = asyncio.ensure_future(self._run_tool(call))
                                if remaining is not None:
                                    content = redact_secrets(
                                        await asyncio.wait_for(tool_task, timeout=max(0.001, remaining))
                                    )
                                else:
                                    content = redact_secrets(await tool_task)
                            _ran_ok = True
                            break
                        except (asyncio.CancelledError, Exception) as _exc:  # noqa: PERF203
                            if isinstance(_exc, asyncio.CancelledError) and self._is_run_level_cancellation():
                                raise
                            _last_exc = _exc
                            if _attempt < tool_max_retries:
                                await self._emit_tool_event(
                                    call, status="retry",
                                    error=f"attempt {_attempt} failed: {redact_secrets(_exc)[:200]}",
                                )
                    if _ran_ok:
                        self._mark_repaired_actions(actions, call.name, round_index)
                        action = {"tool": call.name, "name": call.name, "params": dict(call.params or {}),
                                  "call_id": call_id, "output": content, "success": True,
                                  "status": "completed", "model_round": round_index,
                                  "exit_code": getattr(self, "_last_tool_exit_code", None),
                                  **plan_link}
                        self._transition_plan_step(
                            plan_link, "succeeded",
                            evidence={"tool": call.name, "call_id": call_id,
                                      "output": str(content or "")[:2000]},
                        )
                    else:
                        # Fall through to the existing failure handling below.
                        _exc = _last_exc if _last_exc is not None else RuntimeError("tool failed")
                        raise _exc
                except (asyncio.CancelledError, Exception) as exc:
                    if isinstance(exc, asyncio.CancelledError):
                        if self._is_run_level_cancellation():
                            raise
                        detail = str(exc).strip() or "the tool cancelled its operation"
                        exc = RuntimeError(f"tool cancelled: {detail}")
                    # Tool exceptions become model-visible observations and
                    # durable action evidence.  Keep them bounded and redact
                    # credential-shaped material before either boundary.
                    content = f"Error: {redact_secrets(exc)[:4000]}"
                    failure_signature = hashlib.sha256(
                        f"{call.name}:{json.dumps(call.params or {}, sort_keys=True, ensure_ascii=False)}:{content}".encode(
                            "utf-8", errors="replace"
                        )
                    ).hexdigest()[:16]
                    action = {"tool": call.name, "name": call.name, "params": dict(call.params or {}),
                              "call_id": call_id, "output": "", "error": content,
                              "success": False, "status": "failed", "model_round": round_index,
                              "exit_code": getattr(self, "_last_tool_exit_code", None),
                              "failure_signature": failure_signature,
                              "retryable": not self._is_unavailable_tool_error(content),
                              **plan_link}
                    self._transition_plan_step(
                        plan_link, "failed",
                        evidence={"tool": call.name, "call_id": call_id,
                                  "error": str(content or "")[:2000]},
                    )
                    signature = (str(call.name), json.dumps(call.params or {}, sort_keys=True,
                                                            ensure_ascii=False))
                    if self._is_unavailable_tool_error(content):
                        unavailable_retries[signature] = unavailable_retries.get(signature, 0) + 1
                actions.append(action)
                batch_outcomes.append(action)
                record_ledger = getattr(self, "_ledger_record", None)
                if callable(record_ledger):
                    record_ledger(action, bool(action.get("success")))
                try:
                    self._progress_record(
                        "tool_call",
                        signature=(
                            f"{call.name}:{json.dumps(call.params or {}, sort_keys=True, ensure_ascii=False)}"
                        ),
                        status="success" if action.get("success") else "error",
                    )
                    if action.get("success"):
                        self._reset_stall_hints()
                    if not action.get("success"):
                        await self._recovery_for_failure(
                            exc=RuntimeError(str(content or "")[:400]),
                            component_type="tool",
                            component_id=str(call.name),
                            operation="execute",
                            tool=str(call.name),
                            failure_class=(
                                FailureClass.TOOL_UNAVAILABLE
                                if self._is_unavailable_tool_error(content)
                                else FailureClass.TOOL_EXECUTION
                            ),
                        )
                except Exception:
                    pass
                # Oversized or empty tool results are bounded before entering
                # the model transcript; the durable full result (if any) is
                # archived on disk for a future ``continue``.
                bounded_content = await self._bounded_tool_result_async(
                    content, str(call.name), str(getattr(self, "_current_turn_id", "") or ""),
                    call_slot, str(getattr(self, "root_dir", "") or ""),
                )
                if action.get("success"):
                    # Keep durable action evidence bounded in the same way as
                    # the model transcript. Oversized full output remains in
                    # the sanitized archive referenced by bounded_content.
                    action["output"] = bounded_content
                await self._emit_tool_progress(
                    call,
                    "finished",
                    "success" if action.get("success") else "failed",
                    evidence=bounded_content if action.get("success") else "",
                    retry_reason=str(action.get("error") or "") if not action.get("success") else "",
                    plan_link=plan_link,
                )
                tool_message = {"role": "tool", "name": call.name,
                                "tool_call_id": call_id, "content": bounded_content}
                messages.append(tool_message)
                self._stamp_recent_messages(messages)
                if callable(persist_direct):
                    if callable(persist_direct_async):
                        await persist_direct_async(
                            tool_message,
                            str(getattr(self, "_current_turn_id", "") or ""),
                        )
                    else:
                        persist_direct(tool_message, str(getattr(self, "_current_turn_id", "") or ""))
                calls_executed += 1
                await self._direct_loop_state("OBSERVING")
                # CLOSED LOOP DETECTION: an identical (tool, params) call whose
                # OUTCOME is also unchanged `repeat_call_budget` times is not
                # making progress. Stop here instead of spending more provider
                # requests on it. Failed actions are governed by the repair
                # budget below; this detector owns the harder case of a call
                # that keeps *succeeding* with the same result while nothing
                # advances.
                # Identity is outcome-aware (OpenClaw semantics): a legitimate
                # poll/wait-until-ready workflow repeats the same call but sees
                # the result change, and must not be stopped. Only a call whose
                # normalized outcome is also unchanged is stagnation. A warning
                # tier fires one call before the stop so the model gets a
                # chance to change strategy without losing the turn.
                repeat_key = self._call_signature(call.name, {"params": call.params})
                repeat_counts[repeat_key] = repeat_counts.get(repeat_key, 0) + 1
                repeat_seen = repeat_counts[repeat_key]
                outcome_key = self._repeat_outcome_hash(action)
                last_outcome, stable_streak = repeat_outcomes.get(repeat_key, ("", 0))
                stable_streak = (
                    stable_streak + 1
                    if outcome_key and outcome_key == last_outcome else 1
                )
                repeat_outcomes[repeat_key] = (outcome_key, stable_streak)
                executed_signatures.append((repeat_key, outcome_key))
                if action["success"] and stable_streak >= max(2, int(self.repeat_call_budget)):
                    stagnation_response = self._stagnation_response(
                        str(call.name), stable_streak, actions
                    )
                    # The provider requires one tool result for every tool
                    # call in the assistant batch. Record explicit skipped
                    # results for the remainder so the persisted transcript
                    # stays a valid envelope for the next request/resume.
                    _skipped_count = await self._skip_remaining_batch_calls(
                        calls, call_slot, round_index,
                        "Skipped: the turn stopped because an earlier call in "
                        "this batch repeated without making progress.",
                        actions, batch_outcomes, messages,
                    )
                    calls_executed += _skipped_count
                    await self._emit_tool_batch_progress(batch_outcomes)
                    return {
                        "success": False, "response": stagnation_response,
                        "actions": actions, "tool_rounds": round_index + 1,
                        "calls_executed": calls_executed, "messages": messages,
                        "verification": self._verification_payload(
                            actions, calls_executed, stagnation_response,
                            "repeated identical tool call made no progress",
                        ),
                        "stagnation": {
                            "tool": str(call.name), "repeats": stable_streak,
                            "signature": repeat_key[:200],
                        },
                        "error": "repeated identical tool call made no progress",
                    }
                if (
                    action["success"]
                    and stable_streak >= max(2, int(self.repeat_call_budget) - 1)
                    and repeat_key not in repeat_warned
                ):
                    repeat_warned.add(repeat_key)
                    messages.append({
                        "role": "system",
                        "content": self._repeat_warning_message(
                            str(call.name), stable_streak
                        ),
                    })
                    self._stamp_recent_messages(messages)
                pingpong = self._pingpong_signal(executed_signatures)
                if pingpong is not None:
                    signature_a, signature_b, alternating = pingpong
                    if (
                        action["success"]
                        and alternating >= self.pingpong_stop_streak
                    ):
                        pingpong_response = self._pingpong_response(
                            signature_a, signature_b, alternating
                        )
                        _skipped_count = await self._skip_remaining_batch_calls(
                            calls, call_slot, round_index,
                            "Skipped: the turn stopped because the run entered "
                            "a ping-pong loop.",
                            actions, batch_outcomes, messages,
                        )
                        calls_executed += _skipped_count
                        await self._emit_tool_batch_progress(batch_outcomes)
                        return {
                            "success": False, "response": pingpong_response,
                            "actions": actions, "tool_rounds": round_index + 1,
                            "calls_executed": calls_executed, "messages": messages,
                            "verification": self._verification_payload(
                                actions, calls_executed, pingpong_response,
                                "alternating calls made no progress",
                            ),
                            "loop": {
                                "kind": "ping_pong",
                                "signature_a": signature_a[:200],
                                "signature_b": signature_b[:200],
                                "alternations": alternating,
                            },
                            "error": "alternating calls made no progress",
                        }
                    if (
                        action["success"]
                        and alternating >= self.pingpong_warning_streak
                        and not pingpong_warned
                    ):
                        pingpong_warned = True
                        messages.append({
                            "role": "system",
                            "content": self._pingpong_warning_message(
                                str(signature_a).split(":", 1)[0] or "tool",
                                str(signature_b).split(":", 1)[0] or "tool",
                                alternating,
                            ),
                        })
                        self._stamp_recent_messages(messages)
                if not action["success"]:
                    failure_signature = str(action.get("failure_signature") or "unknown")
                    repair_attempts = repair_attempts_by_signature.get(failure_signature, 0) + 1
                    repair_attempts_by_signature[failure_signature] = repair_attempts
                    required_parameters = []
                    try:
                        registry = getattr(self, "tool_registry", None)
                        entry = registry.get(call.name) if registry is not None else None
                        schema = getattr(entry, "schema", {}) if entry is not None else {}
                        definitions = schema.get("params") or {}
                        if isinstance(definitions, dict):
                            required_parameters = [
                                str(key) for key, definition in definitions.items()
                                if isinstance(definition, dict) and definition.get("required")
                            ]
                        required_parameters.extend(
                            str(key) for key in (schema.get("required") or [])
                            if str(key) not in required_parameters
                        )
                    except Exception:
                        required_parameters = []
                    failure_observation = {
                        "status": "failed",
                        "tool": call.name,
                        "call_id": call_id,
                        "attempt": repair_attempts,
                        "retryable_hint": bool(action.get("retryable", True)),
                        "failure_signature": action.get("failure_signature", ""),
                        "error": content[:1600],
                        "next_step": "Choose retry, alternate tool/parameters, or stop; do not claim success.",
                    }
                    if required_parameters:
                        failure_observation["required_parameters"] = required_parameters
                        failure_observation["next_step"] = (
                            f"Call {call.name} again with one JSON object containing every "
                            f"required parameter ({', '.join(required_parameters)}); never send {{}}."
                        )
                    messages.append({
                        "role": "system",
                        "content": (
                        "REPAIR REQUIRED: the previous tool call failed. Diagnose the "
                        "failure from the tool result, then choose a corrected tool "
                        "or corrected parameters. Do not repeat the identical call "
                        "unless you have a concrete reason it will now succeed. "
                        + (
                            f"For `{call.name}`, the required parameters are: "
                            f"{', '.join(required_parameters)}. Include all of them in the "
                            "next JSON arguments object; an empty object is invalid. "
                            if required_parameters else ""
                        )
                        + "The next model turn must choose retry, an alternative relevant "
                        "tool/provider, or stop. Never claim success without a verified "
                        "tool result. "
                            f"Structured failure observation: {json.dumps(failure_observation, ensure_ascii=False)}"
                        ),
                    })
                    if repair_attempts >= self.repair_attempt_budget:
                        hive_escalated = False
                        active_mode = getattr(self, "_active_mode_enabled", None)
                        hive_repair = getattr(self, "_hive_self_repair", None)
                        if not hive_repair_applied and callable(active_mode) and callable(hive_repair):
                            try:
                                if active_mode():
                                    proposal = await hive_repair(
                                        {"success": False, "actions": actions[-8:]},
                                        SimpleNamespace(original_input=task_desc),
                                    )
                                    if isinstance(proposal, list) and proposal:
                                        hive_repair_applied = True
                                        hive_escalated = True
                                        messages.append({
                                            "role": "system",
                                            "content": (
                                                "HIVE REPAIR PROPOSAL: native repair attempts "
                                                "were exhausted. Inspect this reviewed proposal, "
                                                "then make one corrected tool decision if justified. "
                                                "Do not claim success without fresh evidence.\n"
                                                + json.dumps(
                                                    proposal[:8],
                                                    ensure_ascii=False,
                                                    default=str,
                                                )[:6000]
                                            ),
                                        })
                                        self._stamp_recent_messages(messages)
                            except Exception as exc:
                                self.logger.debug("Hive self-repair escalation unavailable: %s", exc)
                        if not hive_escalated:
                            response = self._repair_exhausted_response(actions)
                            await self._emit_tool_batch_progress(batch_outcomes)
                            return {"success": False, "response": response, "actions": actions,
                                    "tool_rounds": round_index + 1,
                                    "calls_executed": calls_executed, "messages": messages,
                                    "verification": self._verification_payload(
                                        actions, calls_executed, response, "repair attempts exhausted"
                                    ),
                                    "error": "repair attempts exhausted"}
                else:
                    # Repair budgets describe consecutive failure chains, not
                    # the lifetime total for a long task. Verified progress
                    # starts a fresh chain for any later unrelated failure.
                    repair_attempts_by_signature.clear()
                if not action["success"] and self._is_unavailable_tool_error(content):
                    signature = (str(call.name), json.dumps(call.params or {}, sort_keys=True,
                                                            ensure_ascii=False))
                    if unavailable_retries.get(signature, 0) >= 2:
                        response = self._unavailable_tool_response(call.name, content)
                        await self._emit_tool_batch_progress(batch_outcomes)
                        return {"success": False, "response": response, "actions": actions,
                                "tool_rounds": round_index + 1,
                                "calls_executed": calls_executed, "messages": messages,
                                "verification": self._verification_payload(
                                    actions, calls_executed, response, "repeated unavailable tool request"
                                ),
                                "error": "repeated unavailable tool request"}
                if not action["success"]:
                    # The provider requires one tool result for every tool
                    # call in an assistant batch.  We still stop side effects
                    # after the first failure, but record explicit skipped
                    # results so the next request is a valid transcript.
                    _skipped_count = await self._skip_remaining_batch_calls(
                        calls, call_slot, round_index,
                        "Skipped because an earlier tool call in this batch failed.",
                        actions, batch_outcomes, messages,
                    )
                    calls_executed += _skipped_count
                    break
            await self._emit_tool_batch_progress(batch_outcomes)
            self._last_run_had_tool_execution = True
            # Update the consecutive-failure streak from this round's real
            # outcomes (skipped placeholders do not count either way).
            round_results = [
                item for item in actions
                if item.get("model_round") == round_index
                and str(item.get("status") or "") != "skipped"
            ]
            if round_results and not any(
                item.get("success") or item.get("repaired") for item in round_results
            ):
                failure_streak += 1
            else:
                failure_streak = 0
            await self._direct_loop_state("REFLECTING")
        response, protocol_error = self._safe_terminal_response(
            last_text or "Tool loop reached its iteration limit.", actions
        )
        _verification = self._verification_payload(
            actions, calls_executed, response,
            protocol_error or "direct model/tool loop bound exhausted",
        )
        _verified_any = bool(_verification.get("verified_actions"))
        return {"success": False,
                "partial": _verified_any,
                "status": "completed_partial" if _verified_any else "failed",
                "response": response, "actions": actions,
                "tool_rounds": bound, "calls_executed": calls_executed,
                "messages": messages,
                "verification": _verification,
                "degradation": ["loop window exhausted before a final answer"],
                "error": protocol_error or "direct model/tool loop bound exhausted"}

    @staticmethod
    def _is_unavailable_tool_error(error: str) -> bool:
        text = str(error or "").lower()
        return (
            ("tool" in text and "not found" in text)
            or "unknown tool" in text
            or "tool registry unavailable" in text
            or "unavailable tool" in text
        )

    @staticmethod
    def _unavailable_tool_response(name: str, error: str) -> str:
        detail = str(error or "The tool was not available.").strip()
        return (f"I couldn't complete this request because the model requested the unavailable "
                f"tool `{name}` twice. No final answer was produced. Execution evidence: {detail}")

    @staticmethod
    def _repair_exhausted_response(actions: List[Dict[str, Any]]) -> str:
        failed = next(
            (item for item in reversed(actions)
             if not item.get("success") and not item.get("repaired")),
            {},
        )
        name = str(failed.get("name") or failed.get("tool") or "tool")
        detail = str(failed.get("error") or "the tool continued to fail").strip()
        return (f"I couldn't complete this request because repair attempts for `{name}` "
                f"were exhausted. No verified final result was produced. Evidence: {detail}")

    @classmethod
    def _safe_terminal_response(cls, text: str, actions: List[Dict[str, Any]]) -> Tuple[str, str]:
        """Prevent transport envelopes from becoming user-facing final text.

        The failed protocol is retained in the returned error/action evidence;
        only the raw provider envelope is replaced in the chat response.
        """
        response = str(text or "").strip()
        match = re.search(r"<function(?:=|:)\s*([\w.-]+)>[\s\S]*", response,
                          flags=re.IGNORECASE)
        if not match:
            return response, ""
        name = match.group(1)
        failed = next((item for item in reversed(actions)
                       if str(item.get("name") or item.get("tool") or "") == name and
                       not item.get("success")), None)
        detail = str((failed or {}).get("error") or
                     "The model returned a tool envelope instead of a final answer.").strip()
        safe = (f"I couldn't complete this request because the model returned a tool request "
                f"for `{name}` instead of a final answer. No final answer was produced.")
        return safe, f"unfinalized tool envelope for `{name}`: {detail}"

    def _model_turn_parts(self, raw: Any) -> Tuple[str, List[Any]]:
        message: Any = raw
        if isinstance(raw, dict):
            choices = raw.get("choices") or []
            message = (choices[0].get("message", choices[0]) if choices and isinstance(choices[0], dict)
                       else raw.get("message", raw))
        elif getattr(raw, "choices", None):
            choice = raw.choices[0]
            message = getattr(choice, "message", choice)
        content = self._part_content(message)
        calls = self._part_tool_calls(message)
        # Remember provider reasoning (DeepSeek thinking mode) so the next
        # assistant turn can echo ``reasoning_content`` back to the API.
        try:
            rc = message.get("reasoning_content") if isinstance(message, dict) else getattr(message, "reasoning_content", None)
            self._last_reasoning_content = rc if isinstance(rc, str) and rc.strip() else None
        except Exception:
            self.logger.debug("reasoning_content capture failed", exc_info=True)
        # Providers that expose only a text return type (including the local
        # LM Studio adapter) serialize *native* calls as this exact envelope.
        # Decode that transport format, but never interpret arbitrary prose or
        # inline ``name({...})`` text as a tool request.
        if not calls and "<function=" in content:
            # Parse the provider envelope independently of the registry so an
            # invalid/hallucinated name reaches the normal tool resolver and
            # is reported to the model for correction.
            from .tools import _TextToolCall
            for match in re.finditer(r"<function=([\w.-]+)>\s*(\{)", content):
                try:
                    args, _ = json.JSONDecoder().raw_decode(content[match.start(2):])
                except json.JSONDecodeError as exc:
                    calls.append(
                        _TextToolCall(
                            match.group(1), {},
                            argument_error=f"malformed JSON tool arguments: {exc.msg}",
                        )
                    )
                    continue
                if isinstance(args, dict):
                    calls.append(_TextToolCall(match.group(1), args))
        # Providers without native tool-call objects commonly emit one of the
        # explicit text protocols supported by the shared parser.  Keep this
        # bounded to structured envelopes/function syntax; ordinary prose is
        # never treated as an action.
        if not calls and content:
            try:
                from extensions.tools.built_in.nexus_tools.call_parser import parse_all_tool_calls

                registry = getattr(self, "tool_registry", None)
                known = set(registry.list_tools(include_unavailable=False)) if registry else set()
                known.update(getattr(self, "COMMAND_ALIASES", ()))
                for parsed in parse_all_tool_calls(content, known_tools=known):
                    calls.append(_TextToolCall(parsed["tool"], parsed["params"]))
            except Exception as exc:
                self.logger.debug("Structured text tool parsing failed: %s", exc)
        return content, calls

    @staticmethod
    def _part_content(message: Any) -> str:
        if isinstance(message, str):
            return message
        value = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
        if isinstance(value, list):
            return "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in value)
        return str(value or "")

    @staticmethod
    def _part_tool_calls(message: Any) -> List[Any]:
        calls = message.get("tool_calls", []) if isinstance(message, dict) else getattr(message, "tool_calls", [])
        from .tools import _TextToolCall
        from extensions.tools.built_in.nexus_tools.result import ToolArgumentError, parse_tool_arguments
        result = []
        for item in calls or []:
            function = item.get("function", item) if isinstance(item, dict) else getattr(item, "function", item)
            name = function.get("name", "") if isinstance(function, dict) else getattr(function, "name", "")
            arguments = function.get("arguments", {}) if isinstance(function, dict) else getattr(function, "arguments", {})
            argument_error = ""
            try:
                arguments = parse_tool_arguments(arguments, tool_name=str(name))
            except ToolArgumentError as exc:
                argument_error = str(exc)
                arguments = {}
            if isinstance(arguments, dict):
                marker = arguments.pop("__nexus_argument_error", "")
                arguments.pop("__nexus_raw_arguments", None)
                if marker:
                    argument_error = str(marker)
            call_id = item.get("id", "") if isinstance(item, dict) else getattr(item, "id", "")
            if name:
                result.append(_TextToolCall(
                    str(name), arguments if isinstance(arguments, dict) else {},
                    str(call_id), argument_error=argument_error,
                ))
        return result

    @staticmethod
    def _tool_call_dict(call: Any) -> Dict[str, Any]:
        return {"id": str(getattr(call, "call_id", "") or "call_v5"), "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.params or {}, ensure_ascii=False)}}
