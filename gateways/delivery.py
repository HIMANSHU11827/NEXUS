"""Durable at-least-once outbound gateway delivery ledger.

The ledger closes the crash window between producing a response and sending it
to a platform. It intentionally promises at-least-once delivery: a process can
crash after an external platform accepts a message but before the ledger is
acknowledged, so platform-side idempotency should be used where available.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional


def _now() -> float:
    return time.time()


class DeliveryLedger:
    """SQLite-backed outbound message ledger with expiring publisher leases."""

    def __init__(self, root: Optional[str] = None, db_path: Optional[str] = None):
        project_root = os.path.abspath(root or os.environ.get("NEXUS_ROOT") or os.getcwd())
        self.db_path = os.path.abspath(db_path or os.path.join(project_root, ".nexus", "gateway_delivery.sqlite3"))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    reply_to TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_until REAL,
                    message_id TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    sent_at REAL
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_ready ON deliveries(status, lease_until, created_at)")

    def enqueue(self, *, idempotency_key: str, platform: str, chat_id: str, text: str, reply_to: str = "") -> Dict[str, Any]:
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key is required")
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM deliveries WHERE idempotency_key = ?", (key,)).fetchone()
            if existing is not None:
                return dict(existing)
            delivery_id = f"delivery_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO deliveries(delivery_id,idempotency_key,platform,chat_id,text,reply_to,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (delivery_id, key, str(platform), str(chat_id), str(text), str(reply_to or ""), now, now),
            )
            row = conn.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
            return dict(row)

    def claim(self, owner: str, *, limit: int = 100, lease_seconds: float = 60.0, platforms: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        now = _now()
        until = now + max(1.0, float(lease_seconds))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            args: List[Any] = [now]
            platform_clause = ""
            if platforms:
                placeholders = ",".join("?" for _ in platforms)
                platform_clause = f" AND platform IN ({placeholders})"
                args.extend(str(item) for item in platforms)
            args.append(max(1, min(int(limit), 1000)))
            rows = conn.execute(
                f"SELECT delivery_id FROM deliveries WHERE status IN ('pending','retrying','leased') AND (lease_until IS NULL OR lease_until <= ?){platform_clause} ORDER BY created_at LIMIT ?",
                tuple(args),
            ).fetchall()
            claimed = []
            for row in rows:
                cur = conn.execute(
                    "UPDATE deliveries SET status='leased', attempts=attempts+1, lease_owner=?, lease_until=?, updated_at=? WHERE delivery_id=? AND status IN ('pending','retrying','leased') AND (lease_until IS NULL OR lease_until <= ?)",
                    (str(owner), until, now, row["delivery_id"], now),
                )
                if cur.rowcount:
                    item = conn.execute("SELECT * FROM deliveries WHERE delivery_id = ?", (row["delivery_id"],)).fetchone()
                    claimed.append(dict(item))
            return claimed

    def ack(self, delivery_id: str, owner: str, message_id: str = "") -> bool:
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE deliveries SET status='sent', message_id=?, sent_at=?, updated_at=?, lease_owner='', lease_until=NULL "
                "WHERE delivery_id=? AND status='leased' AND lease_owner=? AND lease_until > ?",
                (str(message_id or ""), now, now, str(delivery_id), str(owner), now),
            )
            return cur.rowcount > 0

    def renew(self, delivery_id: str, owner: str, *, lease_seconds: float = 60.0) -> bool:
        """Extend an active publisher lease without changing its ownership.

        The compare-and-update guard prevents a stale heartbeat from reviving
        a delivery that another worker reclaimed after the original lease
        expired.
        """
        now = _now()
        until = now + max(1.0, float(lease_seconds))
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE deliveries SET lease_until=?, updated_at=? "
                "WHERE delivery_id=? AND status='leased' AND lease_owner=? AND lease_until > ?",
                (until, now, str(delivery_id), str(owner), now),
            )
            return cur.rowcount > 0

    def fail(self, delivery_id: str, owner: str, error: str, *, max_attempts: int = 8) -> bool:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM deliveries WHERE delivery_id=? AND status='leased' "
                "AND lease_owner=? AND lease_until > ?",
                (str(delivery_id), str(owner), now),
            ).fetchone()
            if row is None:
                return False
            status = "failed" if int(row["attempts"]) >= max(1, int(max_attempts)) else "retrying"
            cur = conn.execute(
                "UPDATE deliveries SET status=?, last_error=?, updated_at=?, lease_owner='', lease_until=NULL "
                "WHERE delivery_id=? AND status='leased' AND lease_owner=? AND lease_until > ?",
                (status, str(error)[:1000], now, str(delivery_id), str(owner), now),
            )
            return cur.rowcount > 0

    def get(self, delivery_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM deliveries WHERE delivery_id=?", (str(delivery_id),)).fetchone()
            return dict(row) if row else None

    def pending(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM deliveries WHERE status IN ('pending','retrying') ORDER BY created_at LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
            return [dict(row) for row in rows]
