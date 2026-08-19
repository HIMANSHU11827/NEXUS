"""Durable event log — persistent JSONL event stream for replay and resume.

Inspired by OpenHands' EventStream and Codex's JSONL protocol: every
canonical event is persisted to a JSONL file so a crashed/restarted process
can replay the event history, reconstruct turn state, and resume work.

Events are append-only and bounded (oldest entries pruned). The log lives
at .nexus/v5/event_log.jsonl alongside the existing checkpoint system.

Benefits:
- Crash recovery: replay events to reconstruct what happened
- Debugging: full event history for post-mortem analysis
- Learning: deterministic replay for training/evaluation
- Audit trail: permanent record of every action taken
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

_MAX_LOG_ENTRIES = 10_000
_MAX_LOG_SIZE_MB = 50


class DurableEventLog:
    """Append-only JSONL event log with automatic pruning.

    Thread-safe: uses a threading lock for concurrent writes. Each event is
    a single JSON line with an auto-incrementing sequence number.
    """

    def __init__(self, root_dir: str, session_id: str = "default"):
        self.root_dir = root_dir
        self.session_id = session_id
        self._lock = threading.Lock()
        self._sequence = 0
        self._log_path = self._resolve_log_path()
        self._init_sequence()

    def _resolve_log_path(self) -> str:
        """Resolve the log file path."""
        base = os.path.join(self.root_dir, ".nexus", "v5")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "event_log.jsonl")

    def _init_sequence(self) -> None:
        """Read the last sequence number from existing log."""
        try:
            if os.path.exists(self._log_path):
                with open(self._log_path, "r", encoding="utf-8") as f:
                    last_line = ""
                    for line in f:
                        line = line.strip()
                        if line:
                            last_line = line
                    if last_line:
                        entry = json.loads(last_line)
                        self._sequence = int(entry.get("seq", 0))
        except Exception:
            self._sequence = 0

    def append(self, event: Dict[str, Any]) -> int:
        """Append an event to the durable log; returns the sequence number.

        The event is augmented with seq, ts, and session_id before writing.
        """
        with self._lock:
            self._sequence += 1
            seq = self._sequence
            enriched = {
                "seq": seq,
                "ts": time.time(),
                "session": self.session_id,
                **{k: v for k, v in event.items() if k not in ("seq", "ts", "session")},
            }
            try:
                line = json.dumps(enriched, ensure_ascii=False, default=str)
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                self._maybe_prune()
            except Exception as exc:
                logger.debug("durable event log append failed: %s", exc)
            return seq

    def replay(
        self,
        *,
        after_seq: int = 0,
        event_type: Optional[str] = None,
        turn_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Replay events from the log, optionally filtered.

        Args:
            after_seq: Only return events with seq > after_seq.
            event_type: Filter by event_type field.
            turn_id: Filter by turn_id field.
            limit: Maximum events to return.

        Returns:
            List of event dicts in chronological order.
        """
        results: List[Dict[str, Any]] = []
        try:
            if not os.path.exists(self._log_path):
                return results
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    seq = int(entry.get("seq", 0))
                    if seq <= after_seq:
                        continue
                    if event_type and entry.get("event_type") != event_type:
                        continue
                    if turn_id and entry.get("turn_id") != turn_id:
                        continue
                    results.append(entry)
                    if len(results) >= limit:
                        break
        except Exception as exc:
            logger.debug("durable event log replay failed: %s", exc)
        return results

    def replay_turn(self, turn_id: str) -> List[Dict[str, Any]]:
        """Replay all events for a specific turn."""
        return self.replay(turn_id=turn_id, limit=1000)

    def latest_seq(self) -> int:
        """Return the current sequence number."""
        return self._sequence

    def turn_summary(self, turn_id: str) -> Dict[str, Any]:
        """Build a summary of what happened in a turn."""
        events = self.replay_turn(turn_id)
        tool_events = [e for e in events if e.get("kind") == "tool"]
        plan_events = [e for e in events if e.get("kind") == "plan"]
        return {
            "turn_id": turn_id,
            "total_events": len(events),
            "tool_calls": len(tool_events),
            "plan_updates": len(plan_events),
            "first_ts": events[0]["ts"] if events else 0,
            "last_ts": events[-1]["ts"] if events else 0,
            "events": events[-50:],  # Last 50 events
        }

    def _maybe_prune(self) -> None:
        """Prune old entries if the log exceeds size/entry limits."""
        try:
            size_mb = os.path.getsize(self._log_path) / (1024 * 1024)
            if size_mb < _MAX_LOG_SIZE_MB:
                return
            # Read all entries, keep the newest ones
            entries: List[str] = []
            with open(self._log_path, "r", encoding="utf-8") as f:
                entries = [line.strip() for line in f if line.strip()]
            if len(entries) <= _MAX_LOG_ENTRIES:
                return
            keep = entries[-_MAX_LOG_ENTRIES:]
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(keep) + "\n")
            logger.info(
                "pruned event log from %d to %d entries (%.1f MB)",
                len(entries), len(keep), size_mb,
            )
        except Exception:
            pass

    def clear(self) -> int:
        """Clear the event log; returns number of entries removed."""
        with self._lock:
            count = 0
            try:
                if os.path.exists(self._log_path):
                    with open(self._log_path, "r", encoding="utf-8") as f:
                        count = sum(1 for line in f if line.strip())
                    os.remove(self._log_path)
                    self._sequence = 0
            except Exception:
                pass
            return count
