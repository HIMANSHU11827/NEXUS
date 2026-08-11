"""Thread-safe, per-run cancellation registry for the V5 loop."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import sqlite3
from contextlib import contextmanager
from threading import Event, RLock
from time import monotonic, time
from typing import Dict, Optional


@dataclass
class RunControl:
    turn_id: str
    cancel_event: Event = field(default_factory=Event)
    reason: str = ""
    deadline_at: Optional[float] = None
    _state_lock: RLock = field(
        default_factory=RLock, init=False, repr=False, compare=False
    )

    def request_cancel(self, reason: str = "user_cancelled") -> None:
        # Publish the reason before setting the event while holding the same
        # lock used by deadline updates.  Consumers that observe the event
        # must never see a partially updated control state.
        with self._state_lock:
            self.reason = str(reason or "user_cancelled")[:200]
            self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def set_deadline(self, deadline_at: Optional[float]) -> None:
        with self._state_lock:
            self.deadline_at = (
                float(deadline_at) if deadline_at is not None else None
            )

    @property
    def remaining(self) -> Optional[float]:
        with self._state_lock:
            deadline_at = self.deadline_at
        if deadline_at is None:
            return None
        return max(0.0, deadline_at - monotonic())

    @property
    def timed_out(self) -> bool:
        return self.deadline_at is not None and self.remaining <= 0


class RunControlRegistry:
    """Small in-process registry; pending requests survive generator startup."""

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._lock = RLock()
        self._controls: Dict[str, RunControl] = {}
        self._store_path = os.path.abspath(store_path) if store_path else ""
        if self._store_path:
            os.makedirs(os.path.dirname(self._store_path), exist_ok=True)
            with self._connection() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS run_cancellations ("
                    "turn_id TEXT PRIMARY KEY, reason TEXT NOT NULL, requested_at REAL NOT NULL)"
                )

    @contextmanager
    def _connection(self):
        """Open, commit/rollback, and always close the optional SQLite store."""
        if not self._store_path:
            raise RuntimeError("durable run-control storage is disabled")
        connection = sqlite3.connect(self._store_path, timeout=30.0)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _persist_cancel(self, turn_id: str, reason: str) -> None:
        if not self._store_path:
            return
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO run_cancellations(turn_id, reason, requested_at) VALUES (?, ?, ?) "
                "ON CONFLICT(turn_id) DO UPDATE SET reason=excluded.reason, requested_at=excluded.requested_at",
                (str(turn_id), str(reason), time()),
            )

    def _load_cancel(self, turn_id: str) -> str:
        if not self._store_path:
            return ""
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT reason FROM run_cancellations WHERE turn_id=?", (str(turn_id),)
                ).fetchone()
            return str(row[0]) if row else ""
        except (OSError, sqlite3.Error):
            return ""

    def register(self, turn_id: str, deadline_at: Optional[float] = None) -> RunControl:
        key = str(turn_id or "").strip()
        if not key:
            raise ValueError("turn_id is required")
        with self._lock:
            control = self._controls.setdefault(key, RunControl(turn_id=key))
            persisted_reason = self._load_cancel(key)
            if persisted_reason and not control.cancelled:
                control.request_cancel(persisted_reason)
            if deadline_at is not None and control.remaining is None:
                control.set_deadline(deadline_at)
            return control

    def get(self, turn_id: str) -> Optional[RunControl]:
        with self._lock:
            return self._controls.get(str(turn_id or "").strip())

    def refresh_cancel(self, turn_id: str) -> bool:
        """Import a durable cancellation into an already-running process.

        Registration loads cancellations that happened before a run started,
        but another API/runtime process may request cancellation after the
        control object is already registered.  Refresh is intentionally
        read-only with respect to SQLite and safe to call at cooperative abort
        checkpoints.
        """
        key = str(turn_id or "").strip()
        if not key or not self._store_path:
            return False
        with self._lock:
            control = self._controls.get(key)
            if control is None or control.cancelled:
                return bool(control and control.cancelled)
            reason = self._load_cancel(key)
            if not reason:
                return False
            control.request_cancel(reason)
            return True

    def request_cancel(self, turn_id: str, reason: str = "user_cancelled") -> bool:
        key = str(turn_id or "").strip()
        if not key:
            return False
        with self._lock:
            control = self._controls.setdefault(key, RunControl(turn_id=key))
            control.request_cancel(reason)
            try:
                self._persist_cancel(key, control.reason)
            except (OSError, sqlite3.Error):
                # Cancellation remains valid in memory even if the optional
                # durability store is temporarily unavailable.
                pass
            return True

    def unregister(self, turn_id: str) -> None:
        with self._lock:
            key = str(turn_id or "").strip()
            self._controls.pop(key, None)
            if self._store_path and key:
                try:
                    with self._connection() as connection:
                        connection.execute("DELETE FROM run_cancellations WHERE turn_id=?", (key,))
                except (OSError, sqlite3.Error):
                    pass
