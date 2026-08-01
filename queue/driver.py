"""Always-on 24/7 task driver for NEXUS.

Leases tasks from the durable SQLite queue (``queue.store.TaskQueue``) and runs
each one through ``orchestrators.loop.NexusLoop._full_loop``, draining every
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
    ) -> None:
        self.kernel = kernel
        self.root = _resolve_root(kernel)
        self.queue = queue or TaskQueue(db_path=db_path, root=self.root)
        self.workers = max(1, int(workers))
        self.idle_sleep = float(idle_sleep)
        self.lease_timeout = int(lease_timeout)
        self.requeue_after = float(requeue_after)

        self._stopping = False
        self._tasks: List[asyncio.Task] = []
        self._active = 0                 # tasks currently mid-execution
        self._last_reap = 0.0
        self.stats = {"completed": 0, "failed": 0, "leased": 0}

    # ------------------------------------------------------------------ #
    # loop construction
    # ------------------------------------------------------------------ #
    def _build_loop(self):
        """Return a NexusLoop instance, preferring the kernel's own."""
        loop_obj = getattr(self.kernel, "loop", None)
        if loop_obj is not None and hasattr(loop_obj, "_full_loop"):
            return loop_obj
        from orchestrators.loop import NexusLoop  # local import: heavy module
        return NexusLoop(root_dir=self.root)

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

        loop_obj = self._build_loop()

        events = 0
        last_text = ""
        async for event in loop_obj._full_loop(task_desc, **kwargs):
            events += 1
            if isinstance(event, dict):
                for key in ("summary", "content", "text", "message", "title"):
                    val = event.get(key)
                    if isinstance(val, str) and val.strip():
                        last_text = val
                        break
        summary = last_text or f"completed with {events} events"
        return summary[:MAX_SUMMARY_CHARS]

    # ------------------------------------------------------------------ #
    # worker
    # ------------------------------------------------------------------ #
    async def _worker(self, worker_id: str) -> None:
        log.info("queue worker %s started", worker_id)
        try:
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
                    await asyncio.sleep(self.idle_sleep)
                    continue

                task_id = task.get("id")
                self.stats["leased"] += 1
                self._active += 1
                try:
                    summary = await self.run_task(task)
                    self.queue.complete(task_id, summary)
                    self.stats["completed"] += 1
                    log.info("task %s completed by %s", task_id, worker_id)
                except asyncio.CancelledError:
                    # graceful shutdown mid-task: release the lease for retry
                    try:
                        self.queue.fail(
                            task_id, "driver shutdown", requeue_after=0
                        )
                    except Exception:
                        pass
                    raise
                except Exception as exc:
                    self.stats["failed"] += 1
                    log.exception("task %s failed: %s", task_id, exc)
                    try:
                        self.queue.fail(
                            task_id, str(exc), requeue_after=self.requeue_after
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
    """Blocking async entrypoint with SIGINT/SIGTERM graceful shutdown."""
    driver = QueueDriver(kernel=kernel, workers=workers, **kw)
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
