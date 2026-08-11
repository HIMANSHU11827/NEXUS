"""Durable idempotency ledger for Hive tool effects."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple


class HiveEffectLedger:
    """Record tool-effect ownership and results across retries/restarts."""

    def __init__(self, root: str, db_path: Optional[str] = None, lease_seconds: float = 300.0):
        self.db_path = os.path.abspath(db_path or os.path.join(root, ".nexus", "hive_effects.sqlite3"))
        self.lease_seconds = max(1.0, float(lease_seconds))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS effects (
                    effect_key TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    lease_until REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    @staticmethod
    def key(agent_id: str, task: str, step: int, tool: str, params: Dict[str, Any]) -> str:
        raw = json.dumps([agent_id, task, int(step), tool, params], sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def claim(self, effect_key: str, agent_id: str, tool: str) -> Tuple[str, str]:
        """Return ``(execute|replay|uncertain, result_or_message)``."""
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status, result, lease_until FROM effects WHERE effect_key = ?",
                (effect_key,),
            ).fetchone()
            if row and row[0] == "succeeded":
                conn.commit()
                return "replay", str(row[1])
            if row and row[0] == "running" and float(row[2]) > now:
                conn.commit()
                return "uncertain", "effect is already in-flight; refusing duplicate execution"
            conn.execute(
                "INSERT OR REPLACE INTO effects(effect_key,agent_id,tool,status,result,error,lease_until,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (effect_key, str(agent_id), str(tool), "running", "", "", now + self.lease_seconds, now),
            )
            conn.commit()
        return "execute", ""

    def complete(self, effect_key: str, result: Any) -> None:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE effects SET status='succeeded', result=?, error='', lease_until=?, updated_at=? WHERE effect_key=?",
                (str(result), now, now, effect_key),
            )
            conn.commit()

    def fail(self, effect_key: str, error: str) -> None:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE effects SET status='failed', error=?, lease_until=?, updated_at=? WHERE effect_key=?",
                (str(error)[:1000], now, now, effect_key),
            )
            conn.commit()


__all__ = ["HiveEffectLedger"]
