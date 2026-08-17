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

from models.providers.core.reliability import redact_secrets

# Valid task states
STATE_QUEUED = "queued"
STATE_LEASED = "leased"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_RETRYING = "retrying"
STATE_CANCELLED = "cancelled"
VALID_STATES = (
    STATE_QUEUED,
    STATE_LEASED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RETRYING,
    STATE_CANCELLED,
)


def _now() -> float:
    return time.time()


def _new_token() -> str:
    return uuid.uuid4().hex


def _redact_result(value: Any) -> Any:
    """Redact secret material from durable results without flattening JSON."""
    if isinstance(value, dict):
        return {key: _redact_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_result(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_result(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_secrets(value)


def _safe_error(value: Any) -> str:
    """Keep durable task diagnostics useful without persisting secrets."""
    return redact_secrets(str(value or ""))[:1000]


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
        self.root = os.path.abspath(root or os.path.dirname(db_path) if db_path else root or os.getcwd())
        if db_path is None:
            base = root or os.environ.get("NEXUS_ROOT") or os.getcwd()
            db_path = os.path.join(base, ".nexus_queue.db")
        self.db_path = os.path.abspath(db_path)
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
                        dedupe_key    TEXT    NOT NULL DEFAULT '',
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
                columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
                if "dedupe_key" not in columns:
                    conn.execute("ALTER TABLE tasks ADD COLUMN dedupe_key TEXT NOT NULL DEFAULT ''")
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_dedupe_key "
                    "ON tasks(dedupe_key) WHERE dedupe_key <> ''"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_state "
                    "ON tasks(state, CAST(JSON_EXTRACT(payload, '$.priority') "
                    "AS INTEGER) DESC, id ASC)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cron_jobs (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        interval_minutes INTEGER NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        next_run_at REAL NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        last_run_at REAL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cron_runs (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        scheduled_for REAL NOT NULL,
                        trigger TEXT NOT NULL DEFAULT 'schedule',
                        task_id INTEGER,
                        status TEXT NOT NULL DEFAULT 'queued',
                        created_at REAL NOT NULL,
                        completed_at REAL,
                        error TEXT,
                        UNIQUE(job_id, scheduled_for, trigger)
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cron_jobs_due ON cron_jobs(enabled, next_run_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cron_runs_job ON cron_runs(job_id, created_at DESC)")
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        except (ValueError, TypeError) as exc:
            d["payload"] = {
                "_payload_error": f"invalid json payload: {exc}",
                "_raw_payload": str(d["payload"])[:2000],
            }
        return d

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def create_cron_job(
        self, job_id: str, name: str, prompt: str, interval_minutes: int,
        *, enabled: bool = True, next_run_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Create a durable interval job, idempotently by ``job_id``."""
        now = _now()
        interval = max(1, int(interval_minutes))
        next_run = float(next_run_at if next_run_at is not None else now + interval * 60)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO cron_jobs(id,name,prompt,interval_minutes,enabled,next_run_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (str(job_id), str(name), str(prompt), interval, int(bool(enabled)), next_run, now, now),
                )
                conn.commit()
                return self.get_cron_job(job_id, _connection=conn) or {}
            finally:
                conn.close()

    def get_cron_job(self, job_id: str, _connection: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
        """Return one durable cron definition."""
        own = _connection is None
        conn = _connection or self._connect()
        try:
            row = conn.execute("SELECT * FROM cron_jobs WHERE id = ?", (str(job_id),)).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["enabled"] = bool(item.get("enabled"))
            return item
        finally:
            if own:
                conn.close()

    def list_cron_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT * FROM cron_jobs ORDER BY created_at ASC").fetchall()
                return [self._cron_job_dict(row) for row in rows]
            finally:
                conn.close()

    @staticmethod
    def _cron_job_dict(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        return item

    def update_cron_job(self, job_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        allowed = {"name", "prompt", "interval_minutes", "enabled", "next_run_at"}
        updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
        if "interval_minutes" in updates:
            updates["interval_minutes"] = max(1, int(updates["interval_minutes"]))
        if "enabled" in updates:
            updates["enabled"] = int(bool(updates["enabled"]))
        if not updates:
            return self.get_cron_job(job_id)
        updates["updated_at"] = _now()
        with self._lock:
            conn = self._connect()
            try:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                values = list(updates.values()) + [str(job_id)]
                cur = conn.execute(f"UPDATE cron_jobs SET {assignments} WHERE id = ?", values)
                conn.commit()
                if cur.rowcount == 0:
                    return None
                return self.get_cron_job(job_id, _connection=conn)
            finally:
                conn.close()

    def delete_cron_job(self, job_id: str) -> bool:
        """Disable future occurrences while retaining the job/run history."""
        return self.update_cron_job(job_id, enabled=False) is not None

    def _insert_cron_task(self, conn: sqlite3.Connection, job: Dict[str, Any], run_id: str, scheduled_for: float, trigger: str) -> int:
        key = f"cron:{job['id']}:{trigger}:{int(float(scheduled_for) * 1000)}"
        payload = {
            "task_desc": str(job["prompt"]), "voice_mode": "text", "provider": "", "model": "",
            "priority": 0, "meta": {"cron_job_id": str(job["id"]), "cron_run_id": run_id,
                                      "scheduled_for": scheduled_for, "trigger": trigger, "idempotency_key": key},
        }
        now = _now()
        existing = conn.execute("SELECT id FROM tasks WHERE dedupe_key = ?", (key,)).fetchone()
        if existing is not None:
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO tasks(payload,dedupe_key,state,attempts,max_attempts,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (json.dumps(payload), key, STATE_QUEUED, 0, self.default_max_attempts, now, now),
        )
        return int(cur.lastrowid)

    def enqueue_cron_run(self, job_id: str, *, trigger: str = "manual", now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Atomically create a cron run and its queue task."""
        current = float(now if now is not None else _now())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                job = self.get_cron_job(job_id, _connection=conn)
                if job is None:
                    conn.rollback()
                    return None
                run_id = f"cron_run_{uuid.uuid4().hex[:16]}"
                task_id = self._insert_cron_task(conn, job, run_id, current, trigger)
                conn.execute(
                    "INSERT INTO cron_runs(id,job_id,scheduled_for,trigger,task_id,status,created_at) VALUES (?,?,?,?,?,?,?)",
                    (run_id, str(job_id), current, trigger, task_id, "queued", current),
                )
                conn.commit()
                return {"run_id": run_id, "job_id": str(job_id), "task_id": task_id, "status": "queued", "scheduled_for": current}
            finally:
                conn.close()

    def enqueue_due_cron_runs(self, now: Optional[float] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Materialize due interval slots once; queue workers own execution."""
        current = float(now if now is not None else _now())
        created: List[Dict[str, Any]] = []
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                jobs = conn.execute(
                    "SELECT * FROM cron_jobs WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at ASC LIMIT ?",
                    (current, max(1, min(int(limit), 1000))),
                ).fetchall()
                for row in jobs:
                    job = self._cron_job_dict(row)
                    slot = float(job["next_run_at"])
                    run_id = f"cron_run_{uuid.uuid4().hex[:16]}"
                    task_id = self._insert_cron_task(conn, job, run_id, slot, "schedule")
                    inserted = conn.execute(
                        "INSERT OR IGNORE INTO cron_runs(id,job_id,scheduled_for,trigger,task_id,status,created_at) VALUES (?,?,?,?,?,?,?)",
                        (run_id, job["id"], slot, "schedule", task_id, "queued", current),
                    ).rowcount
                    if inserted:
                        created.append({"run_id": run_id, "job_id": job["id"], "task_id": task_id, "status": "queued", "scheduled_for": slot})
                    next_run = slot + max(1, int(job["interval_minutes"])) * 60
                    while next_run <= current:
                        next_run += max(1, int(job["interval_minutes"])) * 60
                    conn.execute("UPDATE cron_jobs SET next_run_at = ?, last_run_at = ?, updated_at = ? WHERE id = ?", (next_run, slot, current, job["id"]))
                conn.commit()
                return created
            finally:
                conn.close()

    def update_cron_run(self, run_id: str, status: str, *, error: str = "") -> bool:
        terminal = status in {"completed", "failed", "cancelled"}
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE cron_runs SET status = ?, error = ?, completed_at = CASE WHEN ? THEN ? ELSE completed_at END WHERE id = ?",
                    (str(status), _safe_error(error), int(terminal), _now(), str(run_id)),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def list_cron_runs(self, job_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                if job_id:
                    rows = conn.execute("SELECT * FROM cron_runs WHERE job_id = ? ORDER BY created_at DESC LIMIT ?", (str(job_id), max(1, min(int(limit), 1000)))).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM cron_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()
    def enqueue(
        self,
        task_desc: str,
        voice_mode: str = "text",
        provider: str = "",
        model: str = "",
        priority: int = 0,
        max_attempts: Optional[int] = None,
        idempotency_key: str = "",
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
        dedupe_key = str(idempotency_key or meta.get("idempotency_key") or "").strip()[:240]
        if dedupe_key:
            payload["meta"]["idempotency_key"] = dedupe_key
        ts = _now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                if dedupe_key:
                    existing = conn.execute(
                        """
                        SELECT id FROM tasks
                        WHERE dedupe_key = ?
                           OR JSON_EXTRACT(payload, '$.meta.idempotency_key') = ?
                        ORDER BY id ASC LIMIT 1
                        """,
                        (dedupe_key, dedupe_key),
                    ).fetchone()
                    if existing is not None:
                        conn.commit()
                        return int(existing["id"])
                cur = conn.execute(
                    """
                    INSERT INTO tasks
                        (payload, dedupe_key, state, attempts, max_attempts, created_at, updated_at)
                    VALUES (?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        json.dumps(payload),
                        dedupe_key,
                        STATE_QUEUED,
                        max_attempts if max_attempts is not None
                        else self.default_max_attempts,
                        ts,
                        ts,
                    ),
                )
                conn.commit()
                if cur.rowcount == 0:
                    existing = conn.execute(
                        "SELECT id FROM tasks WHERE dedupe_key = ?", (dedupe_key,)
                    ).fetchone()
                    if existing is not None:
                        return int(existing["id"])
                return int(cur.lastrowid)
            finally:
                conn.close()

    def enqueue_once(
        self,
        task_desc: str,
        *,
        idempotency_key: str,
        voice_mode: str = "text",
        provider: str = "",
        model: str = "",
        priority: int = 0,
        max_attempts: Optional[int] = None,
        **meta: Any,
    ) -> int:
        """Compatibility wrapper for :meth:`enqueue` with a required key."""
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key must be non-empty")
        return self.enqueue(
            task_desc,
            voice_mode=voice_mode,
            provider=provider,
            model=model,
            priority=priority,
            max_attempts=max_attempts,
            idempotency_key=key,
            **meta,
        )

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
        for lock_attempt in range(4):
            now = _now()
            with self._lock:
                conn = self._connect()
                try:
                # The Python lock only protects callers sharing one
                # TaskQueue instance.  Separate workers/processes must claim
                # through SQLite's write transaction or they can both observe
                # the same candidate before either UPDATE commits.
                    conn.execute("BEGIN IMMEDIATE")
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
                    claimed = conn.execute(
                    """
                    UPDATE tasks
                    SET state = ?,
                        lease_token = ?,
                        leased_until = ?,
                        attempts = attempts + 1,
                        updated_at = ?
                    WHERE id = ? AND (state = ? OR
                        (state = ? AND (leased_until IS NULL OR leased_until <= ?)))
                    """,
                    (STATE_LEASED, token, leased_until, now, task_id,
                     STATE_QUEUED, STATE_RETRYING, now),
                )
                    if claimed.rowcount != 1:
                        conn.rollback()
                        return None
                    conn.commit()

                    cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
                    return self._row_to_dict(cur.fetchone())
                except sqlite3.OperationalError as exc:
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                    if "locked" not in str(exc).lower() or lock_attempt >= 3:
                        raise
                    time.sleep(0.01 * (lock_attempt + 1))
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
                params: tuple[Any, ...] = (
                    STATE_COMPLETED,
                    json.dumps(_redact_result(result), default=str),
                    ts,
                    task_id,
                )
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
                params: tuple[Any, ...] = (new_state, _safe_error(error), ts + delay, ts, task_id)
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
                    "SELECT state, lease_token, leased_until FROM tasks WHERE id = ?",
                    (task_id,),
                )
                row = cur.fetchone()
                now = _now()
                if (
                    row is None
                    or row["state"] != STATE_LEASED
                    or row["lease_token"] != token
                    or row["leased_until"] is None
                    or float(row["leased_until"]) <= now
                ):
                    return False
                if timeout_sec is not None:
                    conn.execute(
                        """
                        UPDATE tasks
                        SET leased_until = ?, updated_at = ?
                        WHERE id = ? AND state = ? AND lease_token = ?
                        """,
                        (now + float(timeout_sec), now, task_id,
                         STATE_LEASED, token),
                    )
                    conn.commit()
                return True
            finally:
                conn.close()

    def owns_lease(self, task_id: int, lease_token: str) -> bool:
        """Return whether a worker still owns a live lease right now."""
        if not lease_token:
            return False
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT 1 FROM tasks
                    WHERE id = ? AND state = ? AND lease_token = ?
                      AND leased_until IS NOT NULL AND leased_until > ?
                    """,
                    (task_id, STATE_LEASED, lease_token, _now()),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def cancel(
        self,
        task_id: int,
        reason: str = "cancelled",
        lease_token: Optional[str] = None,
    ) -> bool:
        """Durably cancel a leased task without making it eligible for replay."""
        ts = _now()
        with self._lock:
            conn = self._connect()
            try:
                query = """
                    UPDATE tasks SET state = ?, error = ?, lease_token = NULL,
                        leased_until = NULL, updated_at = ?
                    WHERE id = ? AND state = ?
                """
                params: tuple[Any, ...] = (STATE_CANCELLED, _safe_error(reason), ts,
                                           task_id, STATE_LEASED)
                if lease_token:
                    query += " AND lease_token = ?"
                    params += (lease_token,)
                cur = conn.execute(query, params)
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def quarantine_uncertain(self, task_id: int, reason: str) -> bool:
        """Stop every replay path after an execution outcome becomes unknown.

        Unlike ordinary worker completion this is intentionally not guarded by
        the old lease token. A replacement lease may already exist when a
        cancellation-resistant prior attempt reports uncertainty; invalidating
        that replacement is the only safe generic action until an operator or
        idempotent adapter reconciles the external effect. Completed/failed
        terminal records remain authoritative and are never overwritten.
        """
        ts = _now()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    UPDATE tasks SET state = ?, error = ?, lease_token = NULL,
                        leased_until = NULL, updated_at = ?
                    WHERE id = ? AND state IN (?, ?, ?)
                    """,
                    (
                        STATE_CANCELLED,
                        _safe_error("uncertain external outcome: " + str(reason or "")),
                        ts,
                        task_id,
                        STATE_QUEUED,
                        STATE_LEASED,
                        STATE_RETRYING,
                    ),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    @staticmethod
    def _payload_matches_scope(payload: Any, session_id: str = "", include_global: bool = False) -> bool:
        """Return whether a payload belongs to an optional session scope."""
        if not session_id:
            return True
        data = payload if isinstance(payload, dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        task_session = str(meta.get("session_id") or "")
        return task_session == str(session_id) or (include_global and not task_session)

    def list_states(self, session_id: str = "", include_global: bool = False) -> Dict[str, int]:
        """Return task counts per state, optionally limited to a session."""
        with self._lock:
            conn = self._connect()
            try:
                counts = {s: 0 for s in VALID_STATES}
                if not session_id:
                    cur = conn.execute("SELECT state, COUNT(*) AS n FROM tasks GROUP BY state")
                    for row in cur.fetchall():
                        counts[row["state"]] = int(row["n"])
                    return counts
                rows = conn.execute("SELECT state, payload FROM tasks").fetchall()
                for row in rows:
                    try:
                        payload = json.loads(row["payload"] or "{}")
                    except (TypeError, ValueError):
                        payload = {}
                    if self._payload_matches_scope(payload, session_id, include_global):
                        counts[str(row["state"])] = counts.get(str(row["state"]), 0) + 1
                return counts
            finally:
                conn.close()

    def pending_count(self, session_id: str = "", include_global: bool = False) -> int:
        """Count eligible queued/retrying tasks, optionally limited to a session."""
        with self._lock:
            conn = self._connect()
            try:
                now = _now()
                if not session_id:
                    cur = conn.execute(
                        """
                        SELECT COUNT(*) AS n FROM tasks
                        WHERE state = ?
                           OR (state = ? AND (leased_until IS NULL OR leased_until <= ?))
                        """,
                        (STATE_QUEUED, STATE_RETRYING, now),
                    )
                    return int(cur.fetchone()["n"])
                rows = conn.execute("SELECT state, leased_until, payload FROM tasks").fetchall()
                count = 0
                for row in rows:
                    if str(row["state"]) == STATE_QUEUED:
                        eligible = True
                    elif str(row["state"]) == STATE_RETRYING:
                        eligible = row["leased_until"] is None or float(row["leased_until"]) <= now
                    else:
                        eligible = False
                    if not eligible:
                        continue
                    try:
                        payload = json.loads(row["payload"] or "{}")
                    except (TypeError, ValueError):
                        payload = {}
                    if self._payload_matches_scope(payload, session_id, include_global):
                        count += 1
                return count
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
                    SELECT id, attempts, max_attempts, lease_token, leased_until FROM tasks
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
                    updated = conn.execute(
                        """
                        UPDATE tasks
                        SET state = ?, lease_token = NULL, leased_until = NULL,
                            updated_at = ?
                        WHERE id = ? AND state = ? AND lease_token = ?
                          AND leased_until IS NOT NULL AND leased_until < ?
                        """,
                        (
                            new_state,
                            now,
                            int(row["id"]),
                            STATE_LEASED,
                            row["lease_token"],
                            now,
                        ),
                    )
                    # A worker may have renewed or completed the task after
                    # the snapshot SELECT. Never overwrite its newer state.
                    if updated.rowcount == 1:
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
