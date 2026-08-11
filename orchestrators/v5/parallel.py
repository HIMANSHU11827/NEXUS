"""V5 parallel step executor — V1-style smart parallelism.

Ported from ``NexusLoop._execute_tools`` in ``orchestrators/loop.py``
(lines 2143-2227): read-only tool steps run concurrently via
``asyncio.gather``, write/command steps run sequentially to avoid state
collisions, reasoning-only steps complete instantly, and a repetition
guard prevents the same tool+params from executing twice in one turn.

Also provides map-reduce Send-style fan-out (``_run_superstep``) with
LangGraph superstep semantics — the write branch is applied only when every
read-only branch succeeded — plus Magentic-One-style stall detection and
replan hints (``_detect_stall`` / ``_replan_hint``).

This mixin is composed into ``NexusLoopV5`` and returns ACTION dicts in
the same shape as ``core.NexusLoopV5._fallback_execute`` so callers
can switch between the sequential and parallel executors transparently.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from providers.reliability import redact_secrets


class _ToolCall:
    """Minimal duck-typed call object: ``_run_tool`` only needs .name/.params/.call_id."""

    __slots__ = ("name", "params", "call_id")

    def __init__(self, name: str, params: Dict[str, Any], call_id: str):
        self.name = name
        self.params = params
        self.call_id = call_id


class V5ParallelExecutor:
    """Execute plan steps with V1-style smart parallelism."""

    _READ_ONLY_TOOLS = frozenset({
        "reading", "code_search", "web_search", "test_runner",
        "deep_research", "hive", "git_ops", "memory_search",
        "skill_lookup", "graph_query",
    })

    _COMMAND_ALIASES = frozenset({
        "bash", "run_command", "terminal", "shell", "execute_command",
    })

    @staticmethod
    def _normalise_result(result: Any) -> Tuple[bool, str, Optional[str]]:
        """Preserve structured tool failure/success results exactly."""
        if isinstance(result, Exception):
            return False, "", redact_secrets(result)[:4000]
        if isinstance(result, dict) and "success" in result:
            return (
                bool(result.get("success")),
                str(result.get("output") or ""),
                redact_secrets(result.get("error") or "")[:4000] or None,
            )
        if hasattr(result, "success"):
            return (
                bool(getattr(result, "success", False)),
                str(getattr(result, "output", "") or ""),
                redact_secrets(getattr(result, "error", "") or "")[:4000] or None,
            )
        return True, str(result), None

    def _is_read_only_tool(self, name: str, params: Dict[str, Any]) -> bool:
        """Classify a tool step as read-only (parallel) or write (sequential)."""
        try:
            registry = getattr(self, "tool_registry", None)
            if registry is not None:
                entry = registry.get(name)
                if entry is not None:
                    is_read_only = getattr(entry, "is_read_only", None)
                    if is_read_only is not None:
                        try:
                            return bool(is_read_only(params))
                        except TypeError:
                            return bool(is_read_only())
        except Exception as e:
            self.logger.info("Could not classify tool '%s' as read-only: %s", name, e)
        if name in self._COMMAND_ALIASES:
            return False
        return name in self._READ_ONLY_TOOLS

    def _step_action(self, index: int, description: str, result: Any) -> Dict[str, Any]:
        """Build one ACTION dict in ``_fallback_execute`` shape.

        Must stay an instance method: the body calls ``self._normalise_result``,
        so a ``@staticmethod`` decorator here makes every call site
        (``_run_steps_parallel``) raise ``NameError: name 'self' is not
        defined`` on the first tool step.
        """
        success, output, error = self._normalise_result(result)
        return {
            "step_id": f"step_{index}",
            "description": description,
            "success": success,
            "output": output,
            **({"error": error} if error else {}),
        }

    async def _run_steps_parallel(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute plan steps with V1-style smart parallelism.

        Args:
            steps: plan steps shaped ``{"description", "tool", "params"}``
                (``tool`` may be empty for reasoning-only steps).

        Returns:
            ACTION dicts (same shape as ``_fallback_execute``) in input order.
        """
        actions: List[Optional[Dict[str, Any]]] = [None] * len(steps)
        read_steps: List[Tuple[int, _ToolCall]] = []
        write_steps: List[Tuple[int, _ToolCall]] = []
        seen_signatures: Set[Tuple[str, str]] = set()

        for index, step in enumerate(steps):
            description = str(step.get("description") or "")
            tool = str(step.get("tool") or "").strip()
            params = dict(step.get("params") or {})

            if not tool:
                actions[index] = {
                    "step_id": f"step_{index}",
                    "description": description,
                    "success": True,
                    "output": f"Reasoning recorded; no external action executed: {description}",
                    "verified": False,
                    "execution_mode": "reasoning",
                }
                continue

            try:
                signature = (tool, json.dumps(params, sort_keys=True))
            except (TypeError, ValueError):
                signature = (tool, repr(params))
            if signature in seen_signatures:
                self.logger.info(
                    "Repetition guard: tool '%s' already executed this turn with identical params",
                    tool,
                )
                actions[index] = {
                    "step_id": f"step_{index}",
                    "description": description,
                    "success": False,
                    "output": "",
                    "error": (
                        f"Repetition guard: tool '{tool}' already executed "
                        "this turn with identical params"
                    ),
                }
                continue
            seen_signatures.add(signature)

            call = _ToolCall(tool, params, f"step_{index}")
            if self._is_read_only_tool(tool, params):
                read_steps.append((index, call))
            else:
                write_steps.append((index, call))

        if read_steps:
            results = await asyncio.gather(
                *(self._run_tool(call) for _, call in read_steps),
                return_exceptions=True,
            )
            for (index, call), result in zip(read_steps, results):
                actions[index] = self._step_action(index, steps[index].get("description") or "", result)
                actions[index]["tool"] = call.name

        for index, call in write_steps:
            try:
                result = await self._run_tool(call)
            except Exception as e:
                result = e
            actions[index] = self._step_action(index, steps[index].get("description") or "", result)
            actions[index]["tool"] = call.name

        return [action for action in actions if action is not None]

    # ─────────────────────────────────────────────────────────────────────
    # MAP-REDUCE SEND-STYLE SUPERSTEP (LangGraph superstep semantics)
    # ─────────────────────────────────────────────────────────────────────

    async def _run_superstep(
        self,
        steps: List[Dict[str, Any]],
        *,
        apply_if_all: bool = True,
        executor: Optional[Callable[[Any], Any]] = None,
    ) -> Dict[str, Any]:
        """Run a map-reduce Send-style superstep with branch gating.

        Read-only steps fan out in parallel; writer steps run sequentially
        and only when every read-only step succeeded (``apply_if_all=True``,
        the default). Otherwise writers are skipped and reported as blocked.

        Args:
            steps: Plan steps shaped ``{"description", "tool", "params",
                "read_only": bool}`` (``read_only`` defaults False;
                classification falls back to ``_is_read_only_tool``).
            apply_if_all: Apply the writer branch only when all read-only
                steps succeeded (LangGraph superstep semantics).
            executor: Optional async callable ``await executor(call)`` used
                instead of ``self._run_tool`` (duck call objects are
                ``_ToolCall`` instances: ``.name`` / ``.params`` / ``.call_id``).

        Returns:
            ``{"applied": bool, "results": [{"index", "success",
            "output"|"error"}...], "blocked": ["step i: writer skipped"]}``.
            Never raises.
        """
        read_calls: List[Tuple[int, Optional[_ToolCall], str]] = []
        write_calls: List[Tuple[int, _ToolCall, str]] = []
        try:
            if not isinstance(steps, list):
                steps = []
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                description = str(step.get("description") or "")
                tool = str(step.get("tool") or "").strip()
                params = dict(step.get("params") or {})
                if not tool:
                    read_calls.append((index, None, description))
                    continue
                call = _ToolCall(tool, params, f"ss_{index}")
                if bool(step.get("read_only", False)) or self._is_read_only_tool(
                    tool, params
                ):
                    read_calls.append((index, call, description))
                else:
                    write_calls.append((index, call, description))
        except Exception as e:  # noqa: BLE001
            self.logger.warning("Superstep classification failed: %s", e)
            return {"applied": False, "results": [], "blocked": [str(e)]}

        results: List[Dict[str, Any]] = []
        blocked: List[str] = []
        try:
            pending = [(index, call) for index, call, _ in read_calls]
            if pending:
                outcomes = await asyncio.gather(
                    *(
                        self._run_superstep_one(index, call, description, executor)
                        for index, call, description in read_calls
                    ),
                    return_exceptions=True,
                )
                for (index, call), outcome in zip(pending, outcomes):
                    if isinstance(outcome, Exception):
                        results.append(
                            {"index": index, "success": False, "error": str(outcome)}
                        )
                    else:
                        results.append(outcome)

            reads_ok = all(result.get("success") for result in results)
            if write_calls and apply_if_all and not reads_ok:
                for index, _call, _desc in write_calls:
                    blocked.append(f"step {index}: writer skipped")
            else:
                for index, call, description in write_calls:
                    results.append(
                        await self._run_superstep_one(index, call, description, executor)
                    )
            return {
                "applied": not blocked,
                "results": results,
                "blocked": blocked,
            }
        except Exception as e:  # noqa: BLE001
            self.logger.warning("Superstep execution failed: %s", e)
            return {"applied": False, "results": results, "blocked": blocked or [str(e)]}

    async def _run_superstep_one(
        self,
        index: int,
        call: Optional[_ToolCall],
        description: str,
        executor: Optional[Callable[[Any], Any]] = None,
    ) -> Dict[str, Any]:
        """Execute one superstep branch; reasoning-only steps complete instantly."""
        try:
            if call is None:
                return {
                    "index": index,
                    "success": True,
                    "output": f"Reasoning recorded; no external action executed: {description}",
                    "verified": False,
                    "execution_mode": "reasoning",
                }
            if executor is not None:
                output = await executor(call)
            else:
                output = await self._run_tool(call)
            if isinstance(output, dict) and "success" in output:
                result = {
                    "index": index,
                    "success": bool(output.get("success")),
                    "output": str(output.get("output") or ""),
                }
                if output.get("error"):
                    result["error"] = str(output["error"])
                return result
            if hasattr(output, "success"):
                result = {
                    "index": index,
                    "success": bool(getattr(output, "success", False)),
                    "output": str(getattr(output, "output", "") or ""),
                }
                if getattr(output, "error", None):
                    result["error"] = str(output.error)
                return result
            success, text, error = self._normalise_result(output)
            result = {"index": index, "success": success, "output": text}
            if error:
                result["error"] = error
            return result
        except Exception as e:  # noqa: BLE001
            return {"index": index, "success": False, "error": redact_secrets(e)[:4000]}

    # ─────────────────────────────────────────────────────────────────────
    # STALL DETECTION + REPLAN HINT (Magentic-One lesson)
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _stall_count(history: List[Dict[str, Any]]) -> int:
        """Count consecutive trailing attempts that failed or repeated a step."""
        if not isinstance(history, list) or not history:
            return 0
        count = 0
        run_description: Optional[str] = None
        for index in range(len(history) - 1, -1, -1):
            entry = history[index]
            if not isinstance(entry, dict):
                break
            if not bool(entry.get("success", True)):
                count += 1
                continue
            description = str(entry.get("description") or "")
            if run_description is None:
                run_description = description
            if description and description == run_description:
                count += 1
            else:
                break
        return count

    def _detect_stall(self, history: List[Dict[str, Any]], threshold: int = 3) -> bool:
        """True when the trailing plan attempts show a stall.

        A stall is ``threshold`` consecutive trailing entries that failed
        (``success`` False) or repeated the same step description. Never
        raises.
        """
        try:
            if threshold < 1:
                return False
            return self._stall_count(history) >= threshold
        except Exception:
            return False

    def _replan_hint(self, history: List[Dict[str, Any]]) -> str:
        """Return a replan hint when the trailing attempts show a stall.

        Returns:
            "Repeated failure detected (N consecutive attempts). Change
            approach — do not repeat the same steps." when stalled, else "".
            Never raises.
        """
        try:
            count = self._stall_count(history)
            if count < 3:
                return ""
            return (
                f"Repeated failure detected ({count} consecutive attempts). "
                "Change approach — do not repeat the same steps."
            )
        except Exception:
            return ""
