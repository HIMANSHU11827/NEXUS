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
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from .store import TaskQueue
from nexus.control_store import ControlStore

log = logging.getLogger("nexus.queue.driver")

DEFAULT_IDLE_SLEEP = 2.0            # seconds between empty-lease polls
DEFAULT_LEASE_TIMEOUT = 3600        # seconds a leased task may run
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
        requeue_after: float = DEFAULT_REQUEUE_AFTER,
        db_path: Optional[str] = None,
        mission_runner: Any = None,
        control_store: Optional[ControlStore] = None,
    ) -> None:
        self.kernel = kernel
        self.root = _resolve_root(kernel)
        self.queue = queue or TaskQueue(db_path=db_path, root=self.root)
        self.control_store = control_store or ControlStore(self.root)
        self.workers = max(1, int(workers))
        self.idle_sleep = float(idle_sleep)
        self.lease_timeout = int(lease_timeout)
        self.requeue_after = float(requeue_after)

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
        self.stats = {"completed": 0, "failed": 0, "leased": 0}

    # ------------------------------------------------------------------ #
    # loop construction
    # ------------------------------------------------------------------ #
    def _build_loop(self, session_id: str = "default"):
        """Return a NexusLoop instance, preferring the kernel's own."""
        loop_obj = getattr(self.kernel, "loop", None)
        if loop_obj is not None and hasattr(loop_obj, "stream_run"):
            return loop_obj
        from orchestrators import NexusLoop  # V5 loop
        return NexusLoop(root_dir=self.root, session_id=session_id or "default")

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
        if meta.get("control_task_id"):
            kwargs["task_id"] = str(meta["control_task_id"])
        if meta.get("control_run_id"):
            kwargs["turn_id"] = str(meta["control_run_id"])
        session_id = str(meta.get("session_id") or task.get("session_id") or "default")
        loop_obj = self._build_loop(session_id=session_id)

        events = 0
        last_text = ""
        done_data: Dict[str, Any] = {}
        # NexusLoopV5 exposes one canonical streaming entrypoint.  Keep the
        # queue driver on that path so queued work has the same tool registry,
        # memory, events, and truthful success contract as GUI chat.
        async for event in loop_obj.stream_run(task_desc, **kwargs):
            events += 1
            if isinstance(event, dict):
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
        goal = str(payload.get("task_desc") or "").strip()
        session_id = str(meta.get("session_id") or "default")
        durable_task = self.control_store.create_task(goal=goal, session_id=session_id, workspace_id=self.root)
        plan = self.control_store.create_plan(
            task_id=durable_task["task_id"], goal=goal, source="legacy_queue",
            steps=[{
                "step_id": f"queue_{task.get('id')}", "title": goal[:300],
                "execution_kind": "queued", "workspace_scope": self.root,
            }],
        )
        meta.update({
            "control_task_id": durable_task["task_id"], "control_plan_id": plan["plan_id"],
            "control_step_id": f"queue_{task.get('id')}",
        })
        run = self.control_store.start_run(
            step_id=meta["control_step_id"], worker_id=worker_id,
            process_id=str(os.getpid()), lease_seconds=self.lease_timeout,
            idempotency_key=f"queue:{task.get('id')}:{task.get('attempts', 0)}",
        )
        meta["control_run_id"] = run["run_id"]
        meta["control_lease_token"] = run["lease_token"]
        self.control_store.link_legacy_record(
            source_type="queue", source_id=str(task.get("id")), task_id=durable_task["task_id"],
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

        async def _heed() -> None:
            while True:
                await asyncio.sleep(check_every)
                if time.time() < first_renew_at:
                    continue
                try:
                    if not self.queue.ack_lease(
                        task_id, lease_token, timeout_sec=ttl
                    ):
                        log.warning(
                            "lease for task %s no longer owned by this worker; "
                            "stemmed result will be discarded",
                            task_id,
                        )
                        return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # heartbeat is best-effort
                    log.debug("lease renewal hiccup for task %s: %s", task_id, exc)

        main = asyncio.ensure_future(self.run_task(task))
        heed = asyncio.ensure_future(_heed())
        try:
            return await main
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
                    control_meta = self._link_queue_task(task, worker_id=worker_id)
                    leased_at = time.time()
                    summary = await self._run_with_heartbeat(
                        task, task_id=task_id, lease_token=lease_token,
                        leased_at=leased_at,
                    )
                    completed = self.queue.complete(task_id, summary, lease_token=lease_token)
                    if not completed:
                        raise RuntimeError("queue lease lost before completion; result discarded")
                    self.stats["completed"] += 1
                    self.control_store.complete_run(
                        run_id=str(control_meta.get("control_run_id") or ""),
                        lease_token=str(control_meta.get("control_lease_token") or ""),
                        evidence=[{"kind": "queue_result", "uri": f"queue:{task_id}", "summary": summary}],
                    )
                    log.info("task %s completed by %s", task_id, worker_id)
                    self._reconcile_mission(task, "success")
                except asyncio.CancelledError:
                    # graceful shutdown mid-task: release the lease for retry
                    try:
                        self.queue.fail(
                            task_id, "driver shutdown", requeue_after=0,
                            lease_token=lease_token,
                        )
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
                        self.queue.fail(
                            task_id, str(exc), requeue_after=self.requeue_after,
                            lease_token=lease_token,
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

    async def _maybe_reap(self) -> None:
        now = time.time()
        if now - self._last_reap < REAP_INTERVAL:
            return
        self._last_reap = now
        try:
            n = self.queue.requeue_expired_leases()
            if n:
                log.info("requeued %s expired lease(s)", n)
        except Exception as exc:
            log.warning("requeue_expired_leases failed: %s", exc)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        """Run all workers until cancelled / stopped. This never returns
        on its own — it is the 24/7 loop."""
        self._stopping = False
        self._tasks = [
            asyncio.ensure_future(self._worker(f"w{i + 1}"))
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

    def stop(self) -> None:
        """Ask workers to finish the current task and exit."""
        self._stopping = True

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

    driver = QueueDriver(kernel=kernel, workers=workers, mission_runner=mission_runner, **kw)
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
