"""Durable Hive blackboard and artifact manifest storage."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List


class HiveStateConflict(RuntimeError):
    """Raised when an optimistic blackboard write observes a stale version."""


class HiveStateStore:
    """SQLite-backed shared state for Hive coordination and artifacts."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root or os.getcwd())
        self._resolved_root = os.path.realpath(self.root)
        self.path = os.path.join(self.root, ".nexus", "hive_state.sqlite3")
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS blackboard (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    writer TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    hive_id TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL DEFAULT '',
                    size INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_hive ON artifacts(hive_id, updated_at)")

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

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def put_blackboard(
        self,
        key: str,
        value: Any,
        *,
        expected_version: int | None = None,
        writer: str = "",
    ) -> Dict[str, Any]:
        name = str(key or "").strip()
        if not name:
            raise ValueError("blackboard key must not be empty")
        now = time.time()
        encoded = self._json(value)
        with self._lock, self._connection() as connection:
            # Acquire the SQLite write lock before reading the current version.
            # A deferred transaction can let two processes observe the same
            # version and turn an optimistic conflict into a lost update or a
            # generic "database is locked" error.
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT version FROM blackboard WHERE key=?", (name,)).fetchone()
            current = int(row["version"]) if row else 0
            if expected_version is not None and current != int(expected_version):
                raise HiveStateConflict(f"blackboard key {name!r} changed: expected {expected_version}, found {current}")
            version = current + 1
            connection.execute(
                "INSERT INTO blackboard(key,value_json,version,writer,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,version=excluded.version,writer=excluded.writer,updated_at=excluded.updated_at",
                (name, encoded, version, str(writer or ""), now),
            )
        return {"key": name, "value": value, "version": version, "writer": str(writer or ""), "updated_at": now}

    def get_blackboard(self) -> Dict[str, Any]:
        with self._lock, self._connection() as connection:
            rows = connection.execute("SELECT key,value_json,version,writer,updated_at FROM blackboard ORDER BY key").fetchall()
        result: Dict[str, Any] = {}
        for row in rows:
            try:
                value = json.loads(row["value_json"])
            except (TypeError, json.JSONDecodeError):
                value = row["value_json"]
            result[str(row["key"])] = {
                "value": value,
                "version": int(row["version"]),
                "writer": str(row["writer"] or ""),
                "updated_at": float(row["updated_at"] or 0),
            }
        return result

    def register_artifact(
        self,
        path: str,
        *,
        artifact_id: str = "",
        hive_id: str = "",
        agent_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        absolute = os.path.abspath(str(path or ""))
        try:
            resolved = os.path.realpath(absolute)
            if os.path.commonpath([self._resolved_root, resolved]) != self._resolved_root:
                raise ValueError("artifact path must remain within the Hive root")
        except ValueError:
            raise ValueError("artifact path must remain within the Hive root") from None
        identifier = str(artifact_id or hashlib.sha256(absolute.encode("utf-8")).hexdigest()[:20])
        fingerprint = self._fingerprint(absolute)
        now = time.time()
        with self._lock, self._connection() as connection:
            prior = connection.execute("SELECT version FROM artifacts WHERE artifact_id=?", (identifier,)).fetchone()
            version = int(prior["version"]) + 1 if prior else 1
            connection.execute(
                "INSERT INTO artifacts(artifact_id,hive_id,agent_id,path,sha256,size,status,metadata_json,version,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(artifact_id) DO UPDATE SET hive_id=excluded.hive_id,agent_id=excluded.agent_id,path=excluded.path,sha256=excluded.sha256,size=excluded.size,status=excluded.status,metadata_json=excluded.metadata_json,version=excluded.version,updated_at=excluded.updated_at",
                (identifier, str(hive_id or ""), str(agent_id or ""), absolute, fingerprint["sha256"], fingerprint["size"], fingerprint["status"], self._json(metadata or {}), version, now),
            )
        return self.get_artifact(identifier) or {}

    def reconcile_artifacts(self, hive_id: str = "") -> List[Dict[str, Any]]:
        with self._lock, self._connection() as connection:
            if hive_id:
                rows = connection.execute("SELECT * FROM artifacts WHERE hive_id=? ORDER BY updated_at", (str(hive_id),)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM artifacts ORDER BY updated_at").fetchall()
        result = []
        for row in rows:
            current = self._fingerprint(str(row["path"]))
            expected = {"sha256": str(row["sha256"] or ""), "size": int(row["size"] or 0)}
            if current["status"] == "missing":
                status = "missing"
            elif current["sha256"] == expected["sha256"] and current["size"] == expected["size"]:
                status = "present"
            else:
                status = "changed"
            item = dict(row)
            item["status"] = status
            item["current_sha256"] = current["sha256"]
            item["current_size"] = current["size"]
            result.append(item)
        return result

    def get_artifact(self, artifact_id: str) -> Dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM artifacts WHERE artifact_id=?", (str(artifact_id),)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _fingerprint(path: str) -> Dict[str, Any]:
        try:
            size = os.path.getsize(path)
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return {"status": "present", "sha256": digest.hexdigest(), "size": size}
        except (FileNotFoundError, OSError, PermissionError):
            return {"status": "missing", "sha256": "", "size": 0}
