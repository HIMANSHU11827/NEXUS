"""Always-on 24/7 task driver for NEXUS.

Leases tasks from the durable SQLite queue (``queue.store.TaskQueue``) and runs
each one through ``orchestrators.NexusLoop``, draining every
event the loop emits.

Standalone usage
----------------
    # run the driver forever (2 workers)
    python -m queue.driver --workers 2

    # enqueue a task
    python -m queue.enqueue "refactor the auth module"
    python -m queue.driver --enqueue "refactor the auth module"

Embedded usage (see ``start_queue_driver``)
-------------------------------------------
    from queue.driver import start_queue_driver
    task = start_queue_driver(kernel)          # inside a running event loop
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from .store import TaskQueue
from .status import QueueRuntimeStatus
from nexus.control_store import ControlStore
from nexus.runtime import build_resume_prompt

log = logging.getLogger("nexus.queue.driver")

DEFAULT_IDLE_SLEEP = 2.0            # seconds between empty-lease polls
DEFAULT_LEASE_TIMEOUT = 3600        # seconds a leased task may run
DEFAULT_EXECUTION_TIMEOUT = 3600    # hard cap prevents an unattended hang
DEFAULT_REQUEUE_AFTER = 30          # seconds before a failed task is retried
REAP_INTERVAL = 60.0                # seconds between requeue_expired_leases()
MAX_SUMMARY_CHARS = 4000


def _resolve_root(kernel: Any = None) -> str:
    for attr in ("root", "root_dir", "project_root"):
        val = getattr(kernel, attr, None)
        if isinstance(val, str) and val:
            return val
    return os.environ.get("NEXUS_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )


class QueueDriver:
    """Continuously lease-and-execute queued NEXUS tasks."""

    def __init__(
        self,
        kernel: Any = None,
        queue: Optional[TaskQueue] = None,
        workers: int = 1,
        idle_sleep: float = DEFAULT_IDLE_SLEEP,
        lease_timeout: int = DEFAULT_LEASE_TIMEOUT,
        execution_timeout: float = DEFAULT_EXECUTION_TIMEOUT,
        requeue_after: float = DEFAULT_REQUEUE_AFTER,
        db_path: Optional[str] = None,
        root: Optional[str] = None,
        status_path: Optional[str] = None,
        mission_runner: Any = None,
        control_store: Optional[ControlStore] = None,
    ) -> None:
        self.kernel = kernel
        self.root = os.path.abspath(root) if root else _resolve_root(kernel)
        self.queue = queue or TaskQueue(db_path=db_path, root=self.root)
        # A supplied queue may be backed by an isolated workspace (tests,
        # embedded workers, or a tenant-specific deployment). Keep canonical
        # control records in that same root; otherwise recycled queue IDs can
        # resolve to stale links in the project-wide control database.
        if root is None and queue is not None:
            queue_root = getattr(self.queue, "root", None)
            if isinstance(queue_root, str) and queue_root:
                self.root = os.path.abspath(queue_root)
        self.control_store = control_store or ControlStore(self.root)
        self.workers = max(1, int(workers))
        self.idle_sleep = float(idle_sleep)
        self.lease_timeout = int(lease_timeout)
        self.execution_timeout = max(0.0, float(execution_timeout or 0.0))
        self.requeue_after = float(requeue_after)
        self.runtime_status = QueueRuntimeStatus(self.root, path=status_path)

        # Long-horizon mission runner (queue/mission.py). When present, the
        # driver reconciles each task outcome back into its mission ledger and
        # advances active missions (enqueues the next milestone) whenever the
        # queue goes idle — so an epic goal keeps producing work 24/7 by itself.
        self.mission_runner = mission_runner

        self._stopping = False
        self._tasks: List[asyncio.Task] = []
        self._active = 0                 # tasks currently mid-execution
        self._last_reap = 0.0
        self._startup_reap_done = False  # crash-recovery sweep runs once at boot
        self.stats = {"completed": 0, "failed": 0, "leased": 0, "worker_restarts": 0}

    # ------------------------------------------------------------------ #
    # loop construction
    # ------------------------------------------------------------------ #
    def _apply_autonomous_safety(self, loop_obj: Any) -> Any:
        """Apply a safe unattended default before running queued work.

        Interactive sessions may opt into ``no_sandbox`` explicitly, but an
        unattended 24/7 worker must not inherit that unsafe legacy default.
        A deliberate environment opt-out keeps deployments that already run
        inside a hardened container compatible.
        """
        if os.environ.get("NEXUS_ALLOW_UNSANDBOXED_AUTONOMOUS", "false").lower() == "true":
            return loop_obj
        setter = getattr(loop_obj, "_set_sandbox_tier", None)
        if callable(setter):
            try:
                setter("normal")
            except Exception as exc:
                log.warning("could not enforce normal sandbox for autonomous task: %s", exc)
        return loop_obj

    def _build_loop(self, session_id: str = "default"):
        """Return a NexusLoop instance, preferring the kernel's own."""
        loop_obj = getattr(self.kernel, "loop", None)
        if loop_obj is not None and hasattr(loop_obj, "stream_run"):
            return self._apply_autonomous_safety(loop_obj)
        from orchestrators import NexusLoop  # V5 loop
        return self._apply_autonomous_safety(
            NexusLoop(root_dir=self.root, session_id=session_id or "default")
        )

    # ------------------------------------------------------------------ #
    # single task execution
    # ------------------------------------------------------------------ #
    async def run_task(self, task: Dict[str, Any]) -> str:
        payload = task.get("payload") or {}
        task_desc = payload.get("task_desc") or ""
        if not task_desc:
            raise ValueError("task payload has no 'task_desc'")

        kwargs: Dict[str, Any] = {}
        vm = payload.get("voice_mode")
        kwargs["voice_mode"] = bool(vm) and vm != "text"
        if payload.get("provider"):
            kwargs["provider"] = payload["provider"]
        if payload.get("model"):
            kwargs["model"] = payload["model"]
        if payload.get("max_tokens"):
            kwargs["max_tokens"] = payload["max_tokens"]

        meta = payload.get("meta") or {}
        queue_namespace = hashlib.sha1(
            os.path.abspath(str(getattr(self.queue, "db_path", ""))).encode()
        ).hexdigest()[:12]
        idempotency_key = str(
            meta.get("idempotency_key") or
            f"queue:{queue_namespace}:{task.get('id')}"
        )[:240]
        # A retried unattended task should continue from the durable session
        # and checkpoint context when possible.  The opt-out is explicit
        # because some callers intentionally require a clean replay.
        if int(task.get("attempts") or 0) > 1 and meta.get("resume_on_retry", True) is not False:
            task_desc = build_resume_prompt(
                str(task_desc),
                meta.get(
                    "resume_context",
                    "The previous execution attempt ended before a terminal result. "
                    "Inspect the saved session/checkpoint and continue the unfinished work.",
                ),
            )
        if meta.get("control_task_id"):
            kwargs["task_id"] = str(meta["control_task_id"])
        if meta.get("control_run_id"):
            kwargs["turn_id"] = str(meta["control_run_id"])
        session_id = str(meta.get("session_id") or task.get("session_id") or "default")
        loop_obj = self._build_loop(session_id=session_id)
        try:
            signature = inspect.signature(loop_obj.stream_run)
            supports_key = "idempotency_key" in signature.parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
        except (TypeError, ValueError):
            supports_key = False
        if supports_key:
            kwargs["idempotency_key"] = idempotency_key

        events = 0
        last_text = ""
        done_data: Dict[str, Any] = {}
        terminal_event_seen = False
        # NexusLoopV5 exposes one canonical streaming entrypoint.  Keep the
        # queue driver on that path so queued work has the same tool registry,
        # memory, events, and truthful success contract as GUI chat.
        async for event in loop_obj.stream_run(task_desc, **kwargs):
            events += 1
            if isinstance(event, dict):
                if event.get("type") == "done":
                    terminal_event_seen = True
                candidates = [event]
                if isinstance(event.get("data"), dict):
                    candidates.append(event["data"])
                for key in ("summary", "content", "text", "message", "title", "response"):
                    val = next(
                        (candidate.get(key) for candidate in candidates
                         if isinstance(candidate.get(key), str) and candidate.get(key).strip()),
                        None,
                    )
                    if isinstance(val, str) and val.strip():
                        last_text = val
                        break
                if event.get("type") == "done" and isinstance(event.get("data"), dict):
                    done_data = event["data"]
        if not terminal_event_seen:
            raise RuntimeError(
                "agent stream ended without a terminal result; task remains retryable"
            )
        if done_data and not bool(done_data.get("success")):
            detail = str(done_data.get("error") or done_data.get("response") or "task did not complete successfully")
            raise RuntimeError(detail)
        summary = last_text or f"completed with {events} events"
        return summary[:MAX_SUMMARY_CHARS]

    def _link_queue_task(self, task: Dict[str, Any], worker_id: str = "queue-worker") -> Dict[str, Any]:
        """Give a legacy queue record stable workflow identity before dispatch."""
        payload = task.get("payload") or {}
        meta = payload.setdefault("meta", {})
        if not isinstance(meta, dict):
            meta = payload["meta"] = {}
        if meta.get("control_task_id") and meta.get("control_run_id"):
            return meta
        queue_namespace = hashlib.sha1(os.path.abspath(str(getattr(self.queue, "db_path", ""))).encode()).hexdigest()[:12]
        legacy_source_id = f"{queue_namespace}:{task.get('id')}"
        prior = self.control_store.legacy_link(source_type="queue", source_id=legacy_source_id)
        if prior.get("task_id") and prior.get("step_id"):
            get_run = getattr(self.control_store, "get_run", None)
            previous_run = (
                get_run(str(prior.get("run_id") or ""))
                if callable(get_run) else {}
            )
            if previous_run.get("status") == "succeeded":
                # The canonical side effect completed before a process crash,
                # but the legacy queue acknowledgement may not have committed.
                # Mark this lease as reconciliation-only so restart never
                # executes the external work a second time.
                meta.update({
                    "control_task_id": prior.get("task_id"),
                    "control_plan_id": prior.get("plan_id"),
                    "control_step_id": prior.get("step_id"),
                    "control_run_id": previous_run.get("run_id"),
                    "control_run_status": "succeeded",
                })
                return meta
            meta.update({"control_task_id": prior.get("task_id"), "control_plan_id": prior.get("plan_id"),
                         "control_step_id": prior.get("step_id")})
            run = self.control_store.start_run(
                step_id=str(prior["step_id"]), worker_id=worker_id,
                process_id=str(os.getpid()), lease_seconds=self.lease_timeout,
                idempotency_key=f"queue:{queue_namespace}:{task.get('id')}:{task.get('attempts', 0)}",
            )
            meta["control_run_id"] = run["run_id"]
            meta["control_lease_token"] = run["lease_token"]
            self.control_store.link_legacy_record(
                source_type="queue", source_id=legacy_source_id,
                task_id=str(prior["task_id"]), plan_id=str(prior.get("plan_id") or ""),
                step_id=str(prior["step_id"]), run_id=str(run["run_id"]),
            )
            return meta
        goal = str(payload.get("task_desc") or "").strip()
        session_id = str(meta.get("session_id") or "default")
        durable_task = self.control_store.create_task(goal=goal, session_id=session_id, workspace_id=self.root)
        plan = self.control_store.create_plan(
            task_id=durable_task["task_id"], goal=goal, source="legacy_queue",
            steps=[{
                "step_id": f"queue_{queue_namespace}_{task.get('id')}", "title": goal[:300],
                "execution_kind": "queued", "workspace_scope": self.root,
            }],
        )
        meta.update({
            "control_task_id": durable_task["task_id"], "control_plan_id": plan["plan_id"],
            "control_step_id": f"queue_{queue_namespace}_{task.get('id')}",
        })
        run = self.control_store.start_run(
            step_id=meta["control_step_id"], worker_id=worker_id,
            process_id=str(os.getpid()), lease_seconds=self.lease_timeout,
            idempotency_key=f"queue:{queue_namespace}:{task.get('id')}:{task.get('attempts', 0)}",
        )
        meta["control_run_id"] = run["run_id"]
        meta["control_lease_token"] = run["lease_token"]
        self.control_store.link_legacy_record(
            source_type="queue", source_id=legacy_source_id, task_id=durable_task["task_id"],
            plan_id=plan["plan_id"], step_id=meta["control_step_id"], run_id=run["run_id"],
        )
        return meta

    # ------------------------------------------------------------------ #
    # lease renewal heartbeat
    # ------------------------------------------------------------------ #
    async def _run_with_heartbeat(
        self,
        task: Dict[str, Any],
        task_id: int,
        lease_token: Optional[str],
        leased_at: float,
    ) -> str:
        """Run ``run_task`` while heart-beating its lease.

        Once ``lease_timeout / 2`` has elapsed the worker renews the lease via
        ``queue.ack_lease(task_id, lease_token, timeout_sec=lease_timeout)`` on
        a small interval, pushing ``leased_until`` forward so a long-running
        task is never reaped by the expired-lease sweep mid-execution. If the
        token ever stops matching (lease lost to a reaper or another worker)
        we log and let the token-checked ``complete``/``fail`` guards discard
        the result. ``run_task`` always runs to completion — the heartbeat
        never cancels the orchestrator mid-stream.
        """
        # Never renew toward an immediate-death lease even if lease_timeout was
        # truncated below 1s (int() of a sub-second value truncates to 0).
        ttl = float(max(1, int(self.lease_timeout)))
        check_every = max(0.25, min(ttl / 4.0, 60.0))
        first_renew_at = leased_at + ttl / 2.0
        lease_lost = asyncio.Event()

        async def _heed() -> None:
            while True:
                await asyncio.sleep(check_every)
                if time.time() < first_renew_at:
                    continue
                try:
                    queue_ok = self.queue.ack_lease(
                        task_id, lease_token, timeout_sec=ttl
                    )
                    meta = (task.get("payload") or {}).get("meta") or {}
                    control_ok = True
                    if meta.get("control_run_id") and meta.get("control_lease_token"):
                        control_ok = self.control_store.renew_run(
                            run_id=str(meta["control_run_id"]),
                            lease_token=str(meta["control_lease_token"]),
                            lease_seconds=ttl,
                        )
                    if not queue_ok or not control_ok:
                        log.warning(
                            "lease for task %s no longer owned by this worker; "
                            "stemmed result will be discarded",
                            task_id,
                        )
                        lease_lost.set()
                        return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # heartbeat is best-effort
                    log.debug("lease renewal hiccup for task %s: %s", task_id, exc)

        async def _execute_with_deadline() -> str:
            work = self.run_task(task)
            if self.execution_timeout > 0:
                return await asyncio.wait_for(work, timeout=self.execution_timeout)
            return await work

        main = asyncio.ensure_future(_execute_with_deadline())
        heed = asyncio.ensure_future(_heed())
        try:
            result = await main
            if lease_lost.is_set():
                raise RuntimeError("queue or canonical lease lost before completion; result discarded")
            return result
        finally:
            heed.cancel()
            await asyncio.gather(heed, return_exceptions=True)
            if not main.done():
                main.cancel()
                await asyncio.gather(main, return_exceptions=True)

    # ------------------------------------------------------------------ #
    # worker
    # ------------------------------------------------------------------ #
    async def _startup_reap(self) -> None:
        """Requeue leases orphaned by a crash before the loop spins up.

        Run once per driver (first worker to start wins). Tasks leased by a
        process that died are re-enqueued immediately instead of waiting up to
        REAP_INTERVAL (60s) for the periodic sweep, so 24/7 recovery is fast.
        """
        if self._startup_reap_done:
            return
        try:
            n = self.queue.requeue_expired_leases()
            try:
                self.control_store.reap_expired_runs()
            except Exception as exc:
                log.warning("startup canonical lease sweep failed: %s", exc)
            self._startup_reap_done = True
            self._last_reap = time.time()  # don't double-reap on the next tick
            if n:
                log.info("startup sweep requeued %s expired lease(s)", n)
        except Exception as exc:
            log.warning("startup lease sweep failed: %s", exc)

    async def _worker(self, worker_id: str) -> None:
        log.info("queue worker %s started", worker_id)
        try:
            await self._startup_reap()
            while not self._stopping:
                await self._maybe_reap()
                self._publish_runtime_status()

                try:
                    task = self.queue.lease(
                        timeout_sec=self.lease_timeout, worker_id=worker_id
                    )
                except Exception as exc:  # transient sqlite issue -> back off
                    log.warning("lease failed on %s: %s", worker_id, exc)
                    task = None

                if not task:
                    # Queue empty: give active long-horizon missions a chance to
                    # enqueue their next milestone so the system keeps producing
                    # work on its own rather than idling forever.
                    try:
                        if self.mission_runner is not None:
                            self.mission_runner.advance()
                    except Exception as exc:
                        log.warning("mission advance failed: %s", exc)
                    await asyncio.sleep(self.idle_sleep)
                    continue

                task_id = task.get("id")
                lease_token = task.get("lease_token")
                self.stats["leased"] += 1
                self._active += 1
                try:
                    self._update_cron_run(task, "running")
                    control_meta = self._link_queue_task(task, worker_id=worker_id)
                    leased_at = time.time()
                    canonical_already_completed = control_meta.get("control_run_status") == "succeeded"
                    if canonical_already_completed:
                        summary = "Recovered canonical completion; queue acknowledgement replayed."
                    else:
                        summary = await self._run_with_heartbeat(
                            task, task_id=task_id, lease_token=lease_token,
                            leased_at=leased_at,
                        )
                    completed = self.queue.complete(task_id, summary, lease_token=lease_token)
                    if not completed:
                        raise RuntimeError("queue lease lost before completion; result discarded")
                    self._update_cron_run(task, "completed")
                    self.stats["completed"] += 1
                    if not canonical_already_completed:
                        self.control_store.complete_run(
                            run_id=str(control_meta.get("control_run_id") or ""),
                            lease_token=str(control_meta.get("control_lease_token") or ""),
                            evidence=[{"kind": "queue_result", "uri": f"queue:{task_id}", "summary": summary}],
                        )
                    log.info("task %s completed by %s", task_id, worker_id)
                    # Preserve the worker's returned evidence for mission
                    # acceptance verification; queue completion alone is not
                    # proof that the milestone's acceptance contract passed.
                    self._reconcile_mission(task, "success", detail=summary)
                except asyncio.CancelledError:
                    # A cancelled worker may already have caused an external
                    # side effect. Never silently replay it as a retry; leave
                    # an explicit durable cancellation for operator recovery.
                    try:
                        self.queue.cancel(
                            task_id, "driver cancelled before completion",
                            lease_token=lease_token,
                        )
                        self._update_cron_run(task, "cancelled", "driver cancelled before completion")
                    except Exception:
                        pass
                    raise
                except Exception as exc:
                    self.stats["failed"] += 1
                    log.exception("task %s failed: %s", task_id, exc)
                    self._reconcile_mission(task, "failure", detail=str(exc))
                    try:
                        meta = (task.get("payload") or {}).get("meta") or {}
                        if meta.get("control_run_id"):
                            self.control_store.fail_run(run_id=str(meta["control_run_id"]), lease_token=str(meta.get("control_lease_token") or ""), failure_code="queue_execution_failed", failure_detail=str(exc))
                    except Exception:
                        log.debug("could not close canonical failed run", exc_info=True)
                    try:
                        failed_recorded = self.queue.fail(
                            task_id, str(exc), requeue_after=self.requeue_after,
                            lease_token=lease_token,
                        )
                        if failed_recorded:
                            attempts = int(task.get("attempts") or 0)
                            maximum = int(task.get("max_attempts") or 0)
                            self._update_cron_run(
                                task, "retrying" if attempts < maximum else "failed", str(exc)
                            )
                    except Exception:
                        log.exception("could not record failure for %s", task_id)
                finally:
                    self._active -= 1
        except asyncio.CancelledError:
            log.info("queue worker %s cancelled", worker_id)
            raise
        finally:
            log.info("queue worker %s stopped", worker_id)

    async def _supervised_worker(self, worker_id: str) -> None:
        """Keep a worker alive after an unexpected worker-level exception.

        Task-level failures are already recorded and requeued by ``_worker``.
        This outer guard handles failures in the lease/database/runtime glue
        itself, which previously caused ``asyncio.gather`` in ``run()`` to
        return and silently ended the supposedly 24/7 driver.  Shutdown and
        cancellation remain terminal; genuine crashes use bounded backoff so a
        broken dependency cannot create a hot restart loop.
        """
        backoff = 1.0
        while not self._stopping:
            try:
                await self._worker(worker_id)
                if self._stopping:
                    return
                log.error("queue worker %s exited unexpectedly; restarting", worker_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats["worker_restarts"] += 1
                log.exception("queue worker %s crashed; restarting in %.1fs", worker_id, backoff)
            if self._stopping:
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)
            # A successful pass through the worker should not retain a stale
            # crash-loop delay.
            if not self._stopping:
                backoff = min(backoff, 5.0)

    async def _maybe_reap(self) -> None:
        now = time.time()
        if now - self._last_reap < REAP_INTERVAL:
            return
        self._last_reap = now
        try:
            n = self.queue.requeue_expired_leases()
            canonical = self.control_store.reap_expired_runs()
            if n:
                log.info("requeued %s expired lease(s)", n)
            if canonical:
                log.info("reaped %s expired canonical run(s)", canonical)
        except Exception as exc:
            log.warning("requeue_expired_leases failed: %s", exc)
        self._publish_runtime_status()

    def _publish_runtime_status(self, *, state: str = "running", error: str = "", force: bool = False) -> None:
        try:
            self.runtime_status.publish(state, stats=self.stats, error=error, force=force)
        except Exception as exc:
            log.debug("could not publish queue runtime status: %s", exc)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        """Run all workers until cancelled / stopped. This never returns
        on its own — it is the 24/7 loop."""
        self._stopping = False
        self._publish_runtime_status(force=True)
        self._tasks = [
            asyncio.ensure_future(self._supervised_worker(f"w{i + 1}"))
            for i in range(self.workers)
        ]
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            await self.shutdown()
            raise

    # convenience alias
    async def start(self) -> None:
        await self.run()

    def _reconcile_mission(self, task: Dict[str, Any], outcome: str, detail: str = "") -> None:
        """Feed a task outcome back into its mission ledger (best-effort)."""
        if self.mission_runner is None:
            return
        try:
            self.mission_runner.reconcile(task, outcome, detail=detail)
        except Exception as exc:
            log.warning("mission reconcile failed: %s", exc)

    def _update_cron_run(self, task: Dict[str, Any], status: str, error: str = "") -> None:
        """Project queue ownership/outcome onto a linked durable cron run."""
        meta = (task.get("payload") or {}).get("meta") or {}
        run_id = str(meta.get("cron_run_id") or "")
        updater = getattr(self.queue, "update_cron_run", None)
        if not run_id or not callable(updater):
            return
        try:
            updater(run_id, status, error=error)
        except Exception:
            log.debug("could not update cron run %s", run_id, exc_info=True)

    def stop(self) -> None:
        """Ask workers to finish the current task and exit."""
        self._stopping = True
        self._publish_runtime_status(state="stopping", force=True)

    async def shutdown(self, drain_timeout: float = 300.0) -> None:
        """Stop accepting new work and wait for in-flight tasks to drain."""
        self._stopping = True
        deadline = time.time() + drain_timeout
        while self._active > 0 and time.time() < deadline:
            await asyncio.sleep(0.5)
        for t in self._tasks:
            if not t.done():
                t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        try:
            self.runtime_status.stopped(stats=self.stats)
        except Exception as exc:
            log.debug("could not publish queue stopped status: %s", exc)


# ---------------------------------------------------------------------- #
# enqueue helpers
# ---------------------------------------------------------------------- #
def get_queue(root: Optional[str] = None, db_path: Optional[str] = None) -> TaskQueue:
    return TaskQueue(db_path=db_path, root=root or _resolve_root(None))


def enqueue_task(task_desc: str, **meta: Any) -> int:
    """Enqueue a task for the 24/7 driver. Returns the new task id.

    Recognised kwargs: voice_mode, provider, model, priority, max_attempts,
    root, db_path. Anything else is stored under payload['meta'].
    """
    root = meta.pop("root", None)
    db_path = meta.pop("db_path", None)
    q = get_queue(root=root, db_path=db_path)
    return q.enqueue(task_desc, **meta)


# ---------------------------------------------------------------------- #
# embedding hook
# ---------------------------------------------------------------------- #
def start_queue_driver(kernel: Any = None, workers: int = 1, **kw) -> asyncio.Task:
    """Start the driver as a background asyncio task on the running loop."""
    driver = QueueDriver(kernel=kernel, workers=workers, **kw)
    task = asyncio.ensure_future(driver.run())
    task._nexus_driver = driver  # type: ignore[attr-defined]
    return task


async def run_forever(kernel: Any = None, workers: int = 1, **kw) -> None:
    """Blocking async entrypoint with SIGINT/SIGTERM graceful shutdown.

    When ``missions=True`` (or ``NEXUS_MISSIONS=1``), a long-horizon
    ``MissionRunner`` is attached so the driver re-hydrates active missions on
    startup, advances them whenever the queue idles, and reconciles each task
    outcome back into the mission ledger — one epic goal keeps producing work
    24/7, survives restarts, and never abandons its goal.
    """
    missions_enabled = bool(
        kw.pop("missions", False) or os.environ.get("NEXUS_MISSIONS", "") not in ("", "0")
    )
    boot_root = kw.pop("root", None)  # QueueDriver resolves root itself
    mission_runner = None
    if missions_enabled:
        try:
            from .mission import MissionRunner
            mission_runner = MissionRunner(root=boot_root)
            requeued = mission_runner.hydrate_active()
            if requeued:
                log.info("mission recovery requeued %s pending milestone(s)", requeued)
        except Exception as exc:
            log.warning("mission runner unavailable (%s); driving queue only", exc)

    # Keep the mission ledger and queue on the same explicit root.  Previously
    # ``root`` was consumed while constructing MissionRunner and the driver
    # silently fell back to the process root, so custom-root deployments could
    # enqueue milestones into a database the worker never read.
    driver = QueueDriver(
        kernel=kernel,
        workers=workers,
        mission_runner=mission_runner,
        root=boot_root,
        **kw,
    )
    loop = asyncio.get_event_loop()
    stop_evt = asyncio.Event()

    def _request_stop(*_a):
        if not stop_evt.is_set():
            log.info("shutdown signal received; draining...")
            driver.stop()
            stop_evt.set()

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows / non-main thread: fall back to plain signal module
            try:
                signal.signal(sig, _request_stop)
            except Exception:
                pass

    run_task = asyncio.ensure_future(driver.run())
    try:
        await run_task
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        _request_stop()
    finally:
        await driver.shutdown()


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #
def _main(argv: Optional[List[str]] = None) -> int:
    import argparse

    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="python -m queue.driver",
        description="NEXUS 24/7 queue driver (and quick enqueue).",
    )
    p.add_argument("--workers", type=int, default=1, help="concurrent workers")
    p.add_argument("--idle-sleep", type=float, default=DEFAULT_IDLE_SLEEP)
    p.add_argument("--db", type=str, default=None, help="explicit sqlite db path")
    p.add_argument("--enqueue", type=str, default=None, metavar="TASK",
                   help="enqueue TASK and exit (do not run the driver)")
    p.add_argument("--status", action="store_true", help="print queue counts and exit")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("NEXUS_QUEUE_LOGLEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.enqueue:
        tid = enqueue_task(args.enqueue, db_path=args.db)
        print(f"enqueued task {tid}: {args.enqueue}")
        return 0

    if args.status:
        q = get_queue(db_path=args.db)
        print(q.list_states())
        return 0

    kernel = None
    try:
        from kernel import get_nexus_kernel
        kernel = get_nexus_kernel()
    except Exception as exc:  # driver still works standalone
        log.warning("kernel unavailable (%s); using standalone NexusLoop", exc)

    try:
        asyncio.run(
            run_forever(
                kernel,
                workers=args.workers,
                idle_sleep=args.idle_sleep,
                db_path=args.db,
            )
        )
    except KeyboardInterrupt:
        print("\nqueue driver stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
