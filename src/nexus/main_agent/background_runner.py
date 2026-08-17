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
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .durable_background import DurableBackgroundStore
from models.providers.core.reliability import redact_secrets


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
        # A coroutine object is single-use. Retrying it would await the same
        # object again and silently turn a recoverable retry into a failed
        # background task. Require a callable factory whenever retries are
        # requested so each attempt gets a fresh coroutine.
        if retries and inspect.isawaitable(coro) and not callable(coro):
            logger.warning(
                "[BACKGROUND] retries require a callable coroutine factory for %s",
                name or "task",
            )
            try:
                coro.close()
            except Exception:
                pass
            return None
        try:
            task = asyncio.create_task(self._run_bg_wrapper(coro, name, retries, on_done))
        except Exception as e:
            logger.warning("[BACKGROUND] failed to start background task: %s", e)
            return None
        tasks = self._v5_runner_tasks()
        tasks.add(task)
        def _cleanup_finished(done_task: asyncio.Task) -> None:
            """Remove the task and any priority/lane metadata it owns."""
            tasks.discard(done_task)
            try:
                by_id = self._v5_runner_task_by_id()
                meta = self._task_meta()
                lanes = self._task_lanes()
                owned_ids = [task_id for task_id, tracked in by_id.items() if tracked is done_task]
                for task_id in owned_ids:
                    by_id.pop(task_id, None)
                    meta.pop(task_id, None)
                    for lane_tasks in lanes.values():
                        lane_tasks.discard(task_id)
                if owned_ids:
                    self._notify_priority_lane_waiters()
            except Exception:
                logger.debug("[BACKGROUND] task metadata cleanup failed", exc_info=True)

        task.add_done_callback(_cleanup_finished)
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
                            payload={"name": label, "attempt": attempt, "error": redact_secrets(e)[:200]},
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
                        payload={"name": label, "error": redact_secrets(e)[:300]},
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

    def _durable_background_store(self) -> DurableBackgroundStore:
        """Return the process-shared SQLite ledger for opted-in jobs."""
        store = getattr(self, "_v5_durable_background_store", None)
        if store is None:
            root = getattr(self, "root_dir", None) or getattr(self, "_project_root", None) or os.getcwd()
            store = DurableBackgroundStore(str(root))
            self._v5_durable_background_store = store
        return store

    def register_durable_background_factory(self, factory_key: str, factory) -> bool:
        """Register a restart-safe factory under a stable key.

        The callable is deliberately process-local; only ``factory_key`` is
        persisted. A new process must register the key before recovery.
        """
        if not str(factory_key or "").strip() or not callable(factory):
            return False
        factories = getattr(self, "_v5_durable_background_factories", None)
        if factories is None:
            factories = {}
            self._v5_durable_background_factories = factories
        factories[str(factory_key)] = factory
        # Registration is the safe point at which a fresh process can
        # rehydrate jobs for this factory; unregistered jobs remain pending.
        try:
            self.recover_durable_background_tasks()
        except Exception:
            logger.debug("[BACKGROUND] durable recovery after registration failed", exc_info=True)
        self._ensure_durable_background_watchdog()
        return True

    def _ensure_durable_background_watchdog(self) -> bool:
        """Start one periodic stale-job recovery loop when an event loop exists."""
        current = getattr(self, "_v5_durable_watchdog_task", None)
        if current is not None and not current.done():
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Factories may be registered during synchronous construction.
            # The next registration/submission in the live loop starts it.
            return False
        try:
            interval = max(
                1.0,
                float(os.environ.get("NEXUS_DURABLE_WATCHDOG_INTERVAL", "30")),
            )
            stale_after = max(
                interval * 2.0,
                float(os.environ.get("NEXUS_DURABLE_STALE_AFTER", "300")),
            )
        except (TypeError, ValueError):
            interval, stale_after = 30.0, 300.0

        async def _watch() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.watchdog_durable_background_tasks(stale_after=stale_after)
                    # Also retry interrupted records left by a prior bounded
                    # cancellation once their old task has actually exited.
                    self.recover_durable_background_tasks()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "[BACKGROUND] durable watchdog pass failed",
                        exc_info=True,
                    )

        self._v5_durable_watchdog_task = loop.create_task(_watch())
        return True

    async def _stop_durable_background_watchdog(self) -> None:
        task = getattr(self, "_v5_durable_watchdog_task", None)
        self._v5_durable_watchdog_task = None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _schedule_durable_background_record(self, record: Dict[str, Any]) -> str:
        store = self._durable_background_store()
        task_id = str(record.get("task_id") or "")
        factory_key = str(record.get("factory_key") or "")
        factory = getattr(self, "_v5_durable_background_factories", {}).get(factory_key)
        if not task_id or not callable(factory):
            return ""
        owner_token = uuid.uuid4().hex
        claim_state = {"claimed": False}
        result_state = {"value": ""}

        async def attempt_factory():
            claimed = store.claim(task_id, owner_token)
            if not claimed and claim_state["claimed"]:
                # In-process retry: the row stays 'running' under our own
                # owner_token between attempts, so ``claim`` legitimately
                # returns False. Treat the still-owned row as claimed instead
                # of silently no-opping the retry and stranding the ledger.
                row = store.get(task_id) or {}
                claimed = (
                    str(row.get("status") or "") == "running"
                    and str(row.get("owner_token") or "") == owner_token
                )
            claim_state["claimed"] = claimed
            if not claimed:
                return None
            awaitable = factory()
            if not inspect.isawaitable(awaitable):
                result_state["value"] = awaitable
                return awaitable
            stop_heartbeat = asyncio.Event()

            async def renew_heartbeat() -> None:
                # The watchdog is conservative: a job gets several heartbeat
                # intervals before it can be reclaimed, and normal long jobs
                # remain alive without needing to know about this mechanism.
                interval = max(1.0, min(30.0, float(record.get("timeout_s") or 30.0) / 3.0))
                while not stop_heartbeat.is_set():
                    try:
                        await asyncio.wait_for(stop_heartbeat.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        store.heartbeat(task_id, owner_token=owner_token)

            heartbeat_task = asyncio.create_task(renew_heartbeat())
            try:
                result = await awaitable
                result_state["value"] = result
                return result
            finally:
                stop_heartbeat.set()
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)

        async def finished(error=None):
            if not claim_state["claimed"]:
                return
            if error is None:
                # Persist the terminal value for restart-safe inspection, but
                # keep the ledger under the same redaction contract as runtime
                # events and error diagnostics.
                store.complete(
                    task_id,
                    redact_secrets(result_state["value"])[:2000],
                    owner_token=owner_token,
                )
            else:
                store.fail(
                    task_id,
                    redact_secrets(error)[:2000],
                    owner_token=owner_token,
                )

        persisted_attempt = max(0, int(record.get("attempt", 0) or 0))
        remaining_retries = max(
            0,
            int(record.get("max_retries", 0) or 0) - persisted_attempt,
        )
        return self._submit_task_priority(
            str(record.get("name") or factory_key),
            attempt_factory,
            priority=int(record.get("priority", 0) or 0),
            timeout_s=float(record.get("timeout_s") or 0.0),
            retries=remaining_retries,
            lane=str(record.get("lane") or "default"),
            task_id=task_id,
            on_done=finished,
        )

    def submit_durable_background(
        self,
        factory_key: str,
        factory,
        *,
        name: str = "",
        priority: int = 0,
        timeout_s: float = 300.0,
        retries: int = 0,
        lane: str = "default",
    ) -> str:
        """Persist and start a restartable background job.

        ``factory_key`` must be registered again by a fresh process before
        calling :meth:`recover_durable_background_tasks`.
        """
        key = str(factory_key or "").strip()
        if not key or not callable(factory) or not self.register_durable_background_factory(key, factory):
            return ""
        task_id = f"durable_{key}_{uuid.uuid4().hex[:10]}"
        store = self._durable_background_store()
        store.create(
            task_id, key, str(name or key), max_retries=int(retries or 0),
            timeout_s=float(timeout_s or 0.0) or None,
            priority=int(priority or 0), lane=str(lane or "default"),
        )
        record = store.get(task_id) or {}
        scheduled = self._schedule_durable_background_record(record)
        if not scheduled:
            store.fail(task_id, "background task could not be scheduled")
            return ""
        return task_id

    def recover_durable_background_tasks(self) -> List[str]:
        """Requeue persisted pending/interrupted jobs with registered factories."""
        store = self._durable_background_store()
        if not getattr(self, "_v5_durable_recovery_initialized", False):
            store.recover_running()
            self._v5_durable_recovery_initialized = True
        active = set(self._v5_runner_task_by_id())
        recovered: List[str] = []
        records = store.list(("pending", "interrupted"))
        # Rehydrate in the same ordering used for live admission.  The lane
        # gate still arbitrates execution, but deterministic scheduling here
        # makes restart behavior observable and prevents creation-time order
        # from defeating persisted priority.
        records.sort(key=lambda record: (
            int(record.get("priority", 0) or 0),
            str(record.get("lane") or "default"),
            float(record.get("created_at", 0.0) or 0.0),
            str(record.get("task_id") or ""),
        ))
        for record in records:
            task_id = str(record.get("task_id") or "")
            if not task_id or task_id in active:
                continue
            if self._schedule_durable_background_record(record):
                recovered.append(task_id)
        return recovered

    async def watchdog_durable_background_tasks(
        self,
        stale_after: float = 300.0,
        *,
        cancel_timeout: float = 5.0,
    ) -> List[str]:
        """Reclaim and restart durable jobs whose heartbeat stopped.

        The stale job is cancelled before its stable task id is scheduled
        again, preventing an old completion callback from racing the new
        attempt. Cancellation is bounded: a task which ignores cancellation
        must not freeze the watchdog or block recovery of unrelated jobs. In
        that case the still-live task remains visible in the runner's active
        map, so the stable task id is not scheduled a second time until the
        old task actually exits. Unknown factory keys remain interrupted and
        are not run.
        """
        store = self._durable_background_store()
        stale_ids = store.recover_stalled(stale_after)
        if not stale_ids:
            return []
        by_id = self._v5_runner_task_by_id()
        active_tasks = [by_id.get(task_id) for task_id in stale_ids if by_id.get(task_id) is not None]
        for task in active_tasks:
            if task is not None and not task.done():
                task.cancel()
        if active_tasks:
            # Do not let a non-cooperative task turn the watchdog into another
            # stuck background task. ``asyncio.wait`` does not cancel the
            # still-pending tasks when its timeout expires; they remain fenced
            # by owner_token and are deliberately left in the active map.
            done, pending = await asyncio.wait(
                active_tasks,
                timeout=max(0.01, float(cancel_timeout)),
            )
            if done:
                await asyncio.gather(*done, return_exceptions=True)
            if pending:
                logger.warning(
                    "[BACKGROUND] stale durable task cancellation exceeded %.2fs; "
                    "deferring reschedule until the old task exits",
                    max(0.01, float(cancel_timeout)),
                )
        return self.recover_durable_background_tasks()

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
        lanes = getattr(self, "_v5_task_lanes_map", None)
        if lanes is None:
            lanes = {}
            self._v5_task_lanes_map = lanes
        return lanes

    def _task_meta(self) -> Dict[str, Dict[str, Any]]:
        """Return the lazy per-task meta map (``task_id -> {priority, seq, ...}``)."""
        meta = getattr(self, "_v5_task_meta_map", None)
        if meta is None:
            meta = {}
            self._v5_task_meta_map = meta
        return meta

    def _v5_runner_task_by_id(self) -> Dict[str, asyncio.Task]:
        """Return the lazy ``task_id -> asyncio.Task`` map. Never raises."""
        by_id = getattr(self, "_v5_runner_task_by_id_map", None)
        if by_id is None:
            by_id = {}
            self._v5_runner_task_by_id_map = by_id
        return by_id

    def _v5_idle_lanes(self) -> set:
        """Return the lazy set of lanes flagged idle (via ``_mark_lane_idle``)."""
        idle = getattr(self, "_v5_idle_lanes_set", None)
        if idle is None:
            idle = set()
            self._v5_idle_lanes_set = idle
        return idle

    def _priority_lane_limits(self) -> Dict[str, Optional[int]]:
        """Return configured lane admission limits.

        A lane is serial by default.  This makes priority meaningful at the
        admission boundary instead of only when the runner drains at close;
        callers that need parallel work can opt into a larger limit (or
        ``None`` for unbounded admission) with
        :meth:`configure_priority_lane`.
        """
        limits = getattr(self, "_v5_priority_lane_limits", None)
        if limits is None:
            limits = {}
            self._v5_priority_lane_limits = limits
        return limits

    def configure_priority_lane(
        self,
        lane: str,
        max_concurrency: Optional[int] = 1,
        *,
        max_wait_admissions: Optional[int] = 8,
    ) -> Optional[int]:
        """Configure bounded admission for a priority lane.

        ``None`` means unbounded admission; positive integers bound the
        number of active attempts in the lane.  ``max_wait_admissions`` is
        the bounded-aging threshold: once a task has waited through that
        many admissions, FIFO age takes precedence over numeric priority.
        The default for an
        unconfigured lane is one, which prevents low-priority work from
        monopolizing a lane before higher-priority work can be admitted.
        Returns the normalized value, or ``None`` for invalid input.
        """
        try:
            safe_lane = str(lane or "default")
            if max_concurrency is None:
                value = None
            else:
                value = max(1, int(max_concurrency))
            self._priority_lane_limits()[safe_lane] = value
            fairness = getattr(self, "_v5_priority_lane_fairness", None)
            if fairness is None:
                fairness = {}
                self._v5_priority_lane_fairness = fairness
            fairness[safe_lane] = (
                None if max_wait_admissions is None
                else max(1, int(max_wait_admissions))
            )
            self._notify_priority_lane_waiters()
            return value
        except Exception:
            return None

    def _priority_lane_state(self) -> Dict[str, Any]:
        state = getattr(self, "_v5_priority_lane_state", None)
        if state is None:
            state = {"active": {}, "running": {}, "admissions": {}}
            self._v5_priority_lane_state = state
        return state

    def _priority_lane_condition(self):
        condition = getattr(self, "_v5_priority_lane_condition", None)
        if condition is None:
            condition = asyncio.Condition()
            self._v5_priority_lane_condition = condition
        return condition

    def _notify_priority_lane_waiters(self) -> None:
        """Wake admission waiters without making cleanup callbacks raise."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notify_priority_lane_waiters_async())
        except Exception:
            pass

    async def _notify_priority_lane_waiters_async(self) -> None:
        try:
            async with self._priority_lane_condition():
                self._priority_lane_condition().notify_all()
        except Exception:
            pass

    async def _acquire_priority_lane(self, task_id: str, lane: str) -> bool:
        """Wait until ``task_id`` is the next admitted task in ``lane``."""
        safe_lane = str(lane or "default")
        limit = self._priority_lane_limits().get(safe_lane, 1)
        if limit is None:
            return True
        state = self._priority_lane_state()
        condition = self._priority_lane_condition()
        async with condition:
            while True:
                meta = self._task_meta().get(task_id)
                if meta is None:
                    return False
                running = state["running"].setdefault(safe_lane, set())
                active = int(state["active"].get(safe_lane, 0) or 0)
                pending = [
                    candidate for candidate in self._lane_tasks(safe_lane)
                    if candidate not in running
                ]
                fairness = getattr(self, "_v5_priority_lane_fairness", {}).get(safe_lane, 8)
                admission_count = int(state["admissions"].get(safe_lane, 0) or 0)
                if fairness is not None:
                    aged = [
                        candidate for candidate in pending
                        if admission_count - int(
                            self._task_meta().get(candidate, {}).get("admission_epoch", admission_count)
                        ) >= int(fairness)
                    ]
                else:
                    aged = []
                if aged:
                    candidate = min(
                        aged,
                        key=lambda item: int(self._task_meta().get(item, {}).get("seq", 0) or 0),
                    )
                else:
                    candidate = pending[0] if pending else ""
                if active < int(limit) and pending and candidate == task_id:
                    running.add(task_id)
                    state["active"][safe_lane] = active + 1
                    state["admissions"][safe_lane] = admission_count + 1
                    return True
                await condition.wait()

    async def _release_priority_lane(self, task_id: str, lane: str) -> None:
        safe_lane = str(lane or "default")
        state = self._priority_lane_state()
        try:
            async with self._priority_lane_condition():
                running = state["running"].setdefault(safe_lane, set())
                if task_id in running:
                    running.discard(task_id)
                    state["active"][safe_lane] = max(
                        0, int(state["active"].get(safe_lane, 0) or 0) - 1
                    )
                self._priority_lane_condition().notify_all()
        except Exception:
            pass

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
        task_id: str = "",
        on_done=None,
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
            task_id = str(task_id or f"bg_{safe_name}_{uuid.uuid4().hex[:8]}")
            seq = self._task_seq()
            meta = self._task_meta()
            meta[task_id] = {
                "name": safe_name,
                "priority": int(priority or 0),
                "timeout_s": float(timeout_s or 0.0) or None,
                "retries": int(retries or 0),
                "lane": safe_lane,
                "seq": seq,
                "admission_epoch": int(
                    self._priority_lane_state()["admissions"].get(safe_lane, 0) or 0
                ),
            }
            self._task_lanes().setdefault(safe_lane, set()).add(task_id)
            wrapped = self._timeout_wrapped_coro(coro, float(timeout_s or 0.0))

            async def admitted_attempt():
                admitted = await self._acquire_priority_lane(task_id, safe_lane)
                if not admitted:
                    return None
                try:
                    return await wrapped()
                finally:
                    await self._release_priority_lane(task_id, safe_lane)

            task = self._run_background(
                admitted_attempt,
                name=safe_name,
                retries=int(retries or 0),
                on_done=on_done,
            )
            if task is None:
                meta.pop(task_id, None)
                self._task_lanes().get(safe_lane, set()).discard(task_id)
                self._notify_priority_lane_waiters()
                return ""
            self._v5_runner_task_by_id()[task_id] = task
            return task_id
        except Exception as e:
            logger.debug("[BACKGROUND] priority submit failed: %s", e)
            return ""

    def _runner_sort_key(self, task: Any) -> Tuple[int, int]:
        """Ordering key for a tracked task: ``(priority, seq)``, lower = sooner."""
        try:
            # The index is task_id -> asyncio.Task, so resolve the reverse
            # mapping before looking up priority/sequence metadata.
            task_id = next(
                (candidate for candidate, tracked in self._v5_runner_task_by_id().items() if tracked is task),
                "",
            )
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
