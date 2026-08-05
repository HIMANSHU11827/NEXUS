"""Lightweight JSON persistence for NEXUS lifecycle managers.

State files live under ``~/.nexus/lifecycle/<manager_key>.json``. Writes are
best-effort: any failure is a silent no-op so persistence can never crash a
lifecycle operation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("nexus.lifecycle.persistence")


def _state_dir() -> Path:
    return Path.home() / ".nexus" / "lifecycle"


def load_state(manager_key: str) -> Optional[Dict[str, Any]]:
    """Load a manager's previously persisted state, or None if unavailable."""
    path = _state_dir() / f"{manager_key}.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning(
            "lifecycle/persistence.py load_state: suppressed error reading %s",
            path,
            exc_info=True,
        )
        return None


def clear_state(manager_key: str) -> None:
    """Remove a manager's persisted state file, if present.

    Useful for test isolation and resetting a supervisor registry.
    Graceful no-op on any failure.
    """
    try:
        path = _state_dir() / f"{manager_key}.json"
        path.unlink(missing_ok=True)
    except Exception:
        logger.warning(
            "lifecycle/persistence.py clear_state: suppressed error removing %s",
            manager_key,
            exc_info=True,
        )


def save_state(manager_key: str, data: Dict[str, Any]) -> None:
    """Persist a manager's state. Graceful no-op on any write failure."""
    try:
        d = _state_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{manager_key}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except Exception:
        logger.warning(
            "lifecycle/persistence.py save_state: suppressed error writing %s",
            manager_key,
            exc_info=True,
        )
