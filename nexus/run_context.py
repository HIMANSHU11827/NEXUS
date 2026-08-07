from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


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

    def persist(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = self.to_dict()
        temporary = f"{self.path}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def finish(self, status: str, terminal_event: str, error: str = "") -> None:
        now = time.time()
        self.status = status
        self.terminal_event = terminal_event
        self.error = str(error or "")[:1000]
        self.updated_at = now
        self.completed_at = now
        self.lease_expires_at = None
        self.persist()

    def heartbeat(self, lease_seconds: float = 900.0) -> None:
        """Renew ownership while a process is actively executing this run."""
        now = time.time()
        self.owner_process_id = os.getpid()
        self.updated_at = now
        self.lease_expires_at = now + max(1.0, float(lease_seconds))
        self.persist()


def run_context_path(root: str, session_id: str, run_id: str) -> str:
    return os.path.join(
        os.path.abspath(root),
        "logs",
        "run_contexts",
        _safe_id(session_id),
        f"{_safe_id(run_id)}.json",
    )


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
        session_id=_safe_id(session_id),
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
    path = run_context_path(root, session_id, run_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else None
    except FileNotFoundError:
        return None


def list_run_contexts(root: str, session_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    base = os.path.join(os.path.abspath(root), "logs", "run_contexts")
    roots = []
    if session_id:
        roots.append(os.path.join(base, _safe_id(session_id)))
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
        sid = _safe_id(str(data.get("session_id") or session_id or "default"))
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
            context.finish("failed", "run.failed", "process restarted before terminal event")
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
