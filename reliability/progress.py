"""Progress tracking and loop-stall detection.

Detects: wall-clock idleness (no meaningful progress since T), repeated
identical tool calls, repeated identical error signatures, and plan
oscillation. The tracker is time-injectable for deterministic tests and
optionally persisted so a restart can reconstruct progress state.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nexus.reliability.progress")

_PROGRESS_KINDS = {"state_change", "artifact", "evidence", "progress", "recovery"}
_SUCCESS_KINDS = {"tool_call", "subagent", "model_call"}

# Repeated identical tool calls beyond this many are a stall signal.
REPEAT_CALL_THRESHOLD = 4
# Repeated identical error signatures beyond this many are a stall signal.
REPEAT_ERROR_THRESHOLD = 4
# Consecutive context compactions without verified progress are a stall
# signal (the compaction-loop guard; mirrors OpenClaw's post-compaction
# loop guard).
DEFAULT_CONTEXT_EXHAUSTION_LIMIT = 3


def _context_exhaustion_limit() -> int:
    try:
        return max(1, int(os.environ.get("NEXUS_CONTEXT_EXHAUSTION_LIMIT", "3") or 3))
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT_EXHAUSTION_LIMIT


@dataclass
class StallSignal:
    kind: str  # idle | repeated_tool_call | repeated_error
    detail: str
    since: float
    recent_events: List[Dict[str, Any]] = field(default_factory=list)


class ProgressTracker:
    """Tracks meaningful progress signals and reports stall conditions."""

    def __init__(
        self,
        *,
        max_idle_s: float = 300.0,
        event_window: int = 100,
        persist_path: Optional[str] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        self._max_idle_s = max(1.0, float(max_idle_s))
        self._event_window = max(10, int(event_window))
        self._persist_path = persist_path
        self._clock = clock or time.time
        self._events: List[Dict[str, Any]] = []
        self._last_progress_at: Optional[float] = None
        self._call_signatures: Dict[str, int] = {}
        self._error_signatures: Dict[str, int] = {}
        self._context_exhaustions: int = 0
        self._context_exhaustion_limit: int = _context_exhaustion_limit()
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------ #
    # recording
    # ------------------------------------------------------------------ #

    def record(self, event: Dict[str, Any]) -> None:
        """Record one progress-relevant event.

        Event dict must carry ``kind`` (state_change | artifact | tool_call |
        error | evidence | plan | progress | recovery | subagent |
        model_call) and optionally ``signature``, ``status``, ``id``.
        Unknown kinds are ignored.
        """
        if not isinstance(event, dict):
            return
        kind = str(event.get("kind") or "")
        if not kind:
            return
        self._events.append(dict(event))
        if len(self._events) > self._event_window:
            self._events = self._events[-self._event_window:]

        now = self._clock()
        if kind in _PROGRESS_KINDS:
            self._last_progress_at = now
            self._context_exhaustions = 0
            self._dirty = True
            return

        signature = str(event.get("signature") or "")
        status = str(event.get("status") or "")
        if kind in _SUCCESS_KINDS:
            if status == "success" and signature:
                if signature not in self._call_signatures:
                    self._last_progress_at = now
                    self._dirty = True
                self._call_signatures[signature] = (
                    self._call_signatures.get(signature, 0) + 1
                )
                # Verified tool/model success is real progress: a compaction
                # loop that compacted just before a success is not a loop.
                self._context_exhaustions = 0
            elif signature:
                self._call_signatures[signature] = (
                    self._call_signatures.get(signature, 0) + 1
                )
        elif kind == "error":
            if signature:
                self._error_signatures[signature] = (
                    self._error_signatures.get(signature, 0) + 1
                )
        elif kind == "compaction":
            # A context compaction is a stall symptom, not progress: repeated
            # compactions without verified progress in between mean the agent
            # is compacting and re-running the same work (compaction loop).
            self._context_exhaustions += 1
            self._dirty = True
        elif kind == "plan":
            self._dirty = True

        if self._dirty:
            self._persist()

    # ------------------------------------------------------------------ #
    # inspection
    # ------------------------------------------------------------------ #

    def last_progress(self) -> Optional[float]:
        return self._last_progress_at

    def event_count(self) -> int:
        return len(self._events)

    def recent_events(self, limit: int = 5) -> List[Dict[str, Any]]:
        return list(self._events[-limit:])

    def check(self) -> Optional[StallSignal]:
        """Return a stall signal when progress has stalled, or None."""
        now = self._clock()

        for signature, count in sorted(
            self._error_signatures.items(), key=lambda item: -item[1]
        ):
            if count >= REPEAT_ERROR_THRESHOLD:
                return StallSignal(
                    kind="repeated_error",
                    detail=(
                        f"error signature {signature[:120]} repeated {count} times"
                    ),
                    since=now,
                    recent_events=self.recent_events(),
                )

        for signature, count in sorted(
            self._call_signatures.items(), key=lambda item: -item[1]
        ):
            if count >= REPEAT_CALL_THRESHOLD:
                return StallSignal(
                    kind="repeated_tool_call",
                    detail=(
                        f"identical call signature {signature[:120]} executed "
                        f"{count} times without a state change"
                    ),
                    since=now,
                    recent_events=self.recent_events(),
                )

        if self._context_exhaustions >= self._context_exhaustion_limit:
            return StallSignal(
                kind="context_exhaustion",
                detail=(
                    f"context compacted {self._context_exhaustions} times "
                    f"without verified progress (limit "
                    f"{self._context_exhaustion_limit})"
                ),
                since=now,
                recent_events=self.recent_events(),
            )

        if self._last_progress_at is None:
            return None
        idle = now - self._last_progress_at
        if idle > self._max_idle_s:
            return StallSignal(
                kind="idle",
                detail=(
                    f"no meaningful progress for {idle:.0f}s "
                    f"(limit {self._max_idle_s:g}s)"
                ),
                since=self._last_progress_at,
                recent_events=self.recent_events(),
            )
        return None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        self._events = []
        self._call_signatures = {}
        self._error_signatures = {}
        self._context_exhaustions = 0
        self._last_progress_at = None
        self._dirty = False
        self._persist()

    def mark_progress(self) -> None:
        self._last_progress_at = self._clock()
        self._context_exhaustions = 0
        self._dirty = True
        self._persist()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "events": list(self._events),
            "call_signatures": dict(self._call_signatures),
            "error_signatures": dict(self._error_signatures),
            "context_exhaustions": int(self._context_exhaustions),
            "last_progress_at": self._last_progress_at,
        }

    def restore(self, snapshot: Dict[str, Any]) -> None:
        if not isinstance(snapshot, dict):
            return
        self._events = [dict(item) for item in (snapshot.get("events") or [])]
        self._call_signatures = {
            str(key): int(value)
            for key, value in (snapshot.get("call_signatures") or {}).items()
        }
        self._error_signatures = {
            str(key): int(value)
            for key, value in (snapshot.get("error_signatures") or {}).items()
        }
        self._context_exhaustions = max(
            0, int(snapshot.get("context_exhaustions") or 0)
        )
        self._last_progress_at = snapshot.get("last_progress_at")

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #

    def _persist(self) -> None:
        path = self._persist_path
        if not path:
            return
        try:
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(
                prefix=".progress-", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.snapshot(), handle, default=str)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, path)
            except Exception:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
        except Exception:
            logger.warning("could not persist progress state at %s", path, exc_info=True)

    def _load(self) -> None:
        path = self._persist_path
        if not path:
            return
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    self.restore(json.load(handle))
        except Exception:
            logger.warning("corrupt progress snapshot at %s; starting fresh", path)