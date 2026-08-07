"""Transactional control-plane store for durable Nexus workflow state.

This is intentionally additive: legacy WorkItem, queue, JSONL and todo.md
callers remain supported while new callers can use one SQLite authority for
Task -> PlanVersion -> Step -> Run -> Lease -> Evidence transitions.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional


def _now() -> float:
    return time.time()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ControlStore:
    """SQLite source of truth with transactional state and an outbox."""

    def __init__(self, root: str, db_path: Optional[str] = None) -> None:
        self.root = os.path.abspath(root)
        self.db_path = db_path or os.path.join(self.root, ".nexus", "control_plane.sqlite3")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_db(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS tasks (
          task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
          goal TEXT NOT NULL, status TEXT NOT NULL, active_plan_id TEXT, priority INTEGER NOT NULL DEFAULT 0,
          created_at REAL NOT NULL, updated_at REAL NOT NULL, completed_at REAL, version INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS plan_versions (
          plan_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id), version INTEGER NOT NULL,
          status TEXT NOT NULL, goal TEXT NOT NULL, source TEXT NOT NULL, supersedes_plan_id TEXT,
          created_at REAL NOT NULL, approved_at REAL, retired_at REAL,
          UNIQUE(task_id, version)
        );
        CREATE TABLE IF NOT EXISTS steps (
          step_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plan_versions(plan_id),
          task_id TEXT NOT NULL REFERENCES tasks(task_id), ordinal INTEGER NOT NULL, title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, execution_kind TEXT NOT NULL DEFAULT 'general',
          workspace_scope TEXT NOT NULL DEFAULT '', agent_role TEXT NOT NULL DEFAULT '', retry_limit INTEGER NOT NULL DEFAULT 2,
          timeout_seconds REAL, acceptance_json TEXT NOT NULL DEFAULT '[]', active_run_id TEXT,
          created_at REAL NOT NULL, updated_at REAL NOT NULL, completed_at REAL, version INTEGER NOT NULL DEFAULT 1,
          UNIQUE(plan_id, ordinal)
        );
        CREATE TABLE IF NOT EXISTS step_dependencies (
          step_id TEXT NOT NULL REFERENCES steps(step_id), depends_on_step_id TEXT NOT NULL REFERENCES steps(step_id),
          PRIMARY KEY(step_id, depends_on_step_id)
        );
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),
          plan_id TEXT NOT NULL REFERENCES plan_versions(plan_id), step_id TEXT NOT NULL REFERENCES steps(step_id),
          parent_run_id TEXT, attempt INTEGER NOT NULL, status TEXT NOT NULL, worker_id TEXT NOT NULL DEFAULT '',
          process_id TEXT NOT NULL DEFAULT '', idempotency_key TEXT NOT NULL, started_at REAL, ended_at REAL,
          deadline_at REAL, failure_code TEXT NOT NULL DEFAULT '', failure_detail TEXT NOT NULL DEFAULT '',
          version INTEGER NOT NULL DEFAULT 1, UNIQUE(step_id, attempt), UNIQUE(idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS leases (
          lease_id TEXT PRIMARY KEY, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
          workspace_scope TEXT NOT NULL DEFAULT '', owner_worker_id TEXT NOT NULL, owner_process_id TEXT NOT NULL,
          lease_token TEXT NOT NULL, heartbeat_at REAL NOT NULL, expires_at REAL NOT NULL, created_at REAL NOT NULL,
          UNIQUE(resource_type, resource_id)
        );
        CREATE TABLE IF NOT EXISTS evidence (
          evidence_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, plan_id TEXT NOT NULL, step_id TEXT NOT NULL,
          run_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, uri TEXT NOT NULL, digest TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '', verified_by TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outbox (
          event_id TEXT PRIMARY KEY, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
          event_type TEXT NOT NULL, payload_json TEXT NOT NULL, causation_id TEXT NOT NULL DEFAULT '',
          idempotency_key TEXT NOT NULL UNIQUE, sequence INTEGER NOT NULL UNIQUE,
          created_at REAL NOT NULL, published_at REAL, delivery_attempts INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS legacy_links (
          source_type TEXT NOT NULL, source_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(task_id),
          plan_id TEXT, step_id TEXT, run_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          PRIMARY KEY(source_type, source_id)
        );
        CREATE INDEX IF NOT EXISTS idx_steps_ready ON steps(plan_id, status, ordinal);
        CREATE INDEX IF NOT EXISTS idx_runs_step ON runs(step_id, status, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_leases_expiry ON leases(expires_at);
        CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(published_at, sequence);
        """
        with self._connect() as connection:
            connection.executescript(schema)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        return dict(row) if row is not None else None

    def _outbox(self, connection: sqlite3.Connection, aggregate_type: str, aggregate_id: str, event_type: str, payload: Dict[str, Any], *, causation_id: str = "", idempotency_key: str = "") -> int:
        key = idempotency_key or _id("outbox")
        sequence = int(connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM outbox").fetchone()[0])
        connection.execute(
            "INSERT INTO outbox(event_id, aggregate_type, aggregate_id, event_type, payload_json, causation_id, idempotency_key, sequence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_id("evt"), aggregate_type, aggregate_id, event_type, json.dumps(payload, ensure_ascii=False), causation_id, key, sequence, _now()),
        )
        return sequence

    def create_task(self, *, goal: str, session_id: str = "default", workspace_id: str = "", priority: int = 0, task_id: str = "") -> Dict[str, Any]:
        now, identifier = _now(), task_id or _id("task")
        with self._transaction() as connection:
            connection.execute("INSERT INTO tasks(task_id, session_id, workspace_id, goal, status, priority, created_at, updated_at) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)", (identifier, session_id, workspace_id or self.root, str(goal)[:4000], int(priority), now, now))
            self._outbox(connection, "task", identifier, "task.created", {"task_id": identifier, "goal": goal})
            return self._row(connection.execute("SELECT * FROM tasks WHERE task_id = ?", (identifier,)).fetchone()) or {}

    def create_plan(self, *, task_id: str, goal: str, steps: Iterable[Dict[str, Any]], source: str = "planner", plan_id: str = "") -> Dict[str, Any]:
        now, identifier = _now(), plan_id or _id("plan")
        step_values = list(steps)
        with self._transaction() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise KeyError(f"Task not found: {task_id}")
            prior = connection.execute("SELECT plan_id, version FROM plan_versions WHERE task_id = ? AND status = 'active'", (task_id,)).fetchone()
            version = int(connection.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM plan_versions WHERE task_id = ?", (task_id,)).fetchone()[0])
            if prior is not None:
                connection.execute("UPDATE plan_versions SET status = 'superseded', retired_at = ? WHERE plan_id = ?", (now, prior["plan_id"]))
            connection.execute("INSERT INTO plan_versions(plan_id, task_id, version, status, goal, source, supersedes_plan_id, created_at) VALUES (?, ?, ?, 'active', ?, ?, ?, ?)", (identifier, task_id, version, str(goal)[:4000], source, prior["plan_id"] if prior else None, now))
            ids: List[str] = []
            for ordinal, value in enumerate(step_values, start=1):
                step_id = str(value.get("step_id") or _id("step"))
                ids.append(step_id)
                connection.execute("INSERT INTO steps(step_id, plan_id, task_id, ordinal, title, description, status, execution_kind, workspace_scope, agent_role, retry_limit, timeout_seconds, acceptance_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)", (step_id, identifier, task_id, ordinal, str(value.get("title") or "Untitled step")[:300], str(value.get("description") or "")[:4000], str(value.get("execution_kind") or "general"), str(value.get("workspace_scope") or ""), str(value.get("agent_role") or ""), max(0, int(value.get("retry_limit", 2))), value.get("timeout_seconds"), json.dumps(value.get("acceptance_criteria") or []), now, now))
            for ordinal, value in enumerate(step_values):
                for dependency in value.get("dependencies") or []:
                    if dependency not in ids:
                        raise ValueError(f"Unknown dependency: {dependency}")
                    connection.execute("INSERT INTO step_dependencies(step_id, depends_on_step_id) VALUES (?, ?)", (ids[ordinal], dependency))
            connection.execute("UPDATE tasks SET status = 'planned', active_plan_id = ?, updated_at = ?, version = version + 1 WHERE task_id = ?", (identifier, now, task_id))
            self._outbox(connection, "plan", identifier, "plan.created", {"task_id": task_id, "plan_id": identifier, "version": version})
            return self._row(connection.execute("SELECT * FROM plan_versions WHERE plan_id = ?", (identifier,)).fetchone()) or {}

    def ready_steps(self, plan_id: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("""SELECT s.* FROM steps s WHERE s.plan_id = ? AND s.status IN ('pending', 'ready') AND NOT EXISTS (SELECT 1 FROM step_dependencies d JOIN steps prerequisite ON prerequisite.step_id = d.depends_on_step_id WHERE d.step_id = s.step_id AND prerequisite.status != 'completed') ORDER BY s.ordinal""", (plan_id,)).fetchall()
            return [dict(row) for row in rows]

    def start_run(self, *, step_id: str, worker_id: str, process_id: str, lease_seconds: float = 90, deadline_at: Optional[float] = None, idempotency_key: str = "") -> Dict[str, Any]:
        now = _now()
        with self._transaction() as connection:
            step = connection.execute("SELECT * FROM steps WHERE step_id = ?", (step_id,)).fetchone()
            if step is None:
                raise KeyError(f"Step not found: {step_id}")
            blockers = connection.execute("""SELECT 1 FROM step_dependencies d JOIN steps prerequisite ON prerequisite.step_id = d.depends_on_step_id WHERE d.step_id = ? AND prerequisite.status != 'completed' LIMIT 1""", (step_id,)).fetchone()
            if step["status"] not in {"pending", "ready"} or blockers is not None:
                raise ValueError(f"Step is not ready: {step_id}")
            existing = connection.execute("SELECT * FROM leases WHERE resource_type = 'step' AND resource_id = ? AND expires_at > ?", (step_id, now)).fetchone()
            if existing is not None:
                raise RuntimeError(f"Step is already leased: {step_id}")
            attempt = int(connection.execute("SELECT COALESCE(MAX(attempt), 0) + 1 FROM runs WHERE step_id = ?", (step_id,)).fetchone()[0])
            run_id, token = _id("run"), _id("lease")
            connection.execute("INSERT INTO runs(run_id, task_id, plan_id, step_id, attempt, status, worker_id, process_id, idempotency_key, started_at, deadline_at) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)", (run_id, step["task_id"], step["plan_id"], step_id, attempt, worker_id, process_id, idempotency_key or _id("run_key"), now, deadline_at))
            connection.execute("INSERT INTO leases(lease_id, resource_type, resource_id, workspace_scope, owner_worker_id, owner_process_id, lease_token, heartbeat_at, expires_at, created_at) VALUES (?, 'step', ?, ?, ?, ?, ?, ?, ?, ?)", (_id("lease"), step_id, step["workspace_scope"], worker_id, process_id, token, now, now + max(1.0, lease_seconds), now))
            connection.execute("UPDATE steps SET status = 'running', active_run_id = ?, updated_at = ?, version = version + 1 WHERE step_id = ?", (run_id, now, step_id))
            self._outbox(connection, "run", run_id, "run.started", {"task_id": step["task_id"], "plan_id": step["plan_id"], "step_id": step_id, "run_id": run_id})
            result = self._row(connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()) or {}
            result["lease_token"] = token
            return result

    def complete_run(self, *, run_id: str, lease_token: str, evidence: Iterable[Dict[str, Any]] = ()) -> bool:
        now = _now()
        with self._transaction() as connection:
            run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            lease = connection.execute("SELECT * FROM leases WHERE resource_type = 'step' AND resource_id = ?", (run["step_id"],)).fetchone() if run else None
            if run is None or lease is None or lease["lease_token"] != lease_token or lease["expires_at"] <= now or run["status"] != "running":
                return False
            for item in evidence:
                connection.execute("INSERT INTO evidence(evidence_id, task_id, plan_id, step_id, run_id, kind, uri, digest, summary, verified_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (_id("evidence"), run["task_id"], run["plan_id"], run["step_id"], run_id, str(item.get("kind") or "tool_result"), str(item.get("uri") or ""), str(item.get("digest") or ""), str(item.get("summary") or ""), str(item.get("verified_by") or ""), now))
            connection.execute("UPDATE runs SET status = 'succeeded', ended_at = ?, version = version + 1 WHERE run_id = ?", (now, run_id))
            connection.execute("UPDATE steps SET status = 'completed', active_run_id = NULL, completed_at = ?, updated_at = ?, version = version + 1 WHERE step_id = ?", (now, now, run["step_id"]))
            connection.execute("DELETE FROM leases WHERE lease_id = ?", (lease["lease_id"],))
            self._outbox(connection, "run", run_id, "run.completed", {"task_id": run["task_id"], "plan_id": run["plan_id"], "step_id": run["step_id"], "run_id": run_id})
            return True

    def fail_run(self, *, run_id: str, lease_token: str, failure_code: str, failure_detail: str = "") -> bool:
        """Close only the currently owned attempt; stale workers are rejected."""
        now = _now()
        with self._transaction() as connection:
            run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            lease = connection.execute("SELECT * FROM leases WHERE resource_type = 'step' AND resource_id = ?", (run["step_id"],)).fetchone() if run else None
            if run is None or lease is None or lease["lease_token"] != lease_token or run["status"] != "running":
                return False
            connection.execute("UPDATE runs SET status = 'failed', ended_at = ?, failure_code = ?, failure_detail = ?, version = version + 1 WHERE run_id = ?", (now, failure_code[:120], failure_detail[:1000], run_id))
            connection.execute("UPDATE steps SET status = 'failed', active_run_id = NULL, updated_at = ?, version = version + 1 WHERE step_id = ?", (now, run["step_id"]))
            connection.execute("DELETE FROM leases WHERE lease_id = ?", (lease["lease_id"],))
            self._outbox(connection, "run", run_id, "run.failed", {"task_id": run["task_id"], "plan_id": run["plan_id"], "step_id": run["step_id"], "run_id": run_id, "error": failure_detail[:1000]})
            return True

    def pending_outbox(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM outbox WHERE published_at IS NULL ORDER BY sequence LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
            return [dict(row) for row in rows]

    def link_legacy_record(self, *, source_type: str, source_id: str, task_id: str, plan_id: str = "", step_id: str = "", run_id: str = "") -> Dict[str, Any]:
        """Attach a legacy queue/WorkItem record to canonical workflow IDs.

        This is the migration boundary: callers may keep their old storage
        while dispatch and UI gain a reliable canonical identity.
        """
        now = _now()
        with self._transaction() as connection:
            if connection.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
                raise KeyError(f"Task not found: {task_id}")
            connection.execute("""INSERT INTO legacy_links(source_type, source_id, task_id, plan_id, step_id, run_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source_type, source_id) DO UPDATE SET task_id=excluded.task_id, plan_id=excluded.plan_id, step_id=excluded.step_id, run_id=excluded.run_id, updated_at=excluded.updated_at""", (source_type[:80], str(source_id)[:240], task_id, plan_id, step_id, run_id, now, now))
            self._outbox(connection, "task", task_id, "legacy.linked", {"source_type": source_type, "source_id": str(source_id), "task_id": task_id, "plan_id": plan_id, "step_id": step_id, "run_id": run_id})
            return self._row(connection.execute("SELECT * FROM legacy_links WHERE source_type = ? AND source_id = ?", (source_type[:80], str(source_id)[:240])).fetchone()) or {}
