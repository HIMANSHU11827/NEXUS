"""Thread-safe, per-run cancellation registry for the V5 loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, RLock
from time import monotonic
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

    def __init__(self) -> None:
        self._lock = RLock()
        self._controls: Dict[str, RunControl] = {}

    def register(self, turn_id: str, deadline_at: Optional[float] = None) -> RunControl:
        key = str(turn_id or "").strip()
        if not key:
            raise ValueError("turn_id is required")
        with self._lock:
            control = self._controls.setdefault(key, RunControl(turn_id=key))
            if deadline_at is not None and control.remaining is None:
                control.set_deadline(deadline_at)
            return control

    def get(self, turn_id: str) -> Optional[RunControl]:
        with self._lock:
            return self._controls.get(str(turn_id or "").strip())

    def request_cancel(self, turn_id: str, reason: str = "user_cancelled") -> bool:
        key = str(turn_id or "").strip()
        if not key:
            return False
        with self._lock:
            control = self._controls.setdefault(key, RunControl(turn_id=key))
            control.request_cancel(reason)
            return True

    def unregister(self, turn_id: str) -> None:
        with self._lock:
            self._controls.pop(str(turn_id or "").strip(), None)
