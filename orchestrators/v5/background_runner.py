"""V5BackgroundRunner — generic background task runner for the V5 loop.

Fire-and-forget tasks with optional retry/backoff, lifecycle events
(background.started/done/retry/failed), counters, and cooperative draining
via _drain_runner_tasks.

This mixin is intentionally dependency-free: it imports nothing from ``core``
or any other ``orchestrators.v5`` module (avoiding circular imports) and
guards every path with try/except, so a failing background task can never
break the loop. Tasks are tracked in this mixin's own set
(``self._v5_runner_tasks_set``) — deliberately distinct from V5Evolution's
``self._v5_bg`` — and are drained by the coordinator through
``_drain_runner_tasks()`` (hooked into ``V5Evolution.aclose``).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


class V5BackgroundRunner:
    """Mixin giving the V5 loop a generic fire-and-forget background runner.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    - ``self._emit_runtime_event(event_type, title, status, *, event_id,
      parent_id=None, payload=None, error="")`` - async canonical runtime
      event emitter; ``event_id`` is keyword-only and always passed
      explicitly. Guarded access, may be missing or fail at runtime.

    Owned state (created lazily, never assumed to exist):
    - ``self._v5_runner_tasks_set`` - set of in-flight runner tasks.
    - ``self._v5_runner_counts`` - dict of "started"/"completed"/"failed".
    """

    def _v5_runner_tasks(self) -> set:
        """Return the set of in-flight background tasks (lazily created).

        Stored on ``self._v5_runner_tasks_set`` — deliberately distinct from
        V5Evolution's ``self._v5_bg`` so the two mixins never collide. Never
        raises.
        """
        tasks = getattr(self, "_v5_runner_tasks_set", None)
        if tasks is None:
            tasks = set()
            self._v5_runner_tasks_set = tasks
        return tasks

    def _runner_counters(self) -> Dict[str, int]:
        """Return the lazily-created lifecycle counters dict.

        Stored on ``self._v5_runner_counts`` with keys ``started``,
        ``completed`` and ``failed`` defaulting to 0. Never raises.
        """
        counts = getattr(self, "_v5_runner_counts", None)
        if counts is None:
            counts = {"started": 0, "completed": 0, "failed": 0}
            self._v5_runner_counts = counts
        return counts

    def _run_background(
        self, coro, *, name: str = "", retries: int = 0, on_done=None
    ) -> Optional[asyncio.Task]:
        """Schedule a fire-and-forget background task and track it.

        ``coro`` may be a coroutine object, a future, or a zero-arg callable
        returning an awaitable. The task is tracked in this mixin's task set
        (discarded on completion), the ``started`` counter is bumped, and a
        ``background.started`` event is emitted. Returns the task, or None
        when creation fails (e.g. no running loop). Never raises.
        """
        try:
            task = asyncio.create_task(self._run_bg_wrapper(coro, name, retries, on_done))
        except Exception as e:
            logger.warning("[BACKGROUND] failed to start background task: %s", e)
            return None
        tasks = self._v5_runner_tasks()
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        label = name or "task"
        try:
            counters = self._runner_counters()
            counters["started"] = counters.get("started", 0) + 1
        except Exception:
            pass
        try:
            emit = asyncio.create_task(
                self._emit_runtime_event(
                    "background.started",
                    label,
                    "running",
                    event_id=f"bg_{label}_{counters.get('started', 0)}",
                    payload={"name": label},
                )
            )
            tasks.add(emit)
            emit.add_done_callback(tasks.discard)
        except Exception as e:
            logger.debug("[BACKGROUND] failed to emit started event: %s", e)
        return task

    async def _run_bg_wrapper(self, coro, name, retries, on_done) -> None:
        """Execute ``coro`` with optional retry/backoff and lifecycle events.

        A zero-arg callable is invoked to obtain its awaitable; coroutine
        objects and futures are awaited directly. On success the ``completed``
        counter bumps and ``background.done`` fires; transient failures retry
        with exponential backoff capped at 30s (``background.retry`` each
        attempt); exhaustion fires ``background.failed`` and bumps ``failed``.
        ``on_done`` is called with no arguments on success and with the
        exception on failure (awaited when awaitable, guarded). Never raises.
        """
        label = name or "task"
        counters = self._runner_counters()
        attempt = 0
        while True:
            try:
                if (
                    callable(coro)
                    and not inspect.iscoroutine(coro)
                    and not inspect.isawaitable(coro)
                ):
                    result = await coro()
                else:
                    result = await coro
                try:
                    counters["completed"] = counters.get("completed", 0) + 1
                    await self._emit_runtime_event(
                        "background.done",
                        label,
                        "done",
                        event_id=f"bg_{label}_{counters.get('completed', 0)}",
                        payload={"name": label, "attempt": attempt + 1},
                    )
                except Exception:
                    pass
                if callable(on_done):
                    try:
                        finished = on_done()
                        if inspect.isawaitable(finished):
                            await finished
                    except Exception:
                        pass
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                attempt += 1
                if attempt <= retries:
                    try:
                        await self._emit_runtime_event(
                            "background.retry",
                            label,
                            "running",
                            event_id=f"bg_{label}_r{attempt}",
                            payload={"name": label, "attempt": attempt, "error": str(e)[:200]},
                        )
                    except Exception:
                        pass
                    try:
                        await asyncio.sleep(min(2 ** attempt, 30))
                    except Exception:
                        pass
                    continue
                try:
                    counters["failed"] = counters.get("failed", 0) + 1
                    await self._emit_runtime_event(
                        "background.failed",
                        label,
                        "failed",
                        event_id=f"bg_{label}_f{counters.get('failed', 0)}",
                        payload={"name": label, "error": str(e)[:300]},
                    )
                except Exception:
                    pass
                if callable(on_done):
                    try:
                        finished = on_done(e)
                        if inspect.isawaitable(finished):
                            await finished
                    except Exception:
                        pass
                return

    def _runner_stats(self) -> Dict[str, Any]:
        """Return lifecycle counters plus the count of active tasks.

        Never raises; any failure yields an empty-ish stats dict.
        """
        try:
            stats = dict(self._runner_counters())
            stats["active"] = len(self._v5_runner_tasks())
            return stats
        except Exception:
            return {}

    async def _drain_runner_tasks(self) -> None:
        """Wait for all in-flight background tasks to finish (cooperative).

        Re-checks the task set after each gather because the done callbacks
        remove tasks as they complete. Tasks are gathered in priority order
        (lower ``priority`` first, then submission ``seq`` — OpenClaw queue
        lanes lesson). V1 ``aclose`` parity. Never raises.
        """
        tasks = self._v5_runner_tasks()
        while tasks:
            ordered = sorted(tasks, key=self._runner_sort_key)
            await asyncio.gather(*tuple(ordered), return_exceptions=True)
            tasks = self._v5_runner_tasks()

    # ─────────────────────────────────────────────────────────────────────
    # PRIORITY / LANE / TIMEOUT SUBMISSION (V5 #18: OpenClaw queue lanes +
    # message priority + per-task timeout + idle watchdog). All defensive.
    # ─────────────────────────────────────────────────────────────────────

    def _task_lanes(self) -> Dict[str, set]:
        """Return the lazy lane map (``lane -> set of task ids``). Never raises."""
        lanes = getattr(self, "_task_lanes", None)
        if lanes is None:
            lanes = {}
            self._task_lanes = lanes
        return lanes

    def _task_meta(self) -> Dict[str, Dict[str, Any]]:
        """Return the lazy per-task meta map (``task_id -> {priority, seq, ...}``)."""
        meta = getattr(self, "_task_meta", None)
        if meta is None:
            meta = {}
            self._task_meta = meta
        return meta

    def _v5_runner_task_by_id(self) -> Dict[str, asyncio.Task]:
        """Return the lazy ``task_id -> asyncio.Task`` map. Never raises."""
        by_id = getattr(self, "_v5_runner_task_by_id", None)
        if by_id is None:
            by_id = {}
            self._v5_runner_task_by_id = by_id
        return by_id

    def _v5_idle_lanes(self) -> set:
        """Return the lazy set of lanes flagged idle (via ``_mark_lane_idle``)."""
        idle = getattr(self, "_v5_idle_lanes_set", None)
        if idle is None:
            idle = set()
            self._v5_idle_lanes_set = idle
        return idle

    def _task_seq(self) -> int:
        """Bump and return the lazy submission sequence counter. Never raises."""
        try:
            seq = int(getattr(self, "_v5_runner_seq", 0) or 0) + 1
        except Exception:
            seq = 1
        self._v5_runner_seq = seq
        return seq

    def _timeout_wrapped_coro(self, coro, timeout_s: float):
        """Return a zero-arg callable running ``coro`` under ``asyncio.wait_for``.

        A timeout surfaces as ``asyncio.TimeoutError`` inside the retry
        wrapper, so it is treated like any other failure (retry/backoff when
        retries remain, otherwise ``background.failed``).
        """
        async def _run():
            awaitable = (
                coro()
                if callable(coro) and not inspect.iscoroutine(coro) and not inspect.isawaitable(coro)
                else coro
            )
            if timeout_s and float(timeout_s) > 0:
                return await asyncio.wait_for(awaitable, float(timeout_s))
            return await awaitable
        return _run

    def _submit_task_priority(
        self,
        name: str,
        coro,
        *,
        priority: int = 0,
        timeout_s: float = 300.0,
        retries: int = 0,
        lane: str = "default",
    ) -> str:
        """Submit a priority/lane/timed background task; the task id, or "" on failure.

        Records the task in ``lane`` with its ``(priority, seq)`` ordering key
        (lower priority = sooner), enforces a per-task ``asyncio.wait_for``
        timeout, and delegates the actual execution to the existing
        ``_run_background`` (retry/backoff preserved). ``coro`` may be a
        coroutine object, an awaitable, or a zero-arg callable returning one;
        for retries to re-run, pass a callable. Never raises.
        """
        try:
            safe_lane = str(lane or "default")
            safe_name = str(name or "task")
            task_id = f"bg_{safe_name}_{uuid.uuid4().hex[:8]}"
            seq = self._task_seq()
            meta = self._task_meta()
            meta[task_id] = {
                "name": safe_name,
                "priority": int(priority or 0),
                "timeout_s": float(timeout_s or 0.0) or None,
                "retries": int(retries or 0),
                "lane": safe_lane,
                "seq": seq,
            }
            self._task_lanes().setdefault(safe_lane, set()).add(task_id)
            wrapped = self._timeout_wrapped_coro(coro, float(timeout_s or 0.0))
            task = self._run_background(wrapped, name=safe_name, retries=int(retries or 0))
            if task is None:
                meta.pop(task_id, None)
                self._task_lanes().get(safe_lane, set()).discard(task_id)
                return ""
            self._v5_runner_task_by_id()[task_id] = task
            return task_id
        except Exception as e:
            logger.debug("[BACKGROUND] priority submit failed: %s", e)
            return ""

    def _runner_sort_key(self, task: Any) -> Tuple[int, int]:
        """Ordering key for a tracked task: ``(priority, seq)``, lower = sooner."""
        try:
            task_id = self._v5_runner_task_by_id().get(task, "")
            meta = self._task_meta().get(task_id, {})
            return (
                int(meta.get("priority", 0) or 0),
                int(meta.get("seq", 0) or 0),
            )
        except Exception:
            return (0, 0)

    def _lane_tasks(self, lane: str) -> List[str]:
        """Return the task ids in ``lane`` sorted by ``(priority, seq)``; [] on failure."""
        try:
            meta = self._task_meta()
            ids = list(self._task_lanes().get(str(lane or "default"), set()) or [])
            return sorted(
                ids,
                key=lambda tid: (
                    int(meta.get(tid, {}).get("priority", 0) or 0),
                    int(meta.get(tid, {}).get("seq", 0) or 0),
                ),
            )
        except Exception:
            return []

    def _mark_lane_idle(self, lane: str) -> None:
        """Flag ``lane`` as idle so the next ``_drain_idle`` cancels its pending tasks."""
        try:
            self._v5_idle_lanes().add(str(lane or "default"))
        except Exception:
            pass

    async def _drain_idle(self, lane: str = "") -> int:
        """Cancel pending tasks in idle-flagged lanes; drop finished bookkeeping.

        Conservative: cancellation only applies to lanes previously flagged
        with ``_mark_lane_idle``; finished tasks' bookkeeping (meta/lane
        entries) is always cleared. Returns the number of tasks cancelled.
        Never raises.
        """
        dropped = 0
        try:
            lanes = self._task_lanes()
            idle = self._v5_idle_lanes()
            by_id = self._v5_runner_task_by_id()
            meta = self._task_meta()
            if lane:
                groups: List[Tuple[str, List[str]]] = [
                    (str(lane), list(lanes.get(str(lane), set()) or []))
                ]
            else:
                groups = [
                    (name, list(ids)) for name, ids in lanes.items()
                ]
            for group_name, ids in groups:
                for task_id in ids:
                    task = by_id.get(task_id)
                    if task is not None and not task.done() and group_name in idle:
                        try:
                            task.cancel()
                            dropped += 1
                        except Exception:
                            pass
                    if task is None or task.done():
                        by_id.pop(task_id, None)
                        meta.pop(task_id, None)
                        lanes.get(group_name, set()).discard(task_id)
            return dropped
        except Exception:
            return 0
