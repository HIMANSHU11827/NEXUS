"""Small durable one-shot scheduler used by the V5 cron mixin.

The scheduler deliberately remains a bridge, not a second task engine: it
invokes the supplied runner, persists ownership/attempt state, and lets the
durable queue handle long-running work. A process restart reloads unfinished
entries and retries them with bounded backoff.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class NexusTaskScheduler:
    """Persisted one-shot scheduler with bounded retry and restart recovery."""

    def __init__(
        self,
        loop_runner: Callable[[str], Any],
        state_path: Optional[str] = None,
        poll_seconds: float = 1.0,
    ):
        self.loop_runner = loop_runner
        configured = state_path or os.environ.get("NEXUS_SCHEDULER_STATE_PATH", "")
        self.state_path = os.path.abspath(configured) if configured else ""
        self.poll_seconds = max(0.1, float(poll_seconds or 1.0))
        self.scheduled_tasks: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._load()
        self._thread = threading.Thread(target=self._run_scheduler, daemon=True, name="nexus-scheduler")
        self._thread.start()

    def _load(self) -> None:
        if not self.state_path:
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
            if isinstance(tasks, list):
                recovered_at = time.time()
                recovered = []
                for item in tasks:
                    if not isinstance(item, dict) or item.get("executed"):
                        continue
                    task = dict(item)
                    # A process can die after persisting running=true but
                    # before the runner reports success/failure. Never let
                    # that orphaned marker strand work permanently.
                    if task.get("running"):
                        task["running"] = False
                        task["status"] = "retrying"
                        task["last_error"] = "recovered after scheduler process restart"
                        task["run_at"] = min(float(task.get("run_at", recovered_at)), recovered_at)
                    recovered.append(task)
                with self._lock:
                    self.scheduled_tasks = recovered
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            logger.warning("scheduler state is unreadable; starting with no pending jobs", exc_info=True)

    def _persist(self) -> None:
        if not self.state_path:
            return
        try:
            state_dir = os.path.dirname(self.state_path) or "."
            os.makedirs(state_dir, exist_ok=True)
            with self._lock:
                payload = {"version": 1, "tasks": [dict(item) for item in self.scheduled_tasks if not item.get("executed")]}
            fd, temporary = tempfile.mkstemp(prefix=".scheduler-", suffix=".tmp", dir=state_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.state_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError:
            logger.warning("could not persist scheduler state", exc_info=True)

    def _run_scheduler(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            with self._lock:
                due = [task for task in self.scheduled_tasks if float(task.get("run_at", 0)) <= now and not task.get("executed") and not task.get("running")]
                for task in due:
                    task["running"] = True
                    task["attempts"] = int(task.get("attempts", 0)) + 1
                if due:
                    self._persist()

            for task in due:
                name = str(task.get("name") or task.get("task_id") or "scheduled-task")
                logger.info("[SCHEDULER]: executing task '%s' (attempt %s)", name, task.get("attempts", 1))
                try:
                    self.loop_runner(str(task.get("task_desc") or ""))
                except Exception as exc:
                    max_attempts = max(1, int(task.get("max_attempts", 3) or 3))
                    attempts = int(task.get("attempts", 1))
                    with self._lock:
                        task["running"] = False
                        task["last_error"] = str(exc)[:1000]
                        if attempts >= max_attempts:
                            task["executed"] = True
                            task["status"] = "failed"
                        else:
                            task["run_at"] = time.time() + float(task.get("retry_delay_seconds", 30) or 30)
                            task["status"] = "retrying"
                        self._persist()
                    logger.error("[SCHEDULER]: task '%s' failed: %s", name, exc)
                else:
                    with self._lock:
                        task["running"] = False
                        task["executed"] = True
                        task["status"] = "success"
                        task["completed_at"] = datetime.now().isoformat()
                        self.scheduled_tasks = [item for item in self.scheduled_tasks if not item.get("executed")]
                        self._persist()

            self._stop_event.wait(self.poll_seconds)

    def schedule(
        self,
        name: str,
        task_desc: str,
        delay_seconds: int,
        *,
        max_attempts: int = 3,
        retry_delay_seconds: float = 30.0,
    ) -> str:
        run_at = time.time() + max(0, int(delay_seconds))
        task = {
            "task_id": f"sched_{uuid.uuid4().hex[:12]}",
            "name": str(name),
            "task_desc": str(task_desc),
            "run_at": run_at,
            "executed": False,
            "running": False,
            "status": "scheduled",
            "attempts": 0,
            "max_attempts": max(1, int(max_attempts or 1)),
            "retry_delay_seconds": max(0.1, float(retry_delay_seconds or 30.0)),
            "scheduled_time": datetime.now().isoformat(),
        }
        with self._lock:
            self.scheduled_tasks.append(task)
            self._persist()
        return f"✅ [SCHEDULER]: Task '{name}' scheduled for execution in {delay_seconds} seconds."

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(task) for task in self.scheduled_tasks]

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    close = stop
