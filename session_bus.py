"""Session bus — shared session management across terminal, CLI, GUI, gateway."""

import os
import json
import uuid
from typing import Optional

_SESSION_PATH: Optional[str] = None


def _ensure_path(root: str) -> str:
    global _SESSION_PATH
    if _SESSION_PATH is None:
        _SESSION_PATH = os.path.join(root, "workspace", "active_session.json")
        os.makedirs(os.path.dirname(_SESSION_PATH), exist_ok=True)
    return _SESSION_PATH


def get_active_session_id(root: str, default_session_id: str) -> str:
    path = _ensure_path(root)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("session_id", default_session_id)
        except (json.JSONDecodeError, OSError):
            pass
    return default_session_id


def set_active_session_id(root: str, session_id: str, source: str = "terminal") -> None:
    path = _ensure_path(root)
    data = {"session_id": session_id, "source": source}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def sync_loop_from_disk() -> None:
    pass
