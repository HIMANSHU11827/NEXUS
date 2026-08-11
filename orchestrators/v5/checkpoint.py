"""V5Checkpoint — per-phase durable snapshots and resume for the V5 loop.

Checkpoints are JSON files under .nexus_v5/checkpoints/, written at loop
phase transitions and loadable to resume a turn.

This module is part of the V5 loop architecture — a V5 module, not V1.
Dependency-free: no imports from core; every method is defensive and
never raises.
"""

from __future__ import annotations

import glob
import re
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional

from providers.reliability import redact_secrets

logger = logging.getLogger(__name__)

_ALLOWED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

# Transcript tail persisted with each checkpoint so a future ``continue``
# has conversation context without the in-memory runtime.
MAX_RECENT_MESSAGES = 12
MAX_TURN_HISTORY = 12
# Checkpoints are written on EVERY state transition (~4 per turn) and each
# one carries a bounded slice of transcript/actions. Without retention a
# long-running autonomous session grows the checkpoint directory without
# limit (measured ~34KB/file => ~134MB per 1000 turns). Keep the newest N;
# resume only ever reads the latest checkpoint for a turn.
MAX_CHECKPOINT_FILES = 200


# Extra patterns redact_secrets misses but checkpoints must still strip:
# AWS access-key ids (AKIA + 16 alphanumerics) and bare bearer tokens.
_CHECKPOINT_SECRET_RE = re.compile(
    r"(AKIA[0-9A-Z]{16})"  # AWS access key id
    r"|(?:bearer\s+)[A-Za-z0-9._\-]+"  # bearer token\n    r"|(?:password\s*[=:]\s*)[^\s"\]+"  # password= / password: form
)

def _redact_extra(value: str) -> str:
    return _CHECKPOINT_SECRET_RE.sub(lambda m: "***REDACTED***", value)

def _checkpoint_safe(value: Any) -> Any:
    """Redact secret-like strings before checkpoint serialization.

    Uses the shared ``redact_secrets`` (which catches OpenAI ``sk-``
    tokens) and then a checkpoint-local pass for shapes
    ``redact_secrets`` misses: AWS access-key ids, bearer tokens, and
    ``password=``/``password:`` assignments. Checkpoints persist
    ``response``/``memory`` verbatim, so a leaked file must not leak
    credentials of any recognized shape.
    """
    if isinstance(value, dict):
        return {str(key): _checkpoint_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_checkpoint_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_checkpoint_safe(item) for item in value]
    if isinstance(value, str):
        return _redact_extra(redact_secrets(value))
    return value


def _checkpoint_turn_history(turns: Any) -> List[Dict[str, Any]]:
    """Convert recent turn records into JSON-safe restart evidence."""
    if not isinstance(turns, list):
        return []
    snapshots: List[Dict[str, Any]] = []
    for turn in turns[-MAX_TURN_HISTORY:]:
        if isinstance(turn, dict):
            source = turn
        else:
            source = {
                key: getattr(turn, key, None)
                for key in (
                    "turn_id", "session_id", "user_input", "input_type",
                    "metadata", "start_time", "end_time", "state",
                )
            }
        if not isinstance(source, dict):
            continue
        state = source.get("state")
        if hasattr(state, "value"):
            state = state.value
        def _serial(value: Any) -> Any:
            if hasattr(value, "isoformat"):
                try:
                    return value.isoformat()
                except Exception:
                    pass
            return value
        snapshots.append({
            "turn_id": str(source.get("turn_id") or ""),
            "session_id": str(source.get("session_id") or ""),
            "user_input": str(source.get("user_input") or ""),
            "input_type": str(source.get("input_type") or "text"),
            "metadata": source.get("metadata") if isinstance(source.get("metadata"), dict) else {},
            "start_time": _serial(source.get("start_time")),
            "end_time": _serial(source.get("end_time")),
            "state": str(state or ""),
        })
    return snapshots


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

    @contextmanager
    def _checkpoint_write_lock(self) -> Iterator[None]:
        """Serialize checkpoint replacement and pruning across workers."""
        directory = self._checkpoint_dir()
        if not directory:
            yield
            return
        os.makedirs(directory, exist_ok=True)
        local_lock = getattr(self, "_checkpoint_local_lock", None)
        if local_lock is None:
            local_lock = threading.RLock()
            self._checkpoint_local_lock = local_lock
        lock_path = directory + ".lock.sqlite3"
        with local_lock:
            connection = sqlite3.connect(lock_path, timeout=60.0, isolation_level=None)
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield
                connection.execute("COMMIT")
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                connection.close()

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
                # The direct loop is the canonical execution path and its
                # result carries no ``plan``/``mental_state``: the real
                # evidence of what a turn achieved is the verification
                # verdict and the final response. Persisting them is what
                # lets a restarted process tell finished work from work
                # that still needs continuing, instead of resuming blind.
                for key in ("verification", "response", "success", "error"):
                    value = result.get(key)
                    if value is not None:
                        snapshot[key] = value
            # Fall back to live runtime state when no result has been
            # recorded yet (e.g. a checkpoint taken mid-turn).
            for key in ("plan", "actions", "mental_state"):
                if key not in snapshot:
                    value = getattr(runtime, key, None)
                    if value:
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
            turn_history = _checkpoint_turn_history(
                getattr(runtime, "turn_history", None)
            )
            if turn_history:
                snapshot["turn_history"] = turn_history
            snapshot["memory_len"] = len(getattr(runtime, "memory", None) or [])
            # ``memory_len`` alone is a count, not state: a restarted
            # process cannot rebuild working memory from an integer.
            # Persist the tail itself (bounded like recent_messages) so
            # resume restores real conversation state.
            memory = getattr(runtime, "memory", None)
            if isinstance(memory, list) and memory:
                snapshot["memory"] = [
                    m for m in memory if isinstance(m, dict)
                ][-MAX_RECENT_MESSAGES:]
            with self._checkpoint_write_lock():
                # Replace the checkpoint atomically so a process crash cannot
                # leave the only phase snapshot as truncated JSON. The lock
                # also keeps pruning from racing a concurrent writer.
                fd, temp_path = tempfile.mkstemp(
                    prefix=".checkpoint-", suffix=".tmp", dir=os.path.dirname(path)
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(_checkpoint_safe(snapshot), fh, ensure_ascii=False, indent=2, default=str)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(temp_path, path)
                    self._checkpoint_prune()
                finally:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
            return path
        except Exception:
            return None

    def _checkpoint_prune(self, keep: int = MAX_CHECKPOINT_FILES) -> int:
        """Delete the oldest checkpoints beyond ``keep``; count removed.

        Bounds the checkpoint directory for long-running sessions. Only whole
        files are removed, newest-first ordering is preserved, and the newest
        ``keep`` snapshots (which is all resume ever reads) are never touched.
        Never raises: a prune failure must not fail the checkpoint write.
        """
        removed = 0
        try:
            entries = self._checkpoint_list(limit=0)
            for entry in entries[keep:]:
                target = str(entry.get("file") or "")
                if not target:
                    continue
                try:
                    os.unlink(target)
                    removed += 1
                except Exception:
                    continue
        except Exception:
            return removed
        return removed

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
            saved_session = str(data.get("session") or "")
            current_session = str(getattr(self, "session_id", "") or "")
            # Turn ids are caller-supplied and are not guaranteed to be
            # globally unique. Never hydrate one session from another
            # session's durable state, even when the filenames collide.
            if saved_session and current_session and saved_session != current_session:
                logger.warning(
                    "Ignoring checkpoint for session %s while resuming session %s",
                    redact_secrets(saved_session),
                    redact_secrets(current_session),
                )
                return {}
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                for key in ("context_summary", "plan", "actions", "mental_state"):
                    if key in data and hasattr(runtime, key):
                        try:
                            setattr(runtime, key, data[key])
                        except Exception:
                            continue
                saved_memory = data.get("memory")
                recent_messages = data.get("recent_messages")
                source = saved_memory if isinstance(saved_memory, list) else recent_messages
                if isinstance(source, list):
                    runtime.memory = [m for m in source if isinstance(m, dict)][-80:]
                saved_turns = data.get("turn_history")
                if isinstance(saved_turns, list) and hasattr(runtime, "turn_history"):
                    runtime.turn_history = [
                        SimpleNamespace(**item)
                        for item in saved_turns
                        if isinstance(item, dict)
                    ][-MAX_TURN_HISTORY:]
                # Rebuild ``last_result`` so the restarted process can
                # actually EVALUATE the interrupted turn (did it succeed?
                # was it verified?) rather than only re-reading its text.
                # Without this the resume had no outcome signal at all.
                restored_result = {
                    key: data[key]
                    for key in ("verification", "response", "success", "error",
                                "plan", "actions", "mental_state")
                    if key in data
                }
                if restored_result and hasattr(runtime, "last_result"):
                    try:
                        runtime.last_result = restored_result
                    except Exception:
                        pass
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
                    if path.endswith(".resume.claim.json"):
                        continue
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
