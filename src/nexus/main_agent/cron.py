"""V5Cron — scheduled task execution for the V5 loop. One-shot delayed tasks via tasks.scheduler.NexusTaskScheduler with CronLifecycle state tracking; thread-safe runner bridges into the async loop."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from models.providers.core.reliability import redact_secrets


logger = logging.getLogger(__name__)


class V5Cron:
    """Scheduled & one-shot task execution mixin for ``NexusLoopV5``.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.run`` - async turn runner taking ``user_input``; invoked from
      the scheduler thread, bridged into the running event loop.
    - ``self._loop`` - optional asyncio loop; when running, scheduled tasks
      are bridged with ``asyncio.run_coroutine_threadsafe``, otherwise each
      task runs in its own ``asyncio.run`` on the scheduler thread.
    - ``self.logger`` - logger exposing ``.debug``/``.info``/``.warning``.
    - ``self._emit_runtime_event(event_type, title, status, *, event_id,
      parent_id=None, payload=None, error="")`` - async event producer.

    Owned state (created lazily, never assumed to exist):
    - ``self._v5_cron_scheduler`` - cached ``NexusTaskScheduler`` instance.
    - ``self._v5_cron_lifecycle`` - cached ``CronLifecycle`` instance.

    Note: this mixin does not define ``aclose`` (``V5Evolution`` already owns
    it); the coordinator hooks ``_stop_scheduler`` into shutdown.
    """

    def _task_scheduler(self) -> Optional[Any]:
        """Return the cached ``NexusTaskScheduler``, building it lazily.

        Constructed with ``self._cron_runner`` as the loop runner; the
        constructor starts a daemon thread, so the scheduler is only built
        when a task is actually scheduled. None on any failure; never raises.
        """
        cached = getattr(self, "_v5_cron_scheduler", None)
        if cached is not None:
            return cached
        try:
            from nexus.tasks.scheduler import NexusTaskScheduler

            scheduler = NexusTaskScheduler(
                self._cron_runner,
                state_path=os.path.join(
                    str(getattr(self, "root_dir", ".")), ".nexus_v5", "scheduled_tasks.json"
                ),
            )
            self._v5_cron_scheduler = scheduler
            return scheduler
        except Exception as e:
            self.logger.warning(f"[CRON] task scheduler unavailable: {e}")
            return None

    def _running_loop(self) -> Optional[Any]:
        """Return the running asyncio loop, if any.

        Prefers ``asyncio.get_running_loop()`` (the loop thread), then the
        host-provided ``self._loop`` when it is running (scheduler-thread
        bridging). None otherwise. Never raises.
        """
        try:
            loop = asyncio.get_running_loop()
            if loop is not None:
                return loop
        except RuntimeError:
            pass
        loop = getattr(self, "_loop", None)
        if loop is not None and bool(getattr(loop, "is_running", lambda: False)()):
            return loop
        return None

    def _cron_emit(self, event_type: str, title: str, status: str, payload: Dict[str, Any]) -> None:
        """Emit a cron runtime event from any context; never raises.

        On the loop thread the event is scheduled with ``ensure_future``
        (safe from sync and async call sites); on a foreign thread it is
        bridged through the running loop when one is known, else dropped.
        """
        emitter = getattr(self, "_emit_runtime_event", None)
        if not callable(emitter):
            return
        try:
            loop = self._running_loop()
            if loop is None:
                return
            coro = emitter(
                event_type,
                title,
                status,
                event_id=f"cron_{uuid.uuid4().hex}",
                payload=payload,
            )
            task = asyncio.ensure_future(coro)
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        except Exception:
            pass

    def _task_policy(self) -> Dict[str, Dict[str, Any]]:
        """Return the lazy per-task policy map (``task_id -> {priority, timeout_s}``).

        ``NexusTaskScheduler.schedule`` has no priority/timeout parameters, so
        the policy is recorded here and consulted at run time
        (``_cron_runner`` wraps the run in ``asyncio.wait_for``). Never raises.
        """
        # The backing attribute must NOT be named ``_task_policy``: that is
        # this method itself, so ``getattr`` would return the bound method and
        # every caller would operate on a non-dict (silently failing both
        # ``_schedule_task_priority`` and ``_cron_runner``).
        policy = getattr(self, "_v5_task_policy_map", None)
        if policy is None:
            policy = {}
            self._v5_task_policy_map = policy
        return policy

    def _schedule_task_priority(
        self, task_id: str, *, priority: int = 0, timeout_s: float = 300.0
    ) -> bool:
        """Schedule a one-shot cron task with a recorded priority/timeout policy.

        The policy is stored under ``task_id`` (which is also used as the
        task description, so ``_cron_runner`` can look it up at run time) and
        the run is wrapped with ``asyncio.wait_for(timeout_s)`` when the task
        fires. Returns True when scheduled, False on failure. Never raises.
        """
        try:
            safe_id = str(task_id or "cron_task")
            policy = self._task_policy()
            policy[safe_id] = {
                "priority": int(priority or 0),
                "timeout_s": float(timeout_s or 0.0) or None,
            }
            msg = self._schedule_task(safe_id, safe_id, 0)
            if msg is None:
                policy.pop(safe_id, None)
                return False
            return True
        except Exception as e:
            self.logger.warning(f"[CRON] priority schedule failed: {e}")
            return False

    def _cron_runner(self, task_desc: str) -> None:
        """Run a scheduled task from the scheduler thread, never raising.

        When a running loop is known the task is bridged with
        ``asyncio.run_coroutine_threadsafe`` (a done callback records the
        outcome); otherwise ``asyncio.run`` executes it on this thread.
        A per-task timeout recorded via ``_schedule_task_priority`` wraps the
        run in ``asyncio.wait_for`` (a timeout surfaces as a failed task).
        ``CronLifecycle.run_task``/``complete_task``/``fail_task`` are
        called around execution, each guarded individually.
        """
        task_id = f"cron_{uuid.uuid4().hex}"
        try:
            lifecycle = self._cron_lifecycle()
            if lifecycle is not None:
                try:
                    lifecycle.run_task(task_id)
                except Exception:
                    pass
        except Exception:
            lifecycle = None
        try:
            policy = self._task_policy().get(task_desc) or {}
            timeout_s = float(policy.get("timeout_s") or 0.0) or None
            run_coro = self.run(task_desc)
            if timeout_s is not None:
                run_coro = asyncio.wait_for(run_coro, timeout_s)
            loop = self._running_loop()
            if loop is not None:
                future = asyncio.run_coroutine_threadsafe(run_coro, loop)
                future.add_done_callback(
                    lambda fut: self._cron_record_result(lifecycle, task_id, fut)
                )
            else:
                try:
                    asyncio.run(run_coro)
                    self._cron_record_result(lifecycle, task_id, None)
                except Exception as e:
                    self._cron_record_result(lifecycle, task_id, None, redact_secrets(e)[:4000])
        except Exception as e:
            self._cron_record_result(lifecycle, task_id, None, redact_secrets(e)[:4000])

    def _cron_record_result(
        self,
        lifecycle: Optional[Any],
        task_id: str,
        future: Optional[Any],
        error: str = "",
    ) -> None:
        """Record success/failure against the cron lifecycle, if present.

        Prefers the explicit ``error`` string, then a cancelled/raised
        ``future``; otherwise marks the task completed. Never raises.
        """
        try:
            if lifecycle is None:
                return
            if error:
                lifecycle.fail_task(task_id, redact_secrets(error)[:4000])
                return
            if future is not None:
                if future.cancelled():
                    lifecycle.fail_task(task_id, "cancelled")
                    return
                try:
                    exc = future.exception()
                except Exception as e:
                    exc = e
                if exc is not None:
                    lifecycle.fail_task(task_id, redact_secrets(exc)[:4000])
                    return
            lifecycle.complete_task(task_id)
        except Exception:
            pass

    def _cron_lifecycle(self) -> Optional[Any]:
        """Return the cached ``CronLifecycle``, building it lazily.

        Imported from ``lifecycle.cron_lifecycle`` inside the method to avoid
        circular imports. None on any failure; never raises.
        """
        cached = getattr(self, "_v5_cron_lifecycle", None)
        if cached is not None:
            return cached
        try:
            from nexus.lifecycle.managers.cron_lifecycle import CronLifecycle

            lifecycle = CronLifecycle()
            self._v5_cron_lifecycle = lifecycle
            return lifecycle
        except Exception as e:
            self.logger.debug(f"[CRON] cron lifecycle unavailable: {e}")
            return None

    def _schedule_task(self, name: str, task_desc: str, delay_seconds: int) -> Optional[str]:
        """Schedule a one-shot task after ``delay_seconds``; returns status text.

        Uses ``NexusTaskScheduler.schedule`` and emits a ``cron.scheduled``
        runtime event; the cron lifecycle records the schedule when present.
        Returns None when the scheduler is unavailable; never raises.
        """
        try:
            scheduler = self._task_scheduler()
            if scheduler is None:
                return None
            msg = scheduler.schedule(name, task_desc, delay_seconds)
            self._cron_emit(
                "cron.scheduled",
                f"Scheduled task: {name}",
                "running",
                {"name": name, "delay_seconds": delay_seconds},
            )
            lifecycle = self._cron_lifecycle()
            if lifecycle is not None:
                try:
                    lifecycle.schedule_task(
                        f"cron_{name}_{int(time.time())}", name, f"delay {delay_seconds}s"
                    )
                except Exception:
                    pass
            return msg
        except Exception as e:
            self.logger.warning(f"[CRON] schedule failed: {e}")
            return None

    def _list_scheduled_tasks(self) -> List[Dict[str, Any]]:
        """Return the scheduler's pending tasks; [] on any failure."""
        try:
            scheduler = self._task_scheduler()
            if scheduler is None:
                return []
            return list(scheduler.list_tasks())
        except Exception:
            return []

    def _cron_stats(self) -> Dict[str, Any]:
        """Return cron lifecycle statistics; {} when unavailable."""
        try:
            lifecycle = self._cron_lifecycle()
            if lifecycle is None:
                return {}
            return dict(lifecycle.get_stats())
        except Exception:
            return {}

    def _stop_scheduler(self) -> None:
        """Stop the scheduler daemon thread if one was ever built.

        Uses the cached scheduler attribute directly so shutdown never
        constructs a new scheduler (construction starts a daemon thread).
        Signals ``_stop_event`` and joins the thread briefly. Never raises.
        """
        try:
            scheduler = getattr(self, "_v5_cron_scheduler", None)
            if scheduler is None:
                return
            stop_event = getattr(scheduler, "_stop_event", None)
            if stop_event is not None:
                try:
                    stop_event.set()
                except Exception:
                    pass
            thread = getattr(scheduler, "_thread", None)
            if thread is not None:
                try:
                    thread.join(timeout=2)
                except Exception:
                    pass
        except Exception:
            pass
