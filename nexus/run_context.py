from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from nexus.runtime import safe_session_id


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())
    return safe[:120] or "default"


@dataclass
class RunContext:
    """Durable identity and terminal status for a single agent run."""

    run_id: str
    session_id: str
    root: str
    task_id: str = ""
    provider: str = ""
    model: str = ""
    max_tokens: Optional[int] = None
    voice_mode: bool = False
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    terminal_event: str = ""
    error: str = ""
    prompt_preview: str = ""
    owner_process_id: int = 0
    lease_expires_at: Optional[float] = None

    @property
    def path(self) -> str:
        return run_context_path(self.root, self.session_id, self.run_id)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def _persist_payload(self, payload: Dict[str, Any]) -> None:
        """Atomically write a payload; caller owns the interprocess lock."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = f"{self.path}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def persist(self) -> None:
        with _run_context_lock(self.path):
            self._persist_payload(self.to_dict())

    def finish(self, status: str, terminal_event: str, error: str = "") -> bool:
        now = time.time()
        if self.owner_process_id and self.owner_process_id != os.getpid():
            return False
        with _run_context_lock(self.path):
            current = _read_run_context_payload(self.path)
            if current:
                if str(current.get("status") or "").lower() != "running":
                    return False
                current_owner = int(current.get("owner_process_id") or 0)
                if current_owner and current_owner != os.getpid():
                    return False
                payload = current
            else:
                payload = self.to_dict()
            payload.update({
                "status": str(status or "failed"),
                "terminal_event": str(terminal_event or ""),
                "error": str(error or "")[:1000],
                "updated_at": now,
                "completed_at": now,
                "lease_expires_at": None,
            })
            self._persist_payload(payload)
            for key, value in payload.items():
                if hasattr(self, key):
                    setattr(self, key, value)
            return True

    def heartbeat(self, lease_seconds: float = 900.0) -> bool:
        """Renew ownership while a process is actively executing this run."""
        if str(self.status or "").lower() != "running":
            return False
        if self.owner_process_id and self.owner_process_id != os.getpid():
            return False
        now = time.time()
        with _run_context_lock(self.path):
            current = _read_run_context_payload(self.path)
            if current:
                if str(current.get("status") or "").lower() != "running":
                    return False
                current_owner = int(current.get("owner_process_id") or 0)
                if current_owner and current_owner != os.getpid():
                    return False
                payload = current
            else:
                payload = self.to_dict()
            payload.update({
                "owner_process_id": os.getpid(),
                "updated_at": now,
                "lease_expires_at": now + max(1.0, float(lease_seconds)),
            })
            self._persist_payload(payload)
            self.owner_process_id = os.getpid()
            self.updated_at = now
            self.lease_expires_at = payload["lease_expires_at"]
            return True

@contextmanager
def _run_context_lock(path: str):
    """Serialize run-context transitions across threads and processes."""
    lock_path = f"{path}.lock.sqlite"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    connection = sqlite3.connect(lock_path, timeout=60.0, isolation_level=None)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS run_context_mutex "
            "(id INTEGER PRIMARY KEY CHECK (id = 1))"
        )
        connection.execute("INSERT OR IGNORE INTO run_context_mutex(id) VALUES (1)")
        connection.execute("BEGIN IMMEDIATE")
        yield
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def _read_run_context_payload(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def run_context_path(root: str, session_id: str, run_id: str) -> str:
    return os.path.join(
        os.path.abspath(root),
        "logs",
        "run_contexts",
        safe_session_id(session_id),
        f"{_safe_id(run_id)}.json",
    )


def _session_context_dirs(root: str, session_id: str) -> List[str]:
    """Return canonical and pre-normalization session directories."""
    base = os.path.join(os.path.abspath(root), "logs", "run_contexts")
    canonical = os.path.join(base, safe_session_id(session_id))
    legacy = os.path.join(base, _safe_id(session_id))
    return [canonical] if legacy == canonical else [canonical, legacy]


def start_run_context(
    *,
    root: str,
    session_id: str,
    run_id: str,
    task_id: str = "",
    prompt: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    voice_mode: bool = False,
    lease_seconds: Optional[float] = None,
) -> RunContext:
    context = RunContext(
        root=os.path.abspath(root),
        session_id=safe_session_id(session_id),
        run_id=_safe_id(run_id),
        task_id=_safe_id(task_id) if task_id else "",
        provider=str(provider or ""),
        model=str(model or ""),
        max_tokens=max_tokens,
        voice_mode=voice_mode,
        prompt_preview=str(prompt or "").strip().replace("\r", " ").replace("\n", " ")[:240],
        owner_process_id=os.getpid() if lease_seconds else 0,
        lease_expires_at=(time.time() + max(1.0, float(lease_seconds))) if lease_seconds else None,
    )
    context.persist()
    return context


def load_run_context(root: str, session_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    for directory in _session_context_dirs(root, session_id):
        path = os.path.join(directory, f"{_safe_id(run_id)}.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            return loaded if isinstance(loaded, dict) else None
        except FileNotFoundError:
            continue
    return None


def list_run_contexts(root: str, session_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    base = os.path.join(os.path.abspath(root), "logs", "run_contexts")
    roots = []
    if session_id:
        roots.extend(_session_context_dirs(root, session_id))
    elif os.path.isdir(base):
        roots.extend(
            os.path.join(base, name)
            for name in os.listdir(base)
            if os.path.isdir(os.path.join(base, name))
        )
    contexts: List[Dict[str, Any]] = []
    for folder in roots:
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.endswith(".json"):
                continue
            path = os.path.join(folder, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    loaded["_path"] = path
                    contexts.append(loaded)
            except (OSError, json.JSONDecodeError):
                continue
    contexts.sort(key=lambda item: float(item.get("updated_at") or item.get("started_at") or 0), reverse=True)
    return contexts[: max(1, min(int(limit or 100), 1000))]


def recover_orphaned_runs(
    *, root: str, session_id: str = "", event_log_dir: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Recover persisted runs left active by a previous process crash.

    A newly constructed loop is not an execution owner for an old in-memory
    run.  Marking that run failed is safer and more truthful than exposing a
    permanent ``running`` state.  Recovery is idempotent: the deterministic
    recovery event is written once and WorkItem projection ignores delayed
    terminal events from the retired run.
    """
    from nexus.work_items import project_work_item_event

    recovered: List[Dict[str, Any]] = []
    contexts = list_run_contexts(root, session_id=session_id, limit=1000)
    now = time.time()
    for data in contexts:
        if str(data.get("status") or "").lower() != "running":
            continue
        # A different server process may legitimately own this run.  Only an
        # expired (or legacy lease-less) record is eligible for recovery.
        try:
            lease_expires_at = float(data.get("lease_expires_at") or 0)
        except (TypeError, ValueError):
            lease_expires_at = 0
        if lease_expires_at > now:
            continue
        run_id = _safe_id(str(data.get("run_id") or ""))
        sid = safe_session_id(str(data.get("session_id") or session_id or "default"))
        if not run_id:
            continue
        context = RunContext(
            run_id=run_id,
            session_id=sid,
            root=os.path.abspath(root),
            task_id=str(data.get("task_id") or ""),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            max_tokens=data.get("max_tokens"),
            voice_mode=bool(data.get("voice_mode", False)),
            status="running",
            started_at=float(data.get("started_at") or time.time()),
            updated_at=float(data.get("updated_at") or data.get("started_at") or time.time()),
            prompt_preview=str(data.get("prompt_preview") or ""),
            owner_process_id=int(data.get("owner_process_id") or 0),
            lease_expires_at=lease_expires_at or None,
        )
        event_id = f"recovery_{run_id}"
        event = {
            "id": event_id,
            "event_id": event_id,
            "event_type": "run.failed",
            "type": "run.failed",
            "kind": "run",
            "title": "Run recovered after process restart",
            "status": "failed",
            "run_id": run_id,
            "turn_id": run_id,
            "task_id": str(data.get("task_id") or ""),
            "error": "process restarted before terminal event",
            "visibility": "public",
        }
        log_dir = os.path.abspath(event_log_dir or os.path.join(root, "workspace", "work_events"))
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"{sid}.jsonl")
        already_written = False
        sequence = 0
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        prior = json.loads(line)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(prior, dict):
                        try:
                            sequence = max(sequence, int(prior.get("sequence") or 0))
                        except (TypeError, ValueError):
                            pass
                        if str(prior.get("event_id") or prior.get("id") or "") == event_id:
                            already_written = True
        except FileNotFoundError:
            pass
        if not already_written:
            transitioned = context.finish(
                "failed", "run.failed", "process restarted before terminal event"
            )
            if not transitioned:
                # A live owner may have renewed or completed the run after
                # the initial scan. Do not emit a stale recovery event.
                continue
        event["sequence"] = sequence + (0 if already_written else 1)
        if not already_written:
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        project_work_item_event(root=os.path.abspath(root), session_id=sid, event=event)
        if not already_written:
            recovered.append(event)
    return recovered
