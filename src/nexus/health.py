"""Health heartbeat monitoring for 24/7 autonomous operation.

Provides a persistent health status file that external monitoring tools
(e.g., systemd watchdog, Docker HEALTHCHECK, cron health probes) can check
to verify the agent is alive and making progress.

Health status is written to .nexus/health.json and includes:
- alive: whether the process is responsive
- last_heartbeat: timestamp of last heartbeat
- tasks_completed: count of completed tasks
- tasks_failed: count of failed tasks
- uptime_seconds: how long the driver has been running
- current_task: id of the task being processed (if any)
- provider_health: status of each provider
- error_streak: consecutive errors
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_HEARTBEAT_INTERVAL = 30.0  # seconds
_HEALTH_FILE = "health.json"


class HealthMonitor:
    """Writes periodic health status for external monitoring."""

    def __init__(
        self,
        root_dir: str,
        *,
        heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL,
    ):
        self.root_dir = root_dir
        self._interval = heartbeat_interval
        self._last_write = 0.0
        self._started_at = time.time()
        self._stats = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_leased": 0,
            "worker_restarts": 0,
            "error_streak": 0,
        }
        self._current_task: Optional[str] = None
        self._provider_health: Dict[str, str] = {}

    def _health_path(self) -> str:
        base = os.path.join(self.root_dir, ".nexus")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, _HEALTH_FILE)

    def heartbeat(self, *, force: bool = False) -> None:
        """Write a health heartbeat if enough time has passed."""
        now = time.time()
        if not force and (now - self._last_write) < self._interval:
            return
        self._last_write = now

        status = {
            "alive": True,
            "last_heartbeat": now,
            "uptime_seconds": round(now - self._started_at, 1),
            **self._stats,
            "current_task": self._current_task,
            "provider_health": dict(self._provider_health),
        }

        try:
            path = self._health_path()
            fd, tmp = None, None
            import tempfile
            fd, tmp = tempfile.mkstemp(
                prefix=".health-", suffix=".tmp",
                dir=os.path.dirname(path),
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception as exc:
            logger.debug("health heartbeat write failed: %s", exc)
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    def mark_task_started(self, task_id: str) -> None:
        self._current_task = task_id
        self._stats["tasks_leased"] += 1
        self.heartbeat(force=True)

    def mark_task_completed(self, task_id: str) -> None:
        self._current_task = None
        self._stats["tasks_completed"] += 1
        self._stats["error_streak"] = 0
        self.heartbeat(force=True)

    def mark_task_failed(self, task_id: str) -> None:
        self._current_task = None
        self._stats["tasks_failed"] += 1
        self._stats["error_streak"] += 1
        self.heartbeat(force=True)

    def mark_worker_restart(self) -> None:
        self._stats["worker_restarts"] += 1
        self.heartbeat(force=True)

    def set_provider_health(self, provider: str, status: str) -> None:
        self._provider_health[provider] = status

    def mark_dead(self, reason: str = "") -> None:
        """Write a final 'not alive' status before shutdown."""
        try:
            path = self._health_path()
            status = {
                "alive": False,
                "last_heartbeat": time.time(),
                "uptime_seconds": round(time.time() - self._started_at, 1),
                "shutdown_reason": reason,
                **self._stats,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)
        except Exception:
            pass

    def read_health(root_dir: str) -> Dict[str, Any]:
        """Read the current health status (for external monitoring)."""
        path = os.path.join(root_dir, ".nexus", _HEALTH_FILE)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"alive": False, "error": "no health file found"}

    def is_healthy(root_dir: str, max_heartbeat_age: float = 120.0) -> bool:
        """Check if the agent is healthy based on heartbeat freshness."""
        health = HealthMonitor.read_health(root_dir)
        if not health.get("alive"):
            return False
        last = health.get("last_heartbeat", 0)
        return (time.time() - last) < max_heartbeat_age
