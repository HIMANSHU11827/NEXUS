"""V5Evolution — background evolution & learning for the V5 loop.

V5: EvolutionLog win/lose, SelfImprovementEngine, gap backlog,
MemoryForge crystallize, SkillCurator, ToolForge auto-creation.

This mixin is intentionally dependency-free: it imports nothing from ``core``
or any other ``orchestrators.v5`` module (avoiding circular imports) and loads
every evolution module lazily inside the methods that use it. All evolution
work runs in the background after a response streams out, so a failure here
must never break the loop — every path is guarded with try/except and
``asyncio.gather(..., return_exceptions=True)``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

_FAILURE_MARKERS = ("traceback", "error", "failed", "not found", "exit code", "non-zero")
_GAPS_CAP = 100


class V5Evolution:
    """Background evolution & learning mixin for ``NexusLoopV5``.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.root`` - str root directory of the project.
    - ``self.session_id`` - str id of the current session.
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    - ``self.runtime`` - object with ``.turn_history`` (list of turn objects
      carrying ``role``/``user_input``/``content``) and ``.current_turn``;
      may be None in exotic cases, everything is guarded.
    - ``self.kernel`` - may be None; when present supports
      ``_get_or_init(key, factory)`` and is used to cache the EvolutionLog.

    Owned state (created lazily, never assumed to exist):
    - ``self._v5_evolution_log`` - cached ``EvolutionLog`` instance.
    - ``self._v5_bg`` - set of background finalization tasks.
    - ``self._v5_gaps`` - list of gap records detected during the session.
    """

    def _evolution_enabled(self) -> bool:
        """True unless env ``NEXUS_EVOLUTION`` explicitly says 0/false/no.

        Defaults to enabled (``NEXUS_EVOLUTION`` unset or empty means on).
        Never raises.
        """
        try:
            value = os.getenv("NEXUS_EVOLUTION", "1") or "1"
        except Exception:
            return True
        return str(value).strip().lower() not in ("0", "false", "no")

    def _evolution_log(self) -> Optional[Any]:
        """Return a cached ``EvolutionLog`` (kernel-backed when available).

        Prefers ``self.kernel._get_or_init("evolution_log", factory)`` when
        the kernel supports it, otherwise constructs ``EvolutionLog(self.root)``
        directly. The instance is cached on ``self._v5_evolution_log`` and the
        result is None on any failure. Never raises.
        """
        cached = getattr(self, "_v5_evolution_log", None)
        if cached is not None:
            return cached
        try:
            from evolution.logs import EvolutionLog

            kernel = getattr(self, "kernel", None)
            get_or_init = getattr(kernel, "_get_or_init", None)
            if callable(get_or_init):
                log = get_or_init("evolution_log", lambda: EvolutionLog(self.root))
            else:
                log = EvolutionLog(self.root)
            self._v5_evolution_log = log
            return log
        except Exception as e:
            self.logger.warning(f"[EVOLVE] evolution log unavailable: {e}")
            return None

    def _v5_background_tasks(self) -> set:
        """Return the set of background finalization tasks (lazily created).

        Owned by this mixin under ``self._v5_bg`` — deliberately distinct from
        V1's ``self._background_tasks`` so the V5 loop never interferes with
        V1 background task bookkeeping. Never raises.
        """
        tasks = getattr(self, "_v5_bg", None)
        if tasks is None:
            tasks = set()
            self._v5_bg = tasks
        return tasks

    def _gaps_found(self) -> List[Dict[str, Any]]:
        """Return the lazily-created list of gaps detected this session.

        Stored on ``self._v5_gaps``; the caller may mutate the returned list
        in place. Never raises.
        """
        gaps = getattr(self, "_v5_gaps", None)
        if gaps is None:
            gaps = []
            self._v5_gaps = gaps
        return gaps

    def _session_messages(self) -> List[Dict[str, str]]:
        """Build ``[{"role": ..., "content": ...}]`` from the recorded turns.

        Each turn contributes its role (default ``"user"``) and its
        ``user_input`` (falling back to ``content``); empty messages are
        skipped. ``runtime.current_turn`` is appended when present and not
        already represented in the history. Returns [] on any failure.
        """
        try:
            runtime = getattr(self, "runtime", None)
            messages: List[Dict[str, str]] = []
            if runtime is None:
                return messages
            history = getattr(runtime, "turn_history", None) or []
            for turn in history:
                role = str(getattr(turn, "role", "user") or "user")
                content = str(getattr(turn, "user_input", "") or getattr(turn, "content", "") or "")
                if content.strip():
                    messages.append({"role": role, "content": content})
            current = getattr(runtime, "current_turn", None)
            if current is not None and not any(current is t for t in history):
                role = str(getattr(current, "role", "user") or "user")
                content = str(getattr(current, "user_input", "") or getattr(current, "content", "") or "")
                if content.strip() and content not in [m["content"] for m in messages]:
                    messages.append({"role": role, "content": content})
            return messages
        except Exception:
            return []

    async def _evolve_log(self, success: bool, task_desc: str) -> None:
        """Step 1: record a win/lose in the EvolutionLog (V5).

        V1 origin: ``orchestrators/loop.py`` lines 2952-2963. Best-effort —
        a failure logs a warning and is swallowed.
        """
        try:
            log = self._evolution_log()
            if log is None:
                return
            fn = log.win if success else log.lose
            await asyncio.to_thread(
                fn,
                "agent",
                "nexus",
                f"Session {'completed' if success else 'failed'}: {task_desc[:80]}",
                0.0,
                {"task": task_desc},
            )
        except Exception as e:
            self.logger.warning(f"[EVOLVE] _evolve_log failed: {e}")

    async def _evolve_self_improve(self, messages) -> None:
        """Step 2: SelfImprovementEngine analysis, top-3 actions + backlog.

        V1 origin: ``orchestrators/loop.py`` lines 2965-2997. The engine runs
        in a thread; each of the top 3 actions is recorded as an improvement
        and persisted to the durable backlog. Fully guarded, never raises.
        """
        try:
            from evolution.self_improvement.scripts.engine import SelfImprovementEngine

            se = SelfImprovementEngine(self.root)
            record = await asyncio.to_thread(se.analyze_session, messages)
            if record is not None and getattr(record, "actions", None):
                log = self._evolution_log()
                if log is not None:
                    for action in list(record.actions)[:3]:
                        await asyncio.to_thread(log.improvement, action)
                try:
                    from evolution.backlog import queue_improvement_action

                    for action in list(record.actions)[:3]:
                        await asyncio.to_thread(
                            queue_improvement_action,
                            {
                                "action": action,
                                "source": "self_improvement.analyze_session",
                                "session_id": getattr(record, "session_id", "") or "",
                                "score": getattr(record, "score", None),
                                "summary": (getattr(record, "summary", "") or "")[:300],
                            },
                            self.root,
                        )
                except Exception:
                    self.logger.warning("[EVOLVE] backlog queue failed", exc_info=True)
        except Exception:
            self.logger.warning("[EVOLVE] _evolve_self_improve failed", exc_info=True)

    async def _evolve_gap_forge(self) -> None:
        """Step 3: backlog every gap found during the session, then clear them.

        V1 origin: ``orchestrators/loop.py`` lines 2999-3011, simplified — V1
        retried gaps with ``_fill_gap``; here each gap is queued to the durable
        backlog for offline consumption. The gap list is cleared only when it
        is a real list. Never raises.
        """
        gaps = self._gaps_found()
        if not gaps:
            return
        self.logger.info(f"[EVOLVE:GAP] Backlogging {len(gaps)} gap(s)")
        try:
            from evolution.backlog import queue_improvement_action
        except Exception as e:
            self.logger.warning(f"[EVOLVE] backlog unavailable: {e}")
            return
        for gap in gaps:
            try:
                action = (
                    gap.get("action", "investigate")
                    if gap.get("action")
                    else f"investigate tool failure: {gap.get('name', '?')}"
                )
                await asyncio.to_thread(
                    queue_improvement_action,
                    {
                        "action": action,
                        "source": "v5_gap_detection",
                        "session_id": getattr(self, "session_id", "") or "",
                        "score": None,
                        "summary": (gap.get("observation") or "")[:300],
                    },
                    self.root,
                )
            except Exception:
                self.logger.warning("[EVOLVE] gap backlog failed", exc_info=True)
        if isinstance(gaps, list):
            gaps.clear()

    async def _evolve_memory_crystallize(self, messages) -> None:
        """Step 4: crystallize assistant learnings into long-term memory.

        V1 origin: ``orchestrators/loop.py`` lines 3075-3097. Assistant
        messages longer than 100 chars become a ``MemoryForge`` memory named
        after the session. Fully guarded, never raises.
        """
        try:
            learnings = [
                str(m.get("content") or "")[:300]
                for m in (messages or [])
                if isinstance(m, dict)
                and m.get("role") == "assistant"
                and len(m.get("content") or "") > 100
            ]
            if learnings:
                from evolution.memory_forge.scripts.forge import MemoryForge

                forge = MemoryForge(self.root)
                await asyncio.to_thread(
                    forge.forge,
                    f"session_{self.session_id}",
                    f"Session learnings: {'; '.join(learnings[:3])}",
                )
        except Exception:
            self.logger.warning("[EVOLVE] _evolve_memory_crystallize failed", exc_info=True)

    async def _evolve_record_experience(self, task_desc: str, success: bool) -> None:
        """Step 6: close the meta-learning loop by recording the real outcome.

        Before this existed, ``MetaLearningLayer.record_experience`` was never
        called anywhere in production: ``optimize()`` read a strategy table
        that only tests ever wrote to, so the "learning" loop had a live read
        end and a dead write end. Each finished turn now contributes one real
        experience, which is what makes ``_select_strategy`` and the adaptive
        learning rate reflect actual behaviour. Fully guarded; never raises.
        """
        meta = getattr(self, "meta_learning", None)
        record = getattr(meta, "record_experience", None)
        if not callable(record):
            return
        try:
            from datetime import datetime

            from .meta import Experience

            turn = getattr(getattr(self, "runtime", None), "current_turn", None)
            strategy = str(
                (getattr(turn, "metadata", {}) or {}).get("strategy") or "direct_loop"
            )
            verified = bool(getattr(self, "_last_run_verified", False))
            # Outcome is graded, not binary: a run that succeeded *and* passed
            # verification is worth more than an unverified success, so a
            # strategy that merely looks finished cannot outrank one that is
            # actually evidenced.
            outcome = 1.0 if (success and verified) else (0.6 if success else 0.0)
            await asyncio.to_thread(
                record,
                Experience(
                    task_id=str(getattr(turn, "turn_id", "") or self.session_id),
                    strategy=strategy,
                    outcome=outcome,
                    timestamp=datetime.now(),
                    context={
                        "task": str(task_desc or "")[:300],
                        "verified": verified,
                        "session_id": str(getattr(self, "session_id", "") or ""),
                    },
                ),
            )
        except Exception:
            self.logger.warning("[EVOLVE] _evolve_record_experience failed", exc_info=True)

    async def _maybe_run_curator(self) -> None:
        """Step 5: idle-run the SkillCurator.

        V1 origin: ``orchestrators/loop.py`` lines 3202-3213. V1 gates on the
        curator's ``enabled`` flag and a 3600s idle window; this mixin
        simplifies that to an always-attempt call inside try/except — the
        curator itself is safe to run repeatedly. Never raises.
        """
        try:
            from evolution.curator.scripts.curator import SkillCurator

            curator = SkillCurator(self.root)
            run_once = getattr(curator, "run_once", None)
            if callable(run_once):
                await asyncio.to_thread(run_once)
        except Exception as e:
            self.logger.debug(f"[EVOLVE] curator run failed: {e}")

    async def _run_evolution_tasks(self, task_desc: str, messages, success: bool) -> None:
        """Run all evolution steps in parallel (V1 ``_finalize_session`` parity).

        Fires ``_fire_session_end_hooks(task_desc, messages)`` first when the
        core provides it (V1 fires ``on_session_end`` before evolution), then
        gathers log / self-improve / gap-forge / memory-crystallize / curator
        with ``return_exceptions=True`` so one failure never blocks the rest.
        """
        if not self._evolution_enabled():
            return
        fire = getattr(self, "_fire_session_end_hooks", None)
        if callable(fire):
            await fire(task_desc, messages)
        await asyncio.gather(
            self._evolve_log(success, task_desc),
            self._evolve_self_improve(messages),
            self._evolve_gap_forge(),
            self._evolve_memory_crystallize(messages),
            self._maybe_run_curator(),
            self._evolve_record_experience(task_desc, success),
            return_exceptions=True,
        )

    def _start_background_finalization(self, task_desc: str, messages, success: bool) -> None:
        """Kick off evolution tasks without delaying the response stream.

        V1 origin: ``orchestrators/loop.py`` lines 2933-2937. Creates an
        ``asyncio.Task`` tracked in this mixin's own task set; the done
        callback discards the task so the set never grows stale. A failure to
        start (e.g. no running loop) only logs a warning.
        """
        try:
            task = asyncio.create_task(
                self._run_evolution_tasks(task_desc, list(messages), success)
            )
            tasks = self._v5_background_tasks()
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        except Exception as e:
            self.logger.warning(f"[EVOLVE] background finalization failed to start: {e}")

    async def _drain_background_tasks(self) -> None:
        """Wait for all in-flight background tasks to finish.

        V1 origin: ``orchestrators/loop.py`` lines 2946-2950 (``aclose``).
        Re-checks the task set after each gather because the done callbacks
        remove tasks as they complete. Never raises.
        """
        tasks = self._v5_background_tasks()
        while tasks:
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
            tasks = self._v5_background_tasks()

    async def aclose(self) -> None:
        """Drain the mixin's background tasks before the loop shuts down."""
        await self._drain_background_tasks()
        drain_runner = getattr(self, "_drain_runner_tasks", None)
        if callable(drain_runner):
            try:
                await drain_runner()
            except Exception:
                pass
        stop_scheduler = getattr(self, "_stop_scheduler", None)
        if callable(stop_scheduler):
            try:
                stop_scheduler()
            except Exception:
                pass

    def _handle_evolution_gaps(self, tool_calls, observations) -> None:
        """Deterministically detect tool-failure gaps from observations.

        Scans the joined observation text for failure markers ("traceback",
        "error", "failed", "not found", "exit code", "non-zero") and records a
        ``tool_failure`` gap — deduplicated by tool name, capped at 100 entries.
        No LLM is involved; never raises.
        """
        try:
            obs_text = "\n".join(str(o) for o in (observations or []) if str(o).strip())
            if not obs_text:
                return
            if not any(marker in obs_text.lower() for marker in _FAILURE_MARKERS):
                return
            name = "?"
            if tool_calls:
                name = str(getattr(tool_calls[0], "name", None) or "?")
            gaps = self._gaps_found()
            if any(g.get("name") == name for g in gaps):
                return
            gaps.append(
                {
                    "type": "tool_failure",
                    "name": name,
                    "observation": obs_text[:300],
                }
            )
            if len(gaps) > _GAPS_CAP:
                del gaps[: len(gaps) - _GAPS_CAP]
        except Exception:
            self.logger.debug("[EVOLVE] _handle_evolution_gaps failed")

    async def _handle_tool_failure(self, tc, error: Exception) -> None:
        """Auto-create a missing tool via ToolForge when a call fails.

        V1 origin: ``orchestrators/loop.py`` lines 3109-3126. Only triggers
        for "not found" / "unknown tool" / "no such tool" errors; a created
        tool is recorded as an improvement in the EvolutionLog. Any failure is
        logged at debug level and recorded as a ``missing_tool`` gap.
        """
        try:
            name = str(getattr(tc, "name", None) or "?")
            msg = str(error).lower()
            if not any(kw in msg for kw in ("not found", "unknown tool", "no such tool")):
                return
            self.logger.info(f"[EVOLVE] Tool '{name}' not found — attempting ToolForge...")
            from evolution.tool_forge.scripts.engine import ToolForge

            forge = ToolForge(self.root)
            result = await asyncio.to_thread(
                forge.forge,
                {
                    "name": name,
                    "description": f"Auto-created to fulfill: {name}",
                    "params": getattr(tc, "params", {}) or {},
                },
            )
            if result.get("created"):
                log = self._evolution_log()
                if log is not None:
                    await asyncio.to_thread(log.improvement, f"Auto-created tool '{name}'")
                self.logger.info(f"[EVOLVE] Tool '{name}' created successfully")
        except Exception as e:
            self.logger.debug(f"[EVOLVE] ToolForge failed: {e}")
            self._gaps_found().append(
                {
                    "type": "missing_tool",
                    "name": str(getattr(tc, "name", None) or "?"),
                    "error": str(error),
                }
            )
