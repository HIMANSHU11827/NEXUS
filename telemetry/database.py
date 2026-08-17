"""Append-only SQLite telemetry store for NEXUS tool/error records.

Records are immutable (insert-only); query() reads them back.  The database
lives under the NEXUS home data dir by default and the parent directory is
created on first use.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NEXUS_TELEMETRY")

try:
    from providers.reliability import redact_secrets
except Exception:  # pragma: no cover - defensive fallback
    def redact_secrets(text: Any) -> str:  # type: ignore[misc]
        return "" if text is None else str(text)


def _default_db_path() -> str:
    """Resolve the telemetry database path (env override or NEXUS home)."""
    explicit = os.environ.get("NEXUS_TELEMETRY_DB")
    if explicit:
        return os.path.abspath(explicit)
    try:
        from utils.nexus_path import get_nexus_home

        base = str(get_nexus_home())
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".nexus")
    return os.path.join(base, "telemetry.sqlite3")


def _bounded(value: Any, limit: int = 8000) -> str:
    """Coerce a value to a bounded string suitable for storage."""
    if value is None:
        return ""
    text = str(value)
    return text[:limit]


class NexusTelemetryDB:
    """Append-only SQLite store for tool calls and errors.

    Public surface (kept compatible with existing imports):

    - log_tool_call(tool, params, result, duration)
    - log_error(error, context)
    - query(...) plus convenience readers and stats()
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = os.path.abspath(db_path) if db_path else _default_db_path()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        logger.info("NexusTelemetryDB ready at %s", self.db_path)

    # ------------------------------------------------------------------ internals

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool TEXT NOT NULL,
                    params TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL DEFAULT '',
                    duration REAL NOT NULL DEFAULT 0.0,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _json(value: Any) -> str:
        """Serialize a mapping/list to JSON (or an empty string)."""
        if value is None:
            return ""
        try:
            if isinstance(value, (dict, list, tuple)):
                return json.dumps(value, ensure_ascii=False, default=str)
            return _bounded(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return _bounded(value)

    # ------------------------------------------------------------------ writers

    def log_tool_call(self, tool: str, params: dict, result: str, duration: float):
        """Persist one tool-call record (append-only)."""
        try:
            tool_name = _bounded(redact_secrets(tool), 200) or "unknown"
            params_text = _bounded(redact_secrets(self._json(params)), 8000)
            result_text = _bounded(redact_secrets(result), 8000)
            try:
                duration_ms = max(0.0, float(duration))
            except (TypeError, ValueError):
                duration_ms = 0.0
            with self._lock, self._connect() as connection:
                connection.execute(
                    "INSERT INTO tool_calls(tool, params, result, duration, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (tool_name, params_text, result_text, duration_ms, time.time()),
                )
        except Exception:
            logger.warning("NexusTelemetryDB.log_tool_call failed", exc_info=True)

    def log_error(self, error: str, context: dict):
        """Persist one error record (append-only)."""
        try:
            error_text = _bounded(redact_secrets(error), 4000) or "unknown error"
            context_text = _bounded(redact_secrets(self._json(context)), 8000)
            with self._lock, self._connect() as connection:
                connection.execute(
                    "INSERT INTO errors(error, context, created_at) VALUES (?, ?, ?)",
                    (error_text, context_text, time.time()),
                )
        except Exception:
            logger.warning("NexusTelemetryDB.log_error failed", exc_info=True)

    # ------------------------------------------------------------------ readers

    def query(
        self, kind: str = "tool_calls", limit: int = 100,
        since: Optional[float] = None, tool: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent records.

        kind is "tool_calls" (default) or "errors".  since is an epoch timestamp
        used to filter created_at >= since; tool filters tool-call records by
        exact tool name.
        """
        table = kind if kind in ("tool_calls", "errors") else "tool_calls"
        try:
            size = max(1, min(int(limit), 5000))
        except (TypeError, ValueError):
            size = 100
        clauses: List[str] = []
        params: List[Any] = []
        if since is not None:
            try:
                clauses.append("created_at >= ?")
                params.append(float(since))
            except (TypeError, ValueError):
                pass
        if table == "tool_calls" and tool:
            clauses.append("tool = ?")
            params.append(_bounded(str(tool), 200))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(size)
        try:
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    f"SELECT * FROM {table}{where} ORDER BY id DESC LIMIT ?", params
                ).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.warning("NexusTelemetryDB.query failed", exc_info=True)
            return []

    def recent_tool_calls(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent tool-call records."""
        return self.query(kind="tool_calls", limit=limit)

    def recent_errors(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent error records."""
        return self.query(kind="errors", limit=limit)

    def stats(self) -> Dict[str, Any]:
        """Return storage stats: record counts and database size."""
        try:
            with self._lock, self._connect() as connection:
                tool_count = connection.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
                error_count = connection.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
            size_bytes = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            return {
                "tool_calls": int(tool_count),
                "errors": int(error_count),
                "db_path": self.db_path,
                "size_bytes": int(size_bytes),
                "append_only": True,
            }
        except Exception:
            logger.warning("NexusTelemetryDB.stats failed", exc_info=True)
            return {"tool_calls": 0, "errors": 0, "db_path": self.db_path, "size_bytes": 0, "append_only": True}


__all__ = ["NexusTelemetryDB"]
