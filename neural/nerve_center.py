"""Durable feedback ledger for Nexus routing/evolution signals.

This component intentionally records reinforcement; it does not claim to
perform online RL or mutate model weights.  Consumers can use the aggregate
scores as an auditable input to later training or routing decisions.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, Optional

from providers.reliability import redact_secrets

logger = logging.getLogger("NEXUS_NERVE")


class NexusNerveCenter:
    def __init__(self, root: str):
        self.root = os.path.abspath(root or ".")
        self.db_path = os.path.join(self.root, ".nexus", "neural_feedback.sqlite3")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reinforcement (
                    task_type TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    total_delta REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (task_type, tool_name)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mutations (
                    mutation_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _label(value: Any, fallback: str) -> str:
        text = str(value or fallback).strip()
        return text[:200] or fallback

    def reinforce(self, task_type: str, tool_name: str, delta: float) -> bool:
        """Persist one bounded reward signal; return whether it was accepted."""
        try:
            score = float(delta)
            if not math.isfinite(score) or abs(score) > 100.0:
                return False
            task = self._label(task_type, "unknown")
            tool = self._label(tool_name, "unknown")
            now = time.time()
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO reinforcement(task_type, tool_name, count, total_delta, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(task_type, tool_name) DO UPDATE SET
                        count = reinforcement.count + 1,
                        total_delta = reinforcement.total_delta + excluded.total_delta,
                        updated_at = excluded.updated_at
                    """ ,
                    (task, tool, score, now),
                )
            return True
        except Exception:
            logger.warning("NexusNerveCenter.reinforce failed", exc_info=True)
            return False

    def log_mutation(self, mutation: dict) -> bool:
        """Persist a redacted, bounded evolution mutation record."""
        if not isinstance(mutation, dict):
            return False
        try:
            payload = redact_secrets(json.dumps(mutation, ensure_ascii=False, default=str))[:8000]
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO mutations(mutation_id, payload, created_at) VALUES (?, ?, ?)",
                    (uuid.uuid4().hex, payload, time.time()),
                )
            return True
        except Exception:
            logger.warning("NexusNerveCenter.log_mutation failed", exc_info=True)
            return False

    def snapshot(self, limit: int = 100) -> Dict[str, Any]:
        """Return bounded aggregate feedback for diagnostics/training input."""
        try:
            size = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            size = 100
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT task_type, tool_name, count, total_delta, updated_at "
                    "FROM reinforcement ORDER BY updated_at DESC LIMIT ?",
                    (size,),
                ).fetchall()
                mutation_count = connection.execute("SELECT COUNT(*) FROM mutations").fetchone()[0]
            return {
                "reinforcement": [dict(row) for row in rows],
                "mutation_count": int(mutation_count),
                "model_training": "not_implemented",
            }
        except Exception:
            logger.warning("NexusNerveCenter.snapshot failed", exc_info=True)
            return {"reinforcement": [], "mutation_count": 0, "model_training": "unavailable"}


__all__ = ["NexusNerveCenter"]
