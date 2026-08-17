"""Durable status and heartbeat records for queue workers.

The record is intentionally small and atomic.  It is useful to an external
supervisor (systemd, Compose, Task Scheduler, or the desktop launcher) without
requiring the supervisor to open the queue database or inspect process tables.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from typing import Any, Dict, Optional


def default_status_path(root: str) -> str:
    return os.path.join(os.path.abspath(root), ".nexus", "queue_driver_status.json")


def default_incident_path(root: str) -> str:
    return os.path.join(os.path.abspath(root), ".nexus", "queue_driver_incident.json")


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _write_json_atomic(path: str, payload: Dict[str, Any], prefix: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_crash(root: str, error: str, *, max_restarts: int = 5,
                 window_seconds: float = 300.0, path: Optional[str] = None) -> Dict[str, Any]:
    """Persist a crash-window incident and return its quarantine decision."""
    incident_path = os.path.abspath(path or default_incident_path(root))
    prior = _read_json(incident_path)
    now = time.time()
    window = max(1.0, float(window_seconds))
    failures = [float(item) for item in prior.get("failures", [])
                if isinstance(item, (int, float)) and now - float(item) <= window]
    failures.append(now)
    limit = max(1, int(max_restarts))
    quarantined = len(failures) >= limit
    payload = {
        "version": 1,
        "state": "quarantined" if quarantined else "recovering",
        "failures": failures[-limit:],
        "failure_count": len(failures),
        "max_restarts": limit,
        "window_seconds": window,
        "last_error": str(error or "")[:1000],
        "updated_at": now,
    }
    _write_json_atomic(incident_path, payload, ".queue-incident-")
    return {**payload, "path": incident_path, "quarantined": quarantined}


def read_incident(root: str, *, path: Optional[str] = None) -> Dict[str, Any]:
    incident_path = os.path.abspath(path or default_incident_path(root))
    payload = _read_json(incident_path)
    if not payload:
        return {"state": "clear", "failure_count": 0, "quarantined": False, "path": incident_path}
    now = time.time()
    try:
        age = now - float(payload.get("updated_at", 0))
    except (TypeError, ValueError):
        age = float("inf")
    window = max(1.0, float(payload.get("window_seconds", 300)))
    failures = [item for item in payload.get("failures", [])
                if isinstance(item, (int, float)) and now - float(item) <= window]
    quarantined = str(payload.get("state")) == "quarantined" and bool(failures)
    return {**payload, "failures": failures, "failure_count": len(failures),
            "age": max(0.0, age), "quarantined": quarantined, "path": incident_path}


def clear_incident(root: str, *, path: Optional[str] = None) -> None:
    """Explicit operator action to allow a quarantined worker to restart."""
    incident_path = os.path.abspath(path or default_incident_path(root))
    _write_json_atomic(incident_path, {
        "version": 1, "state": "clear", "failures": [], "failure_count": 0,
        "cleared_at": time.time(),
    }, ".queue-incident-")


class QueueRuntimeStatus:
    """Publish an atomic worker lifecycle record and heartbeat."""

    def __init__(self, root: str, path: Optional[str] = None, owner: str = "") -> None:
        self.path = os.path.abspath(path or default_status_path(root))
        self.owner = owner or f"queue-{os.getpid()}-{uuid.uuid4().hex[:10]}"
        self.started_at = time.time()
        self._last_publish = 0.0

    def publish(self, state: str, *, stats: Optional[Dict[str, Any]] = None,
                error: str = "", force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_publish < 2.0:
            return
        payload = {
            "version": 1,
            "owner": self.owner,
            "pid": os.getpid(),
            "state": str(state),
            "started_at": self.started_at,
            "heartbeat_at": now,
            "stats": dict(stats or {}),
            "last_error": str(error or "")[:1000],
        }
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".queue-status-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self._last_publish = now
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def stopped(self, *, stats: Optional[Dict[str, Any]] = None, error: str = "") -> None:
        self.publish("stopped", stats=stats, error=error, force=True)


def read_status(path: str, *, stale_after: float = 30.0) -> Dict[str, Any]:
    """Read status and derive a conservative ``healthy`` flag."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"state": "missing", "healthy": False, "stale": True, "path": path}
    if not isinstance(payload, dict):
        return {"state": "invalid", "healthy": False, "stale": True, "path": path}
    try:
        age = max(0.0, time.time() - float(payload.get("heartbeat_at", 0)))
    except (TypeError, ValueError):
        age = float("inf")
    state = str(payload.get("state") or "unknown")
    stale = age > max(1.0, float(stale_after))
    return {**payload, "path": path, "heartbeat_age": age, "stale": stale,
            "healthy": state == "running" and not stale}


__all__ = [
    "QueueRuntimeStatus", "default_incident_path", "default_status_path",
    "read_incident", "read_status", "record_crash", "clear_incident",
]
