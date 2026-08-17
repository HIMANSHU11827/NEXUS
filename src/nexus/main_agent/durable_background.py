"""Small SQLite ledger for restartable V5 background jobs.

The ledger stores lifecycle state and a stable factory key.  Callable objects
are intentionally never serialized; a process must register the matching
factory before recovery, which keeps restart behavior explicit and safe.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List


def _process_is_alive(pid: int) -> bool:
    """Return a conservative process-liveness result across platforms.

    ``os.kill(pid, 0)`` is a useful POSIX probe but is not a portable Windows
    process-query API.  Windows uses ``GetExitCodeProcess`` here so a healthy
    background owner is not reclaimed during restart recovery merely because
    the platform rejects signal 0.
    """
    try:
        safe_pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if safe_pid <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(
                process_query_limited_information, 0, safe_pid
            )
            if not handle:
                # Access denied is not proof of death; preserve the job and
                # let the heartbeat watchdog make a later, stronger decision.
                return ctypes.get_last_error() == 5
            try:
                exit_code = ctypes.c_uint32()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                # STILL_ACTIVE is 259 on Windows.
                return int(exit_code.value) == 259
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # Keep recovery conservative if the native API is unavailable.
            return True

    try:
        os.kill(safe_pid, 0)
        return True
    except (ProcessLookupError, FileNotFoundError):
        return False
    except PermissionError:
        return True
    except OSError:
        return False


class DurableBackgroundStore:
    """Thread-safe durable lifecycle store for restartable background jobs."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root or os.getcwd())
        self.path = os.path.join(self.root, ".nexus", "background_tasks.sqlite3")
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS background_tasks (
                    task_id TEXT PRIMARY KEY,
                    factory_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 0,
                    timeout_s REAL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    lane TEXT NOT NULL DEFAULT 'default',
                    owner_token TEXT NOT NULL DEFAULT '',
                    owner_pid INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    result_summary TEXT NOT NULL DEFAULT '',
                    heartbeat_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
            columns = {
                str(row[1]) for row in connection.execute(
                    "PRAGMA table_info(background_tasks)"
                ).fetchall()
            }
            if "owner_token" not in columns:
                connection.execute(
                    "ALTER TABLE background_tasks ADD COLUMN owner_token TEXT NOT NULL DEFAULT ''"
                )
            if "owner_pid" not in columns:
                connection.execute(
                    "ALTER TABLE background_tasks ADD COLUMN owner_pid INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_background_status ON background_tasks(status, updated_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create(
        self,
        task_id: str,
        factory_key: str,
        name: str,
        *,
        max_retries: int = 0,
        timeout_s: float | None = None,
        priority: int = 0,
        lane: str = "default",
    ) -> Dict[str, Any]:
        now = time.time()
        values = (
            str(task_id), str(factory_key), str(name), "pending", 0,
            max(0, int(max_retries or 0)),
            float(timeout_s) if timeout_s is not None else None,
            int(priority or 0), str(lane or "default"), "", "", now, now, now,
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO background_tasks
                (task_id, factory_key, name, status, attempt, max_retries,
                 timeout_s, priority, lane, last_error, result_summary,
                 heartbeat_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        return self.get(task_id) or {}

    def mark_running(self, task_id: str) -> None:
        """Legacy unconditional transition retained for compatibility.

        New runners must use :meth:`claim`, which atomically fences
        cross-process recovery attempts.
        """
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE background_tasks SET status='running', attempt=attempt+1, heartbeat_at=?, updated_at=? WHERE task_id=?",
                (now, now, str(task_id)),
            )

    def claim(self, task_id: str, owner_token: str = "") -> bool:
        """Atomically claim a pending/interrupted task for one attempt."""
        token = str(owner_token or uuid.uuid4().hex)
        now = time.time()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "UPDATE background_tasks SET status='running', attempt=attempt+1, "
                "owner_token=?, owner_pid=?, heartbeat_at=?, updated_at=? "
                "WHERE task_id=? AND status IN ('pending', 'interrupted')",
                (token, os.getpid(), now, now, str(task_id)),
            )
        return bool(cursor.rowcount)

    def heartbeat(self, task_id: str, *, owner_token: str = "") -> bool:
        now = time.time()
        with self._lock, self._connection() as connection:
            if owner_token:
                cursor = connection.execute(
                    "UPDATE background_tasks SET heartbeat_at=?, updated_at=? "
                    "WHERE task_id=? AND status='running' AND owner_token=?",
                    (now, now, str(task_id), str(owner_token)),
                )
            else:
                cursor = connection.execute(
                    "UPDATE background_tasks SET heartbeat_at=?, updated_at=? WHERE task_id=? AND status='running'",
                    (now, now, str(task_id)),
                )
        return bool(cursor.rowcount)

    def complete(self, task_id: str, result: Any = "", *, owner_token: str = "") -> bool:
        now = time.time()
        with self._lock, self._connection() as connection:
            if owner_token:
                cursor = connection.execute(
                    "UPDATE background_tasks SET status='completed', result_summary=?, heartbeat_at=?, updated_at=? "
                    "WHERE task_id=? AND status='running' AND owner_token=?",
                    (str(result or "")[:2000], now, now, str(task_id), str(owner_token)),
                )
            else:
                cursor = connection.execute(
                    "UPDATE background_tasks SET status='completed', result_summary=?, heartbeat_at=?, updated_at=? WHERE task_id=?",
                    (str(result or "")[:2000], now, now, str(task_id)),
                )
        return bool(cursor.rowcount)

    def fail(self, task_id: str, error: Any = "", *, owner_token: str = "") -> bool:
        now = time.time()
        with self._lock, self._connection() as connection:
            if owner_token:
                cursor = connection.execute(
                    "UPDATE background_tasks SET status='failed', last_error=?, heartbeat_at=?, updated_at=? "
                    "WHERE task_id=? AND status='running' AND owner_token=?",
                    (str(error or "")[:2000], now, now, str(task_id), str(owner_token)),
                )
            else:
                cursor = connection.execute(
                    "UPDATE background_tasks SET status='failed', last_error=?, heartbeat_at=?, updated_at=? WHERE task_id=?",
                    (str(error or "")[:2000], now, now, str(task_id)),
                )
        return bool(cursor.rowcount)

    def recover_running(self) -> int:
        """Requeue jobs whose owning process is no longer alive.

        A second runner sharing the same SQLite ledger must not interrupt a
        healthy process. Older rows without an owner PID are conservatively
        treated as recoverable legacy records.
        """
        now = time.time()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT task_id, owner_pid FROM background_tasks WHERE status='running'"
            ).fetchall()
            recoverable = []
            for row in rows:
                pid = int(row[1] or 0)
                alive = _process_is_alive(pid)
                if not alive:
                    recoverable.append(str(row[0]))
            if not recoverable:
                return 0
            placeholders = ",".join("?" for _ in recoverable)
            cursor = connection.execute(
                "UPDATE background_tasks SET status='interrupted', owner_token='', owner_pid=0, "
                "last_error='recovered after process restart', updated_at=? "
                f"WHERE status='running' AND task_id IN ({placeholders})",
                (now, *recoverable),
            )
            return int(cursor.rowcount or 0)

    def interrupt_owned(self, owner_pid: int, reason: str = "owner shutdown") -> int:
        """Durably release this process's running jobs for restart recovery."""
        now = time.time()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "UPDATE background_tasks SET status='interrupted', owner_token='', "
                "owner_pid=0, last_error=?, updated_at=? "
                "WHERE status='running' AND owner_pid=?",
                (str(reason or "owner shutdown")[:2000], now, int(owner_pid or 0)),
            )
            return int(cursor.rowcount or 0)

    def recover_stalled(self, stale_after: float = 300.0) -> List[str]:
        """Move jobs with an expired heartbeat back to the recovery queue.

        This is deliberately separate from :meth:`recover_running`: startup
        recovery may safely treat every prior-process job as interrupted,
        while a live supervisor must only reclaim jobs whose heartbeat is
        demonstrably stale.
        """
        now = time.time()
        cutoff = now - max(1.0, float(stale_after))
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT task_id FROM background_tasks "
                "WHERE status='running' AND heartbeat_at < ?",
                (cutoff,),
            ).fetchall()
            task_ids = [str(row[0]) for row in rows]
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                connection.execute(
                    f"UPDATE background_tasks SET status='interrupted', owner_token='', owner_pid=0, "
                    f"last_error='recovered after stale heartbeat', updated_at=? "
                    f"WHERE status='running' AND task_id IN ({placeholders})",
                    (now, *task_ids),
                )
        return task_ids

    def get(self, task_id: str) -> Dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM background_tasks WHERE task_id=?", (str(task_id),)).fetchone()
        return dict(row) if row is not None else None

    def list(self, statuses: tuple[str, ...] = ()) -> List[Dict[str, Any]]:
        with self._lock, self._connection() as connection:
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                rows = connection.execute(
                    f"SELECT * FROM background_tasks WHERE status IN ({placeholders}) ORDER BY created_at",
                    tuple(statuses),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM background_tasks ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]
