"""Small durable verifier freshness store for V5.

This module is intentionally independent from the loop and the action verifier.
It records verifier state only; callers decide when a successful mutation should
call :meth:`mark_stale`.  The store uses a bounded JSON document, an advisory
sidecar lock, and atomic replacement so separate Nexus processes do not lose
updates or observe half-written state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

try:  # pragma: no cover - platform branches are covered in CI environments.
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None

try:  # pragma: no cover - platform branches are covered in CI environments.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


_SCHEMA_VERSION = 1
_DEFAULT_MAX_RECORDS = 128
_DEFAULT_MAX_CHANGED_PATHS = 200
_DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
_MAX_SESSION = 256
_MAX_ROOT = 1024
_MAX_PATH = 500
_ALLOWED_STATUSES = frozenset({"passed", "failed", "stale", "unverified", "not_applicable"})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timestamp(value: Optional[str]) -> str:
    if value is None:
        return _utc_now()
    text = str(value).strip()[:64]
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be an ISO-8601 value") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch(value: Any) -> Optional[float]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value: Any, limit: int) -> str:
    return _CONTROL_CHARS.sub("", str(value or "")).strip()[:limit]


def _normal_root(value: Any) -> str:
    text = _text(value, _MAX_ROOT)
    if not text:
        raise ValueError("root is required")
    try:
        return os.path.normcase(str(Path(text).expanduser().resolve(strict=False)))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("root is not a valid path") from exc


class VerifierStateStore:
    """Bounded, process-safe persistence for verifier freshness state.

    ``get`` is deliberately conservative: a missing or malformed document is
    reported as ``unverified`` instead of raising or claiming a pass.  Writes
    repair malformed state by replacing it with a valid bounded document.
    """

    def __init__(
        self,
        path: Optional[os.PathLike[str] | str] = None,
        *,
        max_records: int = _DEFAULT_MAX_RECORDS,
        max_changed_paths: int = _DEFAULT_MAX_CHANGED_PATHS,
        retention_seconds: float = _DEFAULT_RETENTION_SECONDS,
    ) -> None:
        if max_records < 1 or max_changed_paths < 1 or retention_seconds <= 0:
            raise ValueError("retention and bounds must be positive")
        self.path = Path(path) if path is not None else Path.cwd() / ".nexus" / "v5" / "verifier_state.json"
        self.lock_path = Path(str(self.path) + ".lock")
        self.max_records = int(max_records)
        self.max_changed_paths = int(max_changed_paths)
        self.retention_seconds = float(retention_seconds)
        self._thread_lock = threading.RLock()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            if msvcrt is not None:
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            elif fcntl is not None:  # pragma: no cover - exercised on Unix CI.
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if msvcrt is not None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                elif fcntl is not None:  # pragma: no cover
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> List[Dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        records = raw.get("records") if isinstance(raw, dict) else None
        if not isinstance(records, list):
            return []
        return [record for record in records if self._valid_record(record)]

    def _valid_record(self, record: Any) -> bool:
        if not isinstance(record, dict):
            return False
        return (
            isinstance(record.get("session_id"), str)
            and bool(record["session_id"])
            and isinstance(record.get("root"), str)
            and bool(record["root"])
            and isinstance(record.get("verifier_id"), str)
            and bool(record["verifier_id"])
            and record.get("status") in _ALLOWED_STATUSES
            and _epoch(record.get("verified_at")) is not None
        )

    def _prune(self, records: List[Dict[str, Any]], now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = time.time() if now is None else now
        kept = []
        for record in records:
            anchor = _epoch(record.get("stale_at")) or _epoch(record.get("verified_at"))
            if anchor is not None and now - anchor <= self.retention_seconds:
                record["changed_paths"] = list(record.get("changed_paths") or [])[: self.max_changed_paths]
                kept.append(record)
        kept.sort(key=lambda item: _epoch(item.get("verified_at")) or 0.0, reverse=True)
        return kept[: self.max_records]

    def _write(self, records: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": _SCHEMA_VERSION, "records": self._prune(records)}
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def _key(session_id: Any, root: Any) -> tuple[str, str]:
        session = _text(session_id, _MAX_SESSION)
        if not session:
            raise ValueError("session_id is required")
        return session, _normal_root(root)

    def _changed_paths(self, root: str, paths: Iterable[Any]) -> List[str]:
        result: List[str] = []
        seen = set()
        root_path = Path(root)
        for raw in paths or ():
            text = _text(raw, _MAX_PATH)
            if not text:
                continue
            try:
                candidate = Path(text).expanduser()
                if not candidate.is_absolute():
                    candidate = root_path / candidate
                candidate = candidate.resolve(strict=False)
                relative = candidate.relative_to(root_path).as_posix()
            except (OSError, RuntimeError, ValueError):
                continue
            if relative not in seen:
                seen.add(relative)
                result.append(relative[:_MAX_PATH])
            if len(result) >= self.max_changed_paths:
                break
        return result

    def record_verification(
        self,
        session_id: str,
        root: str,
        *,
        status: str,
        verifier_id: Optional[str] = None,
        event_id: Optional[str] = None,
        verified_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a new result and clear any prior stale state for its key."""
        session, normalized_root = self._key(session_id, root)
        if status not in _ALLOWED_STATUSES or status == "stale" or status == "unverified":
            raise ValueError("record status must be passed, failed, or not_applicable")
        record = {
            "session_id": session,
            "root": normalized_root,
            "verifier_id": _text(verifier_id, 128) or secrets.token_hex(16),
            "last_event_id": _text(event_id, 128),
            "verified_at": _timestamp(verified_at),
            "stale_at": None,
            "changed_paths": [],
            "status": status,
        }
        with self._thread_lock, self._lock():
            records = [item for item in self._read() if (item["session_id"], item["root"]) != (session, normalized_root)]
            records.append(record)
            self._write(records)
        return copy.deepcopy(record)

    def mark_stale(
        self,
        session_id: str,
        root: str,
        changed_paths: Iterable[Any] = (),
        *,
        stale_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invalidate an existing result, preserving its verifier identity."""
        session, normalized_root = self._key(session_id, root)
        with self._thread_lock, self._lock():
            records = self._read()
            found = next((item for item in records if (item["session_id"], item["root"]) == (session, normalized_root)), None)
            if found is None:
                return {
                    "session_id": session,
                    "root": normalized_root,
                    "status": "unverified",
                    "verifier_id": None,
                    "verified_at": None,
                    "stale_at": None,
                    "changed_paths": [],
                }
            found["status"] = "stale"
            found["stale_at"] = _timestamp(stale_at)
            previous_paths = found.get("changed_paths") if isinstance(found.get("changed_paths"), list) else []
            found["changed_paths"] = self._changed_paths(
                normalized_root, [*previous_paths, *(changed_paths or ())]
            )
            self._write(records)
            return copy.deepcopy(found)

    def get(self, session_id: str, root: str) -> Dict[str, Any]:
        """Return one state record, or a conservative ``unverified`` result."""
        session, normalized_root = self._key(session_id, root)
        with self._thread_lock, self._lock():
            records = self._prune(self._read())
            found = next((item for item in records if (item["session_id"], item["root"]) == (session, normalized_root)), None)
            if found is None:
                return {"session_id": session, "root": normalized_root, "status": "unverified", "verifier_id": None, "verified_at": None, "stale_at": None, "changed_paths": []}
            return copy.deepcopy(found)

    def digest(self, session_id: str, root: str) -> str:
        """Return a stable digest of the bounded projected state."""
        state = self.get(session_id, root)
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["VerifierStateStore"]
