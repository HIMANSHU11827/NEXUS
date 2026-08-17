"""Session bus — shared session management across TUI, GUI, and gateway."""

import json
import logging
import os
import time
from typing import Optional

from nexus.runtime import safe_session_id

logger = logging.getLogger("nexus.session_bus")

_SESSION_PATHS: dict[str, str] = {}


def _ensure_path(root: str) -> str:
    normalized_root = os.path.abspath(root or ".")
    path = _SESSION_PATHS.get(normalized_root)
    if path is None:
        path = os.path.join(normalized_root, "workspace", "active_session.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _SESSION_PATHS[normalized_root] = path
    return path


def get_active_session_id(root: str, default_session_id: str) -> str:
    path = _ensure_path(root)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return safe_session_id(data.get("session_id", default_session_id))
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("get_active_session_id: %s", e)
    return default_session_id


def get_active_session(root: str, default_session_id: str = "default") -> dict:
    path = _ensure_path(root)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return {
                "session_id": safe_session_id(data.get("session_id") or default_session_id),
                "source": str(data.get("source") or "unknown"),
                "updated_at": float(data.get("updated_at") or 0),
            }
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
            logger.debug("get_active_session: %s", e)
    return {"session_id": safe_session_id(default_session_id), "source": "default", "updated_at": 0.0}


def set_active_session_id(root: str, session_id: str, source: str = "terminal") -> str:
    path = _ensure_path(root)
    session_id = safe_session_id(session_id)
    data = {"session_id": session_id, "source": source, "updated_at": time.time()}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        logger.debug("set_active_session_id: %s", e)
    return session_id


def sync_loop_from_disk(loop=None) -> None:
    return None
