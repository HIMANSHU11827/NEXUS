"""Human-in-the-loop approval broker for Co-Pilot (APPROVE) mode.

Before this existed, PermissionMode.APPROVE was effectively "deny everything":
PermissionSystem.check() returned granted=False with a prompt string that no
surface ever displayed, so the agent silently refused every tool instead of
asking. The GUI shipped the other half of the feature (it renders a
`tool.approval_request` event and POSTs the answer to /api/approve) but there
was no backend piece to connect them.

This module is that missing piece. It is deliberately transport-agnostic: the
loop asks for a decision and awaits it, and any surface (GUI, TUI, CLI,
gateway) resolves it by request id.

Design notes:
  * Waiting is done on an asyncio.Event, so a pending approval never blocks
    the event loop or any other session's work.
  * Every request carries a timeout. A surface that goes away (browser tab
    closed mid-approval) must not strand the run forever, so an expired
    request resolves to a deny rather than hanging.
  * Decisions may arrive before the waiter registers (fast user, or a
    reconnecting client replaying its answer). Answers are therefore recorded
    even when no waiter is present yet, and consumed when the waiter appears.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# A denied decision is the safe default for every failure path below.
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_ALLOW_ALWAYS = "allow_always"

_ALLOW_WORDS = frozenset({"yes", "y", "allow", "approve", "approved", "ok", "true", "1"})
_ALWAYS_WORDS = frozenset({"save", "always", "allow_always", "remember", "trust"})


def normalize_decision(raw: Any) -> str:
    """Map the many spellings a surface may send onto a canonical decision.

    The GUI sends 'yes' | 'no' | 'save'; a CLI may send 'y'/'n'; an automated
    client may send a bool. Anything unrecognised denies, because a garbled
    answer must never be read as consent.
    """
    if isinstance(raw, bool):
        return DECISION_ALLOW if raw else DECISION_DENY
    text = str(raw or "").strip().lower()
    if text in _ALWAYS_WORDS:
        return DECISION_ALLOW_ALWAYS
    if text in _ALLOW_WORDS:
        return DECISION_ALLOW
    return DECISION_DENY


@dataclass
class ApprovalRequest:
    """One outstanding question to a human."""

    request_id: str
    session_id: str
    tool_name: str
    action: str
    reason: str = ""
    turn_id: str = ""
    created_at: float = field(default_factory=time.time)
    timeout_s: float = 300.0

    def to_event(self) -> Dict[str, Any]:
        """Render as the work event the GUI already knows how to display."""
        return {
            "id": self.request_id,
            "event_type": "tool.approval_request",
            "kind": "approval",
            "status": "running",
            "request_id": self.request_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "tool": self.tool_name,
            "action": self.action,
            "title": f"Approve {self.tool_name}?",
            "target": self.action,
            "reason": self.reason,
            "expires_at": self.created_at + self.timeout_s,
        }


class ApprovalBroker:
    """Pairs pending approval requests with decisions from any surface."""

    def __init__(self, store_path: str | None = None, owner_id: str = "") -> None:
        self._lock = threading.RLock()
        self._pending: Dict[str, ApprovalRequest] = {}
        self._events: Dict[str, asyncio.Event] = {}
        self._decisions: Dict[str, str] = {}
        self._store_path = os.path.abspath(store_path) if store_path else ""
        self._owner_id = str(owner_id or f"broker_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        if self._store_path:
            os.makedirs(os.path.dirname(self._store_path), exist_ok=True)
            self._init_store()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._store_path, timeout=30.0)
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

    def _init_store(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    timeout_s REAL NOT NULL,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT '',
                    resolved_at REAL
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, created_at)")

    def _expire_due(self) -> None:
        if not self._store_path:
            return
        now = time.time()
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE approval_requests SET status='expired', decision=?, resolved_at=? "
                "WHERE status='pending' AND created_at + timeout_s <= ?",
                (DECISION_DENY, now, now),
            )

    @staticmethod
    def _request_from_row(row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            request_id=str(row["request_id"]),
            session_id=str(row["session_id"]),
            tool_name=str(row["tool_name"]),
            action=str(row["action"]),
            reason=str(row["reason"] or ""),
            turn_id=str(row["turn_id"] or ""),
            created_at=float(row["created_at"]),
            timeout_s=float(row["timeout_s"]),
        )

    def _stored_row(self, request_id: str) -> sqlite3.Row | None:
        if not self._store_path:
            return None
        self._expire_due()
        with self._lock, self._connection() as connection:
            return connection.execute("SELECT * FROM approval_requests WHERE request_id=?", (request_id,)).fetchone()

    # ── agent side ──────────────────────────────────────────────────────
    def open(
        self,
        session_id: str,
        tool_name: str,
        action: str,
        *,
        reason: str = "",
        turn_id: str = "",
        timeout_s: float = 300.0,
        request_id: str = "",
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            request_id=request_id or f"approval_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            tool_name=tool_name,
            action=action,
            reason=reason,
            turn_id=turn_id,
            timeout_s=max(1.0, float(timeout_s or 300.0)),
        )
        with self._lock:
            if self._store_path:
                row = self._stored_row(request.request_id)
                if row is not None:
                    existing = self._request_from_row(row)
                    self._pending[existing.request_id] = existing
                    self._events.setdefault(existing.request_id, asyncio.Event())
                    if str(row["status"]) != "pending" and row["decision"]:
                        self._decisions[existing.request_id] = str(row["decision"])
                    return existing
            self._pending[request.request_id] = request
            self._events[request.request_id] = asyncio.Event()
            if self._store_path:
                with self._connection() as connection:
                    connection.execute(
                        "INSERT INTO approval_requests(request_id,session_id,tool_name,action,reason,turn_id,created_at,timeout_s,status,decision,owner_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (request.request_id, request.session_id, request.tool_name, request.action, request.reason, request.turn_id, request.created_at, request.timeout_s, "pending", "", self._owner_id),
                    )
        return request

    async def wait(self, request_id: str) -> str:
        """Await a human decision. Returns a canonical decision string.

        Times out into a deny so a lost surface cannot strand the run.
        """
        with self._lock:
            request = self._pending.get(request_id)
            event = self._events.get(request_id)
            early = self._decisions.pop(request_id, None)
            row = self._stored_row(request_id) if self._store_path else None
            if request is None and row is not None:
                request = self._request_from_row(row)
                self._pending[request_id] = request
                event = self._events.setdefault(request_id, asyncio.Event())
                if str(row["status"]) != "pending":
                    early = str(row["decision"] or DECISION_DENY)
        if early is not None:
            self._discard(request_id)
            return early
        if request is None or event is None:
            return DECISION_DENY
        # The local event is the fast path, but it cannot be signalled by a
        # resolver in another process. Poll the durable row at a bounded
        # cadence as well, so a GUI/API worker can resolve an approval owned by
        # a separate runtime process without waiting for the full timeout.
        while True:
            with self._lock:
                decision = self._decisions.pop(request_id, None)
            if decision is not None:
                break
            if self._store_path:
                row = self._stored_row(request_id)
                if row is None:
                    decision = DECISION_DENY
                    break
                if str(row["status"]) != "pending":
                    decision = normalize_decision(row["decision"] or DECISION_DENY)
                    break
            remaining = max(0.0, request.created_at + request.timeout_s - time.time())
            if remaining <= 0:
                if self._store_path:
                    self._expire_due()
                decision = DECISION_DENY
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=min(0.25, remaining))
            except asyncio.TimeoutError:
                continue
        self._discard(request_id)
        return decision or DECISION_DENY

    # ── surface side ────────────────────────────────────────────────────
    def resolve(self, request_id: str, decision: Any) -> bool:
        """Record a human decision. True if it matched a live request.

        Answers that arrive before the agent starts waiting are still kept, so
        a fast click or a client replaying its answer is not lost.
        """
        normalized = normalize_decision(decision)
        if self._store_path:
            self._expire_due()
        with self._lock:
            self._decisions[request_id] = normalized
            event = self._events.get(request_id)
            known = request_id in self._pending
            if self._store_path:
                row = self._stored_row(request_id)
                known = row is not None and str(row["status"]) == "pending"
                if known:
                    with self._connection() as connection:
                        connection.execute(
                            "UPDATE approval_requests SET status='decided', decision=?, owner_id=?, resolved_at=? WHERE request_id=? AND status='pending'",
                            (normalized, self._owner_id, time.time(), request_id),
                        )
                else:
                    self._decisions.pop(request_id, None)
        if event is not None:
            try:
                event.set()
            except RuntimeError:
                pass
        return known

    def pending(self, session_id: str = "") -> list:
        if self._store_path:
            self._expire_due()
            with self._lock, self._connection() as connection:
                rows = connection.execute("SELECT * FROM approval_requests WHERE status='pending' ORDER BY created_at").fetchall()
            requests = [self._request_from_row(row) for row in rows]
            with self._lock:
                for request in requests:
                    self._pending[request.request_id] = request
                    self._events.setdefault(request.request_id, asyncio.Event())
            if session_id:
                requests = [r for r in requests if r.session_id == session_id]
            return [r.to_event() for r in requests]
        with self._lock:
            requests = list(self._pending.values())
        if session_id:
            requests = [r for r in requests if r.session_id == session_id]
        return [r.to_event() for r in requests]

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        if self._store_path:
            row = self._stored_row(request_id)
            if row is None or str(row["status"]) != "pending":
                return None
            request = self._request_from_row(row)
            with self._lock:
                self._pending[request_id] = request
            return request
        with self._lock:
            return self._pending.get(request_id)

    def cancel_session(self, session_id: str) -> int:
        """Deny every outstanding request for a session (stop / disconnect)."""
        if self._store_path:
            self.pending(session_id)
        with self._lock:
            ids = [rid for rid, req in self._pending.items() if req.session_id == session_id]
        for request_id in ids:
            self.resolve(request_id, DECISION_DENY)
        return len(ids)

    def _discard(self, request_id: str) -> None:
        with self._lock:
            self._pending.pop(request_id, None)
            self._events.pop(request_id, None)
            self._decisions.pop(request_id, None)


# One broker per process: the loop and the API routes must share state. The
# global broker additionally persists requests so a backend restart can
# re-render and resolve an outstanding approval instead of losing it.
_BROKER = ApprovalBroker(
    store_path=os.environ.get(
        "NEXUS_APPROVAL_STORE",
        os.path.join(os.getcwd(), ".nexus", "approvals.sqlite3"),
    )
)


def get_approval_broker() -> ApprovalBroker:
    return _BROKER
