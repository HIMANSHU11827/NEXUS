"""Durable SQLite-backed task queue for NEXUS.

Dependency-free (stdlib sqlite3 + threading only). Stores tasks in a SQLite
database so queued work survives process restarts -- enabling true 24/7
autonomy instead of the memory-only threads the old TaskManager used.

Thread safety: every public method opens its own sqlite connection guarded by
a shared threading.Lock, so the queue is safe to share across worker threads.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

# Valid task states
STATE_QUEUED = "queued"
STATE_LEASED = "leased"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_RETRYING = "retrying"
VALID_STATES = (
    STATE_QUEUED,
    STATE_LEASED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RETRYING,
)


def _now() -> float:
    return time.time()


def _new_token() -> str:
    return uuid.uuid4().hex


class TaskQueue:
    """A durable FIFO-ish task queue backed by SQLite.

    Payload is stored as JSON text with keys:
        task_desc, voice_mode, provider, model, priority, meta
    plus any caller-supplied keyword arguments merged into ``meta``.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        root: Optional[str] = None,
        default_max_attempts: int = 3,
    ) -> None:
        if db_path is None:
            base = root or os.environ.get("NEXUS_ROOT") or os.getcwd()
            db_path = os.path.join(base, ".nexus_queue.db")
        self.db_path = db_path
        self.default_max_attempts = default_max_attempts
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        payload       TEXT    NOT NULL,
                        state         TEXT    NOT NULL DEFAULT 'queued',
                        attempts      INTEGER NOT NULL DEFAULT 0,
                        max_attempts  INTEGER NOT NULL DEFAULT 3,
                        lease_token   TEXT,
                        leased_until  REAL,
                        created_at    REAL    NOT NULL,
                        updated_at    REAL    NOT NULL,
                        result        TEXT,
                        error         TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_state "
                    "ON tasks(state, CAST(JSON_EXTRACT(payload, '$.priority') "
                    "AS INTEGER) DESC, id ASC)"
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        except (ValueError, TypeError):
            d["payload"] = {}
        return d

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def enqueue(
        self,
        task_desc: str,
        voice_mode: str = "text",
        provider: str = "",
        model: str = "",
        priority: int = 0,
        max_attempts: Optional[int] = None,
        **meta: Any,
    ) -> int:
        """Add a task and return its new id."""
        payload = {
            "task_desc": task_desc,
            "voice_mode": voice_mode,
            "provider": provider,
            "model": model,
            "priority": priority,
            "meta": meta,
        }
        ts = _now()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO tasks
                        (payload, state, attempts, max_attempts, created_at, updated_at)
                    VALUES (?, ?, 0, ?, ?, ?)
                    """,
                    (
                        json.dumps(payload),
                        STATE_QUEUED,
                        max_attempts if max_attempts is not None
                        else self.default_max_attempts,
                        ts,
                        ts,
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)
            finally:
                conn.close()

    def lease(
        self,
        timeout_sec: int = 300,
        worker_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Atomically grab the next queued (or retrying) task.

        Sets state=leased, a fresh lease_token, leased_until=now+timeout_sec,
        and increments attempts. Returns the task dict or None if nothing is
        available.
        """
        now = _now()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    SELECT id FROM tasks
                    WHERE state = ?
                       OR (state = ? AND (leased_until IS NULL OR leased_until <= ?))
                    ORDER BY CAST(JSON_EXTRACT(payload, '$.priority')
                        AS INTEGER) DESC, id ASC
                    LIMIT 1
                    """,
                    (STATE_QUEUED, STATE_RETRYING, now),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                task_id = int(row["id"])

                token = _new_token()
                leased_until = now + timeout_sec
                conn.execute(
                    """
                    UPDATE tasks
                    SET state = ?,
                        lease_token = ?,
                        leased_until = ?,
                        attempts = attempts + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (STATE_LEASED, token, leased_until, now, task_id),
                )
                conn.commit()

                cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
                return self._row_to_dict(cur.fetchone())
            finally:
                conn.close()

    def complete(self, task_id: int, result: Any, lease_token: Optional[str] = None) -> bool:
        """Mark a task completed, only when the caller still owns its lease.

        ``lease_token`` is optional for backwards-compatible administrative
        callers. Workers must pass the token returned by :meth:`lease`; an
        expired worker can then never overwrite a newer worker's result.
        """
        ts = _now()
        with self._lock:
            conn = self._connect()
            try:
                query = """
                    UPDATE tasks
                    SET state = ?, result = ?, lease_token = NULL,
                        leased_until = NULL, updated_at = ?
                    WHERE id = ?
                """
                params: tuple[Any, ...] = (STATE_COMPLETED, json.dumps(result), ts, task_id)
                if lease_token:
                    query += " AND state = ? AND lease_token = ?"
                    params += (STATE_LEASED, lease_token)
                cur = conn.execute(query, params)
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def fail(
        self,
        task_id: int,
        error: str,
        requeue_after: Optional[float] = None,
        lease_token: Optional[str] = None,
    ) -> bool:
        """Mark a task failed.

        If the task still has attempts left (< max_attempts) it is moved to
        ``retrying`` (re-leasable immediately, or after ``requeue_after``
        seconds by simply leaving it retrying). Otherwise it is ``failed``
        permanently.
        """
        ts = _now()
        with self._lock:
            conn = self._connect()
            try:
                select = "SELECT attempts, max_attempts FROM tasks WHERE id = ?"
                select_params: tuple[Any, ...] = (task_id,)
                if lease_token:
                    select += " AND state = ? AND lease_token = ?"
                    select_params += (STATE_LEASED, lease_token)
                cur = conn.execute(select, select_params)
                row = cur.fetchone()
                if row is None:
                    return False
                attempts = int(row["attempts"])
                max_attempts = int(row["max_attempts"])
                # attempts was already incremented at lease time
                if attempts < max_attempts:
                    new_state = STATE_RETRYING
                else:
                    new_state = STATE_FAILED
                delay = requeue_after or 0.0
                query = """
                    UPDATE tasks
                    SET state = ?, error = ?, lease_token = NULL,
                        leased_until = ?, updated_at = ?
                    WHERE id = ?
                """
                params: tuple[Any, ...] = (new_state, str(error), ts + delay, ts, task_id)
                if lease_token:
                    query += " AND state = ? AND lease_token = ?"
                    params += (STATE_LEASED, lease_token)
                cur = conn.execute(query, params)
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def ack_lease(self, task_id: int, token: str, timeout_sec: Optional[float] = None) -> bool:
        """Confirm a worker still holds the lease for task_id, renewing it.

        Returns True only when the given token matches the stored lease_token
        (i.e. the lease is still valid / owned by this worker). When
        ``timeout_sec`` is given the lease is *renewed* — ``leased_until`` is
        pushed forward to ``now + timeout_sec`` — so a long-running worker can
        heart-beat its lease before it expires. With no ``timeout_sec`` this
        behaves exactly as before (pure ownership check).
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT lease_token FROM tasks WHERE id = ?", (task_id,)
                )
                row = cur.fetchone()
                if row is None or row["lease_token"] != token:
                    return False
                if timeout_sec is not None:
                    conn.execute(
                        """
                        UPDATE tasks
                        SET leased_until = ?, updated_at = ?
                        WHERE id = ? AND state = ? AND lease_token = ?
                        """,
                        (_now() + float(timeout_sec), _now(), task_id,
                         STATE_LEASED, token),
                    )
                    conn.commit()
                return True
            finally:
                conn.close()

    def list_states(self) -> Dict[str, int]:
        """Return a count of tasks per state."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT state, COUNT(*) AS n FROM tasks GROUP BY state"
                )
                counts = {s: 0 for s in VALID_STATES}
                for row in cur.fetchall():
                    counts[row["state"]] = int(row["n"])
                return counts
            finally:
                conn.close()

    def pending_count(self) -> int:
        """Count tasks that are queued or retrying (i.e. eligible to lease)."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM tasks
                    WHERE state = ?
                       OR (state = ? AND (leased_until IS NULL OR leased_until <= ?))
                    """,
                    (STATE_QUEUED, STATE_RETRYING, _now()),
                )
                return int(cur.fetchone()["n"])
            finally:
                conn.close()

    def requeue_expired_leases(self) -> int:
        """Requeue tasks whose lease has expired (leased_until < now).

        Expired leases become either ``queued`` (if still attempts left) or
        ``failed`` (if attempts exhausted). Returns the number requeued.
        """
        now = _now()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    SELECT id, attempts, max_attempts FROM tasks
                    WHERE state = ? AND leased_until IS NOT NULL AND leased_until < ?
                    """,
                    (STATE_LEASED, now),
                )
                expired = cur.fetchall()
                requeued = 0
                for row in expired:
                    attempts = int(row["attempts"])
                    max_attempts = int(row["max_attempts"])
                    if attempts < max_attempts:
                        new_state = STATE_QUEUED
                    else:
                        new_state = STATE_FAILED
                    conn.execute(
                        """
                        UPDATE tasks
                        SET state = ?, lease_token = NULL, leased_until = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (new_state, now, int(row["id"])),
                    )
                    requeued += 1
                conn.commit()
                return requeued
            finally:
                conn.close()

    def get(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single task by id (for inspection)."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
                row = cur.fetchone()
                return self._row_to_dict(row) if row else None
            finally:
                conn.close()

    def list_unfinished(self, session_id: str = "") -> List[Dict[str, Any]]:
        """Return queued, retrying, or leased tasks that survive a restart."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT * FROM tasks WHERE state IN (?, ?, ?) ORDER BY id ASC",
                    (STATE_QUEUED, STATE_RETRYING, STATE_LEASED),
                )
                rows = [self._row_to_dict(row) for row in cur.fetchall()]
                if not session_id:
                    return rows
                return [
                    row for row in rows
                    if str((row.get("payload") or {}).get("meta", {}).get("session_id") or "") == str(session_id)
                ]
            finally:
                conn.close()


__all__ = ["TaskQueue", "VALID_STATES"]
