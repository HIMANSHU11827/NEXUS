"""Evidence-based conversation and task continuity."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

_UNFINISHED = {"running", "failed", "error", "cancelled", "canceled", "aborted"}
_TERMINAL_CHECKPOINT_PHASES = {
    "complete", "completed", "done", "success", "succeeded", "finished",
}


@dataclass(frozen=True)
class ContinuitySnapshot:
    available: bool = False
    session_id: str = ""
    task: str = ""
    status: str = ""
    error: str = ""
    run_id: str = ""
    source: str = ""
    checkpoint: str = ""
    queue_task_id: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def as_prompt(self) -> str:
        if not self.available:
            return ""
        lines = [
            "[CONTINUITY — PERSISTED EVIDENCE]",
            f"An unfinished task record exists: {self.task or 'the persisted task'}",
        ]
        if self.run_id:
            lines.append(f"Run: {self.run_id}")
        if self.status:
            lines.append(f"Recorded status: {self.status}")
        if self.error:
            lines.append(f"Recorded error: {self.error}")
        if self.checkpoint:
            lines.append(f"Checkpoint: {self.checkpoint}")
        lines.append("Progress after this evidence is unknown; ask whether to continue before claiming work was done.")
        return "\n".join(lines)


def _text(value: Any, limit: int = 1000) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return str(value).strip().replace("\r", " ").replace("\n", " ")[:limit]


def _load(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return None


def _safe_component(value: str) -> str:
    """Match durable run-context naming so readers use the same directory."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())[:120] or "default"


def _run_contexts(root: str, session_id: str) -> List[Dict[str, Any]]:
    folder = os.path.join(root, "logs", "run_contexts", _safe_component(session_id))
    rows = []
    if not os.path.isdir(folder):
        return rows
    for name in os.listdir(folder):
        if name.endswith(".json"):
            value = _load(os.path.join(folder, name))
            if isinstance(value, dict):
                rows.append(value)
    return sorted(rows, key=lambda row: float(row.get("updated_at") or row.get("started_at") or 0), reverse=True)


def _latest_checkpoint(root: str, session_id: str) -> Dict[str, Any]:
    folder = os.path.join(root, ".nexus_v5", "checkpoints")
    candidates = []
    if not os.path.isdir(folder):
        return {}
    for name in os.listdir(folder):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        value = _load(path)
        if isinstance(value, dict) and _safe_component(str(value.get("session") or "")) == _safe_component(session_id):
            candidates.append((float(value.get("ts") or os.path.getmtime(path)), path, value))
    if not candidates:
        return {}
    _, path, value = max(candidates, key=lambda row: row[0])
    if str(value.get("phase") or "").strip().lower() in _TERMINAL_CHECKPOINT_PHASES:
        return {}
    result = dict(value)
    result["file"] = path
    return result


def _todo(root: str) -> Dict[str, str]:
    path = os.path.join(root, "workspace", "todo.md")
    try:
        content = open(path, "r", encoding="utf-8").read()
    except OSError:
        return {}
    pending = [line.strip() for line in content.splitlines() if "[ ]" in line or "[/]" in line]
    if not pending:
        return {}
    task = next((line.split(":", 1)[1].strip() for line in content.splitlines() if line.lower().startswith("task:") and ":" in line), "")
    return {"task": _text(task or pending[0], 500), "evidence": "workspace/todo.md"}


def inspect_continuity(root: str, session_id: str = "default", queue: Any = None) -> ContinuitySnapshot:
    """Return only unfinished work backed by a durable record."""
    root = os.path.abspath(root)
    session_id = str(session_id or "default")
    runs = _run_contexts(root, session_id)
    if runs:
        # Only the newest run is authoritative. An old failure must not
        # resurrect itself after a newer successful conversation turn.
        run = runs[0]
        status = _text(run.get("status")).lower()
        if status in _UNFINISHED:
            checkpoint = _latest_checkpoint(root, session_id)
            return ContinuitySnapshot(True, session_id, _text(run.get("prompt_preview"), 500), status,
                                      _text(run.get("error")), _text(run.get("run_id")), "run_context",
                                      _text(checkpoint.get("file")), "", "logs/run_contexts")
    checkpoint = _latest_checkpoint(root, session_id)
    if checkpoint:
        task = _text(checkpoint.get("context_summary") or checkpoint.get("plan"), 500)
        if task:
            return ContinuitySnapshot(True, session_id, task, "checkpointed", "",
                                      _text(checkpoint.get("turn_id")), "checkpoint",
                                      _text(checkpoint.get("file")), "", ".nexus_v5/checkpoints")
    todo = _todo(root)
    if todo:
        return ContinuitySnapshot(True, session_id, todo["task"], "unfinished", "", "", "todo", "", "", todo["evidence"])
    if queue is not None and hasattr(queue, "list_unfinished"):
        try:
            tasks = queue.list_unfinished(session_id=session_id)
        except Exception:
            tasks = []
        if tasks:
            row = tasks[0]
            payload = row.get("payload") or {}
            return ContinuitySnapshot(True, session_id, _text(payload.get("task_desc"), 500),
                                      _text(row.get("state")), _text(row.get("error")), "", "task_queue", "",
                                      _text(row.get("id")), ".nexus_queue.db")
    return ContinuitySnapshot(session_id=session_id)


__all__ = ["ContinuitySnapshot", "inspect_continuity"]
