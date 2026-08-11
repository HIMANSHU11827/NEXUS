"""Bounded durable verifier event history for V5."""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from providers.reliability import redact_secrets


class VerifierEventStore:
    """SQLite event history kept separate from the latest verifier state."""

    def __init__(self, path: Optional[os.PathLike[str] | str] = None,
                 *, retention_seconds: float = 30 * 24 * 60 * 60,
                 max_events: int = 256) -> None:
        self.path = Path(path) if path is not None else Path.cwd() / ".nexus_v5" / "verifier_events.sqlite3"
        self.retention_seconds = max(60.0, float(retention_seconds))
        self.max_events = max(1, int(max_events))

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS verification_events (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                root TEXT NOT NULL,
                created_at REAL NOT NULL,
                verifier_id TEXT NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                command TEXT NOT NULL,
                canonical_command TEXT NOT NULL,
                kind TEXT NOT NULL,
                scope TEXT NOT NULL,
                exit_code INTEGER,
                output_summary TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(verification_events)")}
        if "run_id" not in columns:
            connection.execute("ALTER TABLE verification_events ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
        if "phase" not in columns:
            connection.execute("ALTER TABLE verification_events ADD COLUMN phase TEXT NOT NULL DEFAULT ''")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_verification_events_scope "
            "ON verification_events(session_id, root, created_at DESC)"
        )
        connection.commit()
        return connection

    @staticmethod
    def _text(value: Any, limit: int) -> str:
        return redact_secrets(str(value or "")).replace("\x00", "")[:limit]

    def _prune(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            "DELETE FROM verification_events WHERE created_at < ?",
            (now - self.retention_seconds,),
        )
        rows = connection.execute(
            "SELECT event_id FROM verification_events ORDER BY created_at DESC LIMIT -1 OFFSET ?",
            (self.max_events,),
        ).fetchall()
        if rows:
            connection.executemany("DELETE FROM verification_events WHERE event_id = ?", rows)

    def record(
        self, session_id: str, root: str, *, verifier_id: str,
        run_id: str = "", phase: str = "",
        status: str, command: str = "", canonical_command: str = "",
        kind: str = "tool_evidence", scope: str = "targeted",
        exit_code: Optional[int] = None, output_summary: str = "",
        created_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        event = {
            "event_id": f"ve_{uuid.uuid4().hex[:24]}",
            "session_id": self._text(session_id, 256) or "default",
            "root": self._text(Path(root).resolve(), 1024),
            "created_at": float(created_at or time.time()),
            "verifier_id": self._text(verifier_id, 128),
            "run_id": self._text(run_id, 128),
            "phase": self._text(phase, 40),
            "status": self._text(status, 24),
            "command": self._text(command, 500),
            "canonical_command": self._text(canonical_command or command, 500),
            "kind": self._text(kind, 64),
            "scope": self._text(scope, 40),
            "exit_code": int(exit_code) if isinstance(exit_code, int) else None,
            "output_summary": self._text(output_summary, 1500),
        }
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO verification_events
                (event_id, session_id, root, created_at, verifier_id, run_id, phase, status,
                 command, canonical_command, kind, scope, exit_code, output_summary)
                VALUES (:event_id, :session_id, :root, :created_at, :verifier_id,
                        :run_id, :phase, :status, :command, :canonical_command, :kind, :scope,
                        :exit_code, :output_summary)""", event,
            )
            self._prune(connection, event["created_at"])
        return event

    def list_events(self, session_id: str, root: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        cap = max(1, min(int(limit), self.max_events))
        normalized_root = str(Path(root).resolve())
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT event_id, session_id, root, created_at, verifier_id,
                   run_id, phase, status, command, canonical_command, kind, scope, exit_code,
                   output_summary FROM verification_events
                   WHERE session_id = ? AND root = ? ORDER BY created_at DESC LIMIT ?""",
                (self._text(session_id, 256) or "default", normalized_root, cap),
            ).fetchall()
        fields = ("event_id", "session_id", "root", "created_at", "verifier_id",
                  "run_id", "phase", "status", "command", "canonical_command", "kind", "scope",
                  "exit_code", "output_summary")
        return [dict(zip(fields, row)) for row in rows]


__all__ = ["VerifierEventStore"]
