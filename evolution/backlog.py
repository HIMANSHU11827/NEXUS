"""Durable improvement-action backlog.

The SelfImprovementEngine produces `actions` per session. Historically those
actions were write-only (logged to self_improvement.jsonl and never read),
so self-improvement never actually influenced behavior.

This module gives those actions a durable, *consumable* home:
`logs/improvements/action_backlog.jsonl`.

Safety: the backlog only ever writes under `logs/improvements/`. It routes the
write through utils.runtime_guard.assert_not_rewriting_core so it can never be
pointed at orchestrators/ kernel/ nexus/ server/ or other protected core code.
"""
from __future__ import annotations

__version__ = "1.0.0"

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

BACKLOG_RELPATH = os.path.join("logs", "improvements", "action_backlog.jsonl")

_STATUS_PENDING = "pending"
_VALID_STATUSES = {"pending", "in_progress", "done", "rejected"}


def _repo_root(root: Optional[str] = None) -> str:
    if root:
        return os.path.abspath(root)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def backlog_path(root: Optional[str] = None) -> str:
    """Absolute path of the action backlog file (guard-checked)."""
    path = os.path.join(_repo_root(root), BACKLOG_RELPATH)
    try:
        from utils.runtime_guard import assert_not_rewriting_core

        assert_not_rewriting_core(path, operation="append(action_backlog)")
    except ImportError:
        pass
    return path


def _normalize(action: Any) -> Dict[str, Any]:
    if isinstance(action, dict):
        entry: Dict[str, Any] = dict(action)
    else:
        entry = {"action": str(action)}
    entry.setdefault("action", "")
    entry.setdefault("source", "self_improvement")
    entry.setdefault("status", _STATUS_PENDING)
    if entry["status"] not in _VALID_STATUSES:
        entry["status"] = _STATUS_PENDING
    entry.setdefault("id", uuid.uuid4().hex[:12])
    entry.setdefault("ts", time.time())
    entry.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    return entry


def queue_improvement_action(action_dict: Any, root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Append one improvement action to the durable backlog.

    Accepts a dict (preferred) or a plain string action. Returns the stored
    entry, or None if persisting failed (never raises — callers run in
    best-effort finalize paths).
    """
    try:
        entry = _normalize(action_dict)
        if not str(entry.get("action", "")).strip():
            return None
        path = backlog_path(root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
    except Exception:
        logger.warning("evolution.backlog.queue_improvement_action: suppressed error", exc_info=True)
        return None


def queue_improvement_actions(actions: Iterable[Any], root: Optional[str] = None) -> int:
    """Queue many actions; returns the number successfully persisted."""
    count = 0
    for action in actions or []:
        if queue_improvement_action(action, root=root):
            count += 1
    return count


def read_backlog(root: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read backlog entries, optionally filtered by status. Consumers use this."""
    path = backlog_path(root)
    entries: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return entries
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if status is None or item.get("status") == status:
                    entries.append(item)
    except Exception:
        logger.warning("evolution.backlog.read_backlog: suppressed error", exc_info=True)
    return entries


def pending_actions(root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Actions still awaiting action — the consumable work queue."""
    return read_backlog(root=root, status=_STATUS_PENDING)


def mark_action_status(action_id: str, status: str, root: Optional[str] = None) -> bool:
    """Rewrite an action's status so a completed/rejected action is not
    re-proposed by pending_actions() on every future session.

    Reads the JSONL, rewrites the matching entry's status, and writes it back
    atomically. Returns True if the entry was found and updated.
    """
    if status not in _VALID_STATUSES:
        return False
    path = backlog_path(root)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        updated = False
        out = []
        for ln in lines:
            try:
                item = json.loads(ln)
            except Exception:
                out.append(ln)
                continue
            if item.get("id") == action_id:
                item["status"] = status
                item["resolved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                updated = True
            out.append(json.dumps(item, ensure_ascii=False) + "\n")
        if updated:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(out)
            os.replace(tmp, path)
        return updated
    except Exception:
        logger.warning("evolution.backlog.mark_action_status: suppressed error", exc_info=True)
        return False


__all__ = [
    "BACKLOG_RELPATH",
    "backlog_path",
    "queue_improvement_action",
    "queue_improvement_actions",
    "read_backlog",
    "pending_actions",
    "mark_action_status",
]
