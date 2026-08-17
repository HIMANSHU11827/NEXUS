"""Lightweight JSON persistence for NEXUS lifecycle managers.

State files live under ``~/.nexus/lifecycle/<manager_key>.json``. Lifecycle
operations remain best-effort, but the last persistence outcome is exposed for
diagnostics so state loss is not indistinguishable from an empty state.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("nexus.lifecycle.persistence")
_STATUS_LOCK = threading.RLock()
_STATUS: Dict[str, Dict[str, Any]] = {}


def _key(manager_key: str) -> str:
    """Normalize keys so lifecycle persistence cannot escape its state root."""
    value = str(manager_key or "").strip()
    return value.replace("\\", "_").replace("/", "_").replace("..", "_") or "unknown"


def _record(key: str, operation: str, available: bool, error: str = "") -> None:
    with _STATUS_LOCK:
        _STATUS[key] = {
            "available": bool(available),
            "operation": operation,
            "error": error[:500] if error else "",
            "updated_at": time.time(),
        }


def persistence_status(manager_key: str) -> Dict[str, Any]:
    """Return the last persistence outcome without raising."""
    key = _key(manager_key)
    with _STATUS_LOCK:
        return dict(_STATUS.get(key, {
            "available": True,
            "operation": "none",
            "error": "",
            "updated_at": 0.0,
        }))


def _state_dir() -> Path:
    return Path.home() / ".nexus" / "lifecycle"


def load_state(manager_key: str) -> Optional[Dict[str, Any]]:
    """Load a manager's previously persisted state, or None if unavailable."""
    key = _key(manager_key)
    path = _state_dir() / f"{key}.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _record(key, "load", True)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        _record(key, "load_missing", True)
        return None
    except Exception as exc:
        _record(key, "load", False, str(exc))
        logger.warning(
            "lifecycle/persistence.py load_state: suppressed error reading %s",
            path,
            exc_info=True,
        )
        return None


def clear_state(manager_key: str) -> bool:
    """Remove a manager's persisted state file, if present.

    Useful for test isolation and resetting a supervisor registry.
    Graceful no-op on any failure.
    """
    try:
        key = _key(manager_key)
        path = _state_dir() / f"{key}.json"
        path.unlink(missing_ok=True)
        _record(key, "clear", True)
        return True
    except Exception as exc:
        _record(_key(manager_key), "clear", False, str(exc))
        logger.warning(
            "lifecycle/persistence.py clear_state: suppressed error removing %s",
            manager_key,
            exc_info=True,
        )
        return False


def save_state(manager_key: str, data: Dict[str, Any]) -> bool:
    """Persist a manager's state atomically; return whether it was durable."""
    key = _key(manager_key)
    try:
        d = _state_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{key}.json"
        fd, temporary = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        _record(key, "save", True)
        return True
    except Exception as exc:
        _record(key, "save", False, str(exc))
        logger.warning(
            "lifecycle/persistence.py save_state: suppressed error writing %s",
            manager_key,
            exc_info=True,
        )
        return False
