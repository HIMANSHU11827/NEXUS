"""V5Checkpoint — per-phase durable snapshots and resume for the V5 loop.

Checkpoints are JSON files under .nexus_v5/checkpoints/, written at loop
phase transitions and loadable to resume a turn.

This module is part of the V5 loop architecture — a V5 module, not V1.
Dependency-free: no imports from core; every method is defensive and
never raises.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ALLOWED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

# Transcript tail persisted with each checkpoint so a future ``continue``
# has conversation context without the in-memory runtime.
MAX_RECENT_MESSAGES = 12


class V5Checkpoint:
    """Mixin giving the V5 loop durable per-phase checkpoints.

    Expected attributes when mixed into ``NexusLoopV5``:
    - ``self.root_dir`` - project root used to resolve the checkpoint
      directory (``.nexus_v5/checkpoints``).
    - ``self.session_id`` - session id stamped on every snapshot.
    - ``self.logger`` - python logger exposing ``.info``/``.warning``.
    - ``self.runtime`` - object carrying ``current_turn``, ``turn_history``,
      ``memory`` and optional ``last_result``; may be None in exotic cases,
      everything is guarded.
    - ``self._current_turn_id`` - id of the in-flight turn.
    """

    def _checkpoint_dir(self) -> str:
        """Resolve the checkpoint directory; "" on failure."""
        try:
            root = getattr(self, "root_dir", None) or os.getcwd()
            return os.path.join(root, ".nexus_v5", "checkpoints")
        except Exception:
            return ""

    def _checkpoint_sanitize(self, name: str) -> str:
        """Keep [A-Za-z0-9_-], replacing every other character with '_'."""
        try:
            return "".join(c if c in _ALLOWED else "_" for c in (name or ""))
        except Exception:
            return "turn"

    def _checkpoint_path(self, turn_id: str = "", phase: str = "") -> str:
        """Resolve the checkpoint file path for (turn_id, phase); "" on failure."""
        try:
            directory = self._checkpoint_dir()
            if not directory:
                return ""
            safe_turn = self._checkpoint_sanitize(turn_id) or "turn"
            safe_phase = self._checkpoint_sanitize(phase)
            return os.path.join(directory, f"{safe_turn}_{safe_phase}.json")
        except Exception:
            return ""

    def _checkpoint_turn_id(self, turn_id: str = "") -> str:
        """Resolve the best-known turn id; "" on failure."""
        try:
            if turn_id:
                return turn_id
            runtime = getattr(self, "runtime", None)
            current = getattr(runtime, "current_turn", None)
            return (
                getattr(current, "turn_id", "")
                or getattr(self, "_current_turn_id", "")
                or ""
            )
        except Exception:
            return ""

    def _checkpoint_context_summary(self, runtime: Any = None) -> Any:
        """Pull the best-known context summary from the runtime; None if absent."""
        try:
            if runtime is None:
                runtime = getattr(self, "runtime", None)
            for attr in ("context_summary", "_v5_context_summary"):
                value = getattr(runtime, attr, None)
                if value is not None:
                    return value
            turns = getattr(runtime, "turn_history", None) or []
            if turns:
                first = turns[0]
                for attr in ("context_summary", "context"):
                    value = getattr(first, attr, None)
                    if value is not None:
                        return value
                return getattr(first, "user_input", None)
            return None
        except Exception:
            return None

    def _checkpoint_save(self, turn_id: str = "", phase: str = "") -> Optional[str]:
        """Snapshot the current turn state to JSON; the path, or None on failure."""
        try:
            resolved_turn = self._checkpoint_turn_id(turn_id)
            path = self._checkpoint_path(resolved_turn, phase)
            if not path:
                return None
            runtime = getattr(self, "runtime", None)
            snapshot: Dict[str, Any] = {
                "turn_id": resolved_turn,
                "phase": phase or "",
                "ts": time.time(),
                "session": getattr(self, "session_id", "default") or "default",
            }
            context_summary = self._checkpoint_context_summary(runtime)
            if context_summary is not None:
                snapshot["context_summary"] = context_summary
            result = getattr(runtime, "last_result", None)
            if isinstance(result, dict):
                for key in ("plan", "actions", "mental_state"):
                    value = result.get(key)
                    if value is not None:
                        snapshot[key] = value
            # Carry the tail of the live transcript so a future ``continue``
            # has conversation context even without the in-memory runtime.
            recent_messages = getattr(self, "_recent_messages", None)
            if not isinstance(recent_messages, list) and isinstance(result, dict):
                recent_messages = result.get("messages")
            if isinstance(recent_messages, list) and recent_messages:
                snapshot["recent_messages"] = recent_messages[-MAX_RECENT_MESSAGES:]
            snapshot["turn_history_len"] = len(
                getattr(runtime, "turn_history", None) or []
            )
            snapshot["memory_len"] = len(getattr(runtime, "memory", None) or [])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, ensure_ascii=False, indent=2, default=str)
            return path
        except Exception:
            return None

    def _checkpoint_read(self, path: str) -> Dict[str, Any]:
        """Read and parse one checkpoint file; {} on failure."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _checkpoint_ts(self, path: str) -> float:
        """Read the recorded timestamp from a file; mtime fallback."""
        try:
            data = self._checkpoint_read(path)
            ts = data.get("ts")
            if isinstance(ts, (int, float)):
                return float(ts)
            return os.path.getmtime(path)
        except Exception:
            return 0.0

    def _checkpoint_load(self, turn_id: str = "", phase: str = "") -> Dict[str, Any]:
        """Read the checkpoint for (turn_id, phase); {} on failure.

        When ``phase`` is empty, the most recently written checkpoint
        matching the turn id is returned.
        """
        try:
            if phase:
                path = self._checkpoint_path(turn_id, phase)
                if not path or not os.path.exists(path):
                    return {}
                data = self._checkpoint_read(path)
                if data:
                    data["file"] = path
                return data
            entries = self._checkpoint_list(limit=0)
            resolved = self._checkpoint_sanitize(
                turn_id or self._checkpoint_turn_id()
            ) or "turn"
            matches = [e for e in entries if e.get("turn_id") == resolved]
            if not matches:
                return {}
            path = str(matches[0].get("file") or "")
            data = self._checkpoint_read(path)
            if data:
                data["file"] = path
            return data
        except Exception:
            return {}

    def _checkpoint_resume(self, turn_id: str = "") -> Dict[str, Any]:
        """Load the latest checkpoint for a turn and restore it; {} on failure.

        Restores snapshot fields into the runtime only when the runtime
        already has a matching attribute. The checkpoint path is stamped
        into the returned dict as ``resumed_from_checkpoint``.
        """
        try:
            data = self._checkpoint_load(turn_id)
            if not data:
                return {}
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                for key in ("context_summary", "plan", "actions", "mental_state"):
                    if key in data and hasattr(runtime, key):
                        try:
                            setattr(runtime, key, data[key])
                        except Exception:
                            continue
            data["resumed_from_checkpoint"] = data.get("file", "")
            return data
        except Exception:
            return {}

    def _checkpoint_list(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List checkpoints newest-first; [] on failure.

        Each entry carries ``file``, ``turn_id``, ``phase`` and ``ts``,
        parsed from the ``<turn_id>_<phase>.json`` filenames.
        """
        try:
            directory = self._checkpoint_dir()
            if not directory or not os.path.isdir(directory):
                return []
            entries: List[Dict[str, Any]] = []
            for path in glob.glob(os.path.join(directory, "*.json")):
                try:
                    stem = os.path.basename(path)[:-5]
                    turn_id, phase = stem.rsplit("_", 1)
                    entries.append(
                        {
                            "file": path,
                            "turn_id": turn_id,
                            "phase": phase,
                            "ts": self._checkpoint_ts(path),
                        }
                    )
                except Exception:
                    continue
            entries.sort(key=lambda entry: entry.get("ts", 0.0), reverse=True)
            if limit > 0:
                return entries[:limit]
            return entries
        except Exception:
            return []

    def _checkpoint_clear(self, turn_id: str = "") -> int:
        """Delete checkpoint files (one turn if given, else all); count deleted."""
        try:
            entries = self._checkpoint_list(limit=0)
            if turn_id:
                safe_turn = self._checkpoint_sanitize(turn_id) or "turn"
                entries = [e for e in entries if e.get("turn_id") == safe_turn]
            count = 0
            for entry in entries:
                try:
                    os.remove(str(entry.get("file") or ""))
                    count += 1
                except Exception:
                    continue
            return count
        except Exception:
            return 0
