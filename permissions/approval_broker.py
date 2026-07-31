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
import threading
import time
import uuid
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

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: Dict[str, ApprovalRequest] = {}
        self._events: Dict[str, asyncio.Event] = {}
        self._decisions: Dict[str, str] = {}

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
            self._pending[request.request_id] = request
            self._events[request.request_id] = asyncio.Event()
        return request

    async def wait(self, request_id: str) -> str:
        """Await a human decision. Returns a canonical decision string.

        Times out into a deny so a lost surface cannot strand the run.
        """
        with self._lock:
            request = self._pending.get(request_id)
            event = self._events.get(request_id)
            early = self._decisions.pop(request_id, None)
        if early is not None:
            self._discard(request_id)
            return early
        if request is None or event is None:
            return DECISION_DENY
        try:
            await asyncio.wait_for(event.wait(), timeout=request.timeout_s)
        except asyncio.TimeoutError:
            self._discard(request_id)
            return DECISION_DENY
        with self._lock:
            decision = self._decisions.pop(request_id, DECISION_DENY)
        self._discard(request_id)
        return decision

    # ── surface side ────────────────────────────────────────────────────
    def resolve(self, request_id: str, decision: Any) -> bool:
        """Record a human decision. True if it matched a live request.

        Answers that arrive before the agent starts waiting are still kept, so
        a fast click or a client replaying its answer is not lost.
        """
        normalized = normalize_decision(decision)
        with self._lock:
            self._decisions[request_id] = normalized
            event = self._events.get(request_id)
            known = request_id in self._pending
        if event is not None:
            try:
                event.set()
            except RuntimeError:
                pass
        return known

    def pending(self, session_id: str = "") -> list:
        with self._lock:
            requests = list(self._pending.values())
        if session_id:
            requests = [r for r in requests if r.session_id == session_id]
        return [r.to_event() for r in requests]

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        with self._lock:
            return self._pending.get(request_id)

    def cancel_session(self, session_id: str) -> int:
        """Deny every outstanding request for a session (stop / disconnect)."""
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


# One broker per process: the loop and the API routes must share state.
_BROKER = ApprovalBroker()


def get_approval_broker() -> ApprovalBroker:
    return _BROKER
