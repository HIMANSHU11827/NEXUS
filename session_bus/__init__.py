"""Shared session state for terminal, CLI, GUI, and gateway."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Optional


def safe_session_id(session_id: str) -> str:
    raw = os.path.basename(str(session_id or "default")).replace(".json", "")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip("._")
    return cleaned or "default"


def active_session_path(root: str) -> str:
    return os.path.join(os.path.abspath(root), "workspace", "active_session.json")


def session_memory_path(root: str, session_id: str) -> str:
    sid = safe_session_id(session_id)
    return os.path.join(os.path.abspath(root), "logs", "sessions", f"{sid}.json")


def work_events_path(root: str, session_id: str) -> str:
    sid = safe_session_id(session_id)
    return os.path.join(os.path.abspath(root), "workspace", "work_events", f"{sid}.jsonl")


def get_active_session(root: str, default: str = "default") -> Dict[str, Any]:
    path = active_session_path(root)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data["session_id"] = safe_session_id(data.get("session_id", default))
                return data
    except Exception:
        pass
    sid = safe_session_id(default)
    return {"session_id": sid, "source": "default", "updated_at": 0.0}


def get_active_session_id(root: str, default: str = "default") -> str:
    return str(get_active_session(root, default).get("session_id", safe_session_id(default)))


def set_active_session_id(root: str, session_id: str, source: str = "") -> str:
    sid = safe_session_id(session_id)
    os.makedirs(os.path.join(os.path.abspath(root), "workspace"), exist_ok=True)
    payload = {
        "session_id": sid,
        "source": source or "unknown",
        "updated_at": time.time(),
    }
    with open(active_session_path(root), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return sid


def load_session_history(root: str, session_id: str) -> list:
    path = session_memory_path(root, session_id)
    legacy = os.path.join(os.path.abspath(root), "logs", "session_memory.json")
    try:
        if not os.path.exists(path) and safe_session_id(session_id) == "default" and os.path.exists(legacy):
            path = legacy
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def sync_loop_from_disk(loop) -> None:
    if hasattr(loop, "sync_memory"):
        loop.sync_memory()
