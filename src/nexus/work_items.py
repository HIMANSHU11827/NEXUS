"""Durable task/work-item state for the Nexus execution control plane.

This module deliberately has no model, server, or tool dependencies.  It is a
small persistence boundary that can be adopted by the V5 loop incrementally:
task identity and lifecycle survive process restarts without making the
existing todo.md or run-context formats invalid.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional


logger = logging.getLogger(__name__)


WORK_ITEM_STATUSES = frozenset(
    {
        "draft",
        "planned",
        "approved",
        "running",
        "waiting",
        "ready_for_review",
        "applied",
        "failed",
        "cancelled",
    }
)

_TRANSITIONS = {
    "draft": {"planned", "cancelled"},
    "planned": {"approved", "draft", "failed", "cancelled"},
    "approved": {"running", "failed", "cancelled"},
    "running": {"waiting", "ready_for_review", "applied", "failed", "cancelled"},
    "waiting": {"running", "cancelled", "failed"},
    "ready_for_review": {"applied", "running", "failed", "cancelled"},
    "applied": set(),
    "failed": {"planned", "approved", "cancelled"},
    "cancelled": {"planned"},
}

# Run events are an external projection input, not a second planner.  Keep
# their accepted progression deliberately narrow and one-way.
_RUN_EVENT_TARGETS = {
    "run.started": "running",
    "run.completed": "applied",
    "run.failed": "failed",
    "run.timed_out": "failed",
    "run.cancelled": "cancelled",
}
_TERMINAL_STATUSES = frozenset({"applied", "failed", "cancelled"})


def _event_sequence(event: Dict[str, Any]) -> int:
    """Return a safe ordering key for untrusted JSONL records."""
    try:
        value = int(event.get("sequence") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0
    return value if value >= 0 else 0


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())
    return cleaned[:120] or "default"


def _now() -> float:
    return time.time()


def _projection_failure_key(event: Dict[str, Any]) -> str:
    """Return a stable key for a failed event, including legacy records."""
    event_id = str(event.get("event_id") or event.get("id") or "").strip()
    if event_id:
        return event_id[:240]
    return ":".join(
        (
            str(event.get("sequence") or "0"),
            str(event.get("task_id") or ""),
            str(event.get("event_type") or event.get("type") or ""),
        )
    )[:240]


def _projection_failure_path(event_log_path: str) -> Path:
    return Path(f"{event_log_path}.projection-failures.json")


def _read_projection_failures(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _write_projection_failures(path: Path, failures: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(failures, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _projection_retry_delay(attempts: int) -> float:
    """Bound retries so a permanently malformed event cannot hot-loop."""
    return (1.0, 5.0, 30.0, 300.0)[min(max(attempts, 1), 4) - 1]


def record_work_item_projection_failure(*, event_log_path: str, event: Dict[str, Any], error: Exception) -> Dict[str, Any]:
    """Persist a bounded-backoff retry record for a failed projection."""
    path = _projection_failure_path(event_log_path)
    with _interprocess_projection_lock(path):
        failures = _read_projection_failures(path)
        key = _projection_failure_key(event)
        previous = failures.get(key, {})
        try:
            previous_attempts = int(previous.get("attempts") or 0)
        except (TypeError, ValueError):
            previous_attempts = 0
        attempts = max(previous_attempts, 0) + 1
        record = {
            "event_id": key,
            "event_type": str(event.get("event_type") or event.get("type") or ""),
            "task_id": str(event.get("task_id") or ""),
            "attempts": attempts,
            "last_error": str(error)[:1000],
            "last_failed_at": _now(),
        }
        record["next_retry_at"] = record["last_failed_at"] + _projection_retry_delay(attempts)
        failures[key] = record
        _write_projection_failures(path, failures)
        return record


def clear_work_item_projection_failure(*, event_log_path: str, event: Dict[str, Any]) -> None:
    """Remove a retry record after the event projects successfully."""
    path = _projection_failure_path(event_log_path)
    with _interprocess_projection_lock(path):
        failures = _read_projection_failures(path)
        if _projection_failure_key(event) not in failures:
            return
        failures.pop(_projection_failure_key(event), None)
        if failures:
            _write_projection_failures(path, failures)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def pending_work_item_projection_failures(*, event_log_path: str) -> List[Dict[str, Any]]:
    """Return durable projection failures for diagnostics and API status."""
    path = _projection_failure_path(event_log_path)
    with _interprocess_projection_lock(path):
        failures = list(_read_projection_failures(path).values())
    return sorted(failures, key=lambda item: float(item.get("last_failed_at") or 0.0))


@dataclass
class WorkItem:
    """A durable unit of planned work with explicit lifecycle semantics."""

    task_id: str
    session_id: str
    root: str
    title: str
    description: str = ""
    status: str = "draft"
    run_id: str = ""
    parent_run_id: str = ""
    plan_id: str = ""
    workspace: str = ""
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    completed_at: Optional[float] = None
    version: int = 0

    def __post_init__(self) -> None:
        self.task_id = _safe_id(self.task_id)
        self.session_id = _safe_id(self.session_id)
        self.root = os.path.abspath(self.root)
        self.title = str(self.title or "Untitled").strip()[:240]
        self.description = str(self.description or "")[:4000]
        self.status = str(self.status or "draft").strip().lower()
        if self.status not in WORK_ITEM_STATUSES:
            raise ValueError(f"Unsupported work-item status: {self.status!r}")
        self.dependencies = [_safe_id(item) for item in self.dependencies if str(item).strip()]

    @property
    def path(self) -> Path:
        return work_item_path(self.root, self.session_id, self.task_id)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, root: Optional[str] = None) -> "WorkItem":
        if not isinstance(data, dict):
            raise ValueError("work-item data must be an object")
        values = dict(data)
        if root is not None:
            values["root"] = root
        values.pop("_path", None)
        return cls(**values)

    def transition(self, status: str, *, run_id: Optional[str] = None, reason: str = "") -> "WorkItem":
        target = str(status or "").strip().lower()
        if target not in WORK_ITEM_STATUSES:
            raise ValueError(f"Unsupported work-item status: {status!r}")
        if target != self.status and target not in _TRANSITIONS[self.status]:
            raise ValueError(f"Invalid work-item transition: {self.status} -> {target}")
        # Reopening a failed/cancelled item starts a new execution attempt.
        # Keeping the old run id would make the next run look foreign to the
        # event projector and would also allow stale events to be associated
        # with the reopened checklist item.
        if target == "planned" and self.status in {"failed", "cancelled"}:
            retired = self.metadata.get("_retired_run_ids", [])
            if not isinstance(retired, list):
                retired = []
            if self.run_id and self.run_id not in retired:
                # Unlike the bounded event-id cache below, run tombstones
                # must not be evicted: an arbitrarily delayed event from a
                # previous attempt must never become authoritative after a
                # retry.  This list is kept only for run ids, not payloads.
                self.metadata = {
                    **self.metadata,
                    "_retired_run_ids": [*retired, self.run_id],
                }
            self.run_id = ""
        self.status = target
        if run_id is not None:
            self.run_id = _safe_id(run_id) if run_id else ""
        if reason:
            self.metadata = {**self.metadata, "last_transition_reason": str(reason)[:1000]}
        self.updated_at = _now()
        self.version += 1
        if target in {"applied", "failed", "cancelled"}:
            self.completed_at = self.updated_at
        elif target not in {"applied", "failed", "cancelled"}:
            self.completed_at = None
        return self


_LOCKS: Dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, RLock())


@contextmanager
def _interprocess_projection_lock(path: Path):
    """Serialize one WorkItem projection across server worker processes."""
    lock_path = f"{path}.lock.sqlite"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    connection = sqlite3.connect(lock_path, timeout=60.0, isolation_level=None)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS work_item_mutex "
            "(id INTEGER PRIMARY KEY CHECK (id = 1))"
        )
        connection.execute("INSERT OR IGNORE INTO work_item_mutex(id) VALUES (1)")
        connection.execute("BEGIN IMMEDIATE")
        yield
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def work_item_path(root: str, session_id: str, task_id: str) -> Path:
    return Path(os.path.abspath(root)) / ".nexus" / "work_items" / _safe_id(session_id) / f"{_safe_id(task_id)}.json"


def _persist_work_item_unlocked(item: WorkItem) -> Path:
    path = item.path
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(path)
    with lock:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(item.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return path


def persist_work_item(item: WorkItem) -> Path:
    """Persist a WorkItem under the same interprocess projection mutex."""
    with _interprocess_projection_lock(item.path):
        return _persist_work_item_unlocked(item)


def load_work_item(root: str, session_id: str, task_id: str) -> Optional[WorkItem]:
    path = work_item_path(root, session_id, task_id)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return WorkItem.from_dict(data, root=root)
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid work-item state at {path}: {exc}") from exc


def list_work_items(root: str, session_id: str = "", limit: int = 100) -> List[WorkItem]:
    base = Path(os.path.abspath(root)) / ".nexus" / "work_items"
    folders: Iterable[Path]
    if session_id:
        folders = [base / _safe_id(session_id)]
    elif base.is_dir():
        folders = [item for item in base.iterdir() if item.is_dir()]
    else:
        folders = []
    result: List[WorkItem] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    result.append(WorkItem.from_dict(data, root=root))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
    result.sort(key=lambda item: item.updated_at, reverse=True)
    return result[: max(1, min(int(limit or 100), 1000))]


def create_work_item(
    *, root: str, session_id: str, title: str, description: str = "", task_id: str = "", **kwargs: Any
) -> WorkItem:
    item = WorkItem(
        task_id=_safe_id(task_id) if task_id else f"task_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        root=root,
        title=title,
        description=description,
        **kwargs,
    )
    path = item.path
    with _interprocess_projection_lock(path):
        if load_work_item(root, session_id, item.task_id) is not None:
            raise FileExistsError(f"Work item already exists: {item.task_id}")
        _persist_work_item_unlocked(item)
    return item


def reconcile_checklist_work_item(
    *, root: str, session_id: str = "default", task_id: str, title: str,
    checklist_status: str = "pending", plan_id: str = "",
) -> WorkItem:
    """Create/update the durable projection of one todo.md checklist row."""
    status_map = {
        "pending": "planned",
        "in_progress": "running",
        "completed": "applied",
        "done": "applied",
    }
    target = status_map.get(str(checklist_status or "pending").lower(), "planned")
    path = work_item_path(root, session_id, task_id)
    # The planner and TaskTool can run in separate worker processes.  The
    # entire load/transition/save cycle must be serialized, not just the JSON
    # replace, otherwise concurrent checklist updates can lose a terminal
    # run result or resurrect stale state.
    with _interprocess_projection_lock(path):
        item = load_work_item(root, session_id, task_id)
        if item is None:
            item = WorkItem(task_id=task_id, session_id=session_id, root=root, title=title, status="draft", plan_id=plan_id)
        item.title = str(title or item.title or "Untitled").strip()[:240]
        if plan_id:
            item.plan_id = str(plan_id)[:120]

        # An explicit new checklist plan may reopen a failed/cancelled item,
        # but the prior run identity must remain retired so delayed terminal
        # events cannot claim the new attempt after the event-id ledger rolls.
        if target == "planned" and item.status in {"failed", "cancelled"}:
            retired = item.metadata.get("_retired_run_ids", [])
            if not isinstance(retired, list):
                retired = []
            if item.run_id and item.run_id not in retired:
                # Run tombstones are permanent.  Event-id retention may be
                # bounded, but a delayed event from any prior retry must
                # never reclaim a task after enough later retries.
                retired = retired + [item.run_id]
            item.metadata = {**item.metadata, "_retired_run_ids": retired}
            item.run_id = ""
            item.transition("planned", reason="new checklist attempt")
            _persist_work_item_unlocked(item)
            return item

    # A checklist is a planning projection, not proof that an execution run
    # succeeded.  Once a run owns the item, a stale/manual ``[x]`` must not
    # synthesize ``applied``; the canonical run-event projector owns that
    # terminal outcome.  Keep writing todo.md for legacy compatibility, but
    # leave the run-owned lifecycle state untouched until its terminal event.
        if target == "applied" and item.run_id and item.status not in _TERMINAL_STATUSES:
            _persist_work_item_unlocked(item)
            return item

        if target != item.status:
            try:
                if item.status == "draft" and target in {"planned", "running", "applied"}:
                    item.transition("planned", reason="todo.md reconciliation")
                if item.status == "planned" and target in {"running", "applied"}:
                    item.transition("approved", reason="todo.md reconciliation")
                if item.status == "approved" and target in {"running", "applied"}:
                    item.transition("running", reason="todo.md reconciliation")
                if item.status != target:
                    item.transition(target, reason="todo.md reconciliation")
            except ValueError:
                # A terminal run outcome is authoritative until a new explicit
                # execution starts; do not rewrite it from a stale checklist mark.
                if item.status in {"running", "waiting", "ready_for_review", "applied"}:
                    _persist_work_item_unlocked(item)
                    return item
                if item.status not in {"failed", "cancelled"}:
                    raise
        _persist_work_item_unlocked(item)
        return item


def _project_work_item_event_unlocked(
    *, root: str, session_id: str, event: Dict[str, Any]
) -> Optional[WorkItem]:
    """Project one canonical/public run event onto its durable WorkItem.

    This function is intentionally persistence-only: it never emits or
    appends an event, so callers can safely invoke it from an event sink.
    Events without explicit ``task_id`` and ``run_id`` identity are ignored.
    Repeated event IDs are no-ops, and stale/invalid lifecycle transitions are
    ignored rather than rewriting planner state.
    """
    if not isinstance(event, dict):
        return None
    nested = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    task_id = str(event.get("task_id") or nested.get("task_id") or "").strip()
    run_id = str(event.get("run_id") or "").strip()
    event_id = str(event.get("event_id") or event.get("id") or "").strip()
    event_type = str(event.get("event_type") or event.get("type") or "").strip().lower()
    if not task_id or not run_id or not event_id:
        return None
    target = _RUN_EVENT_TARGETS.get(event_type)
    if target is None:
        return None

    item = load_work_item(root, session_id, task_id)
    if item is None:
        return None
    retired = item.metadata.get("_retired_run_ids", [])
    if isinstance(retired, list) and _safe_id(run_id) in {_safe_id(value) for value in retired}:
        # A delayed event from an older retry is never allowed to claim a
        # freshly reopened item, even after its event-id cache has rotated.
        return None
    if item.run_id and item.run_id != _safe_id(run_id):
        # A WorkItem is not reopened or reassigned by a stale/foreign run.
        return None

    seen = item.metadata.get("_projected_work_event_ids", [])
    if not isinstance(seen, list):
        seen = []
    if event_id in seen:
        return item

    # Terminal states are authoritative.  In particular, replaying an older
    # run.started after a terminal event must not reopen the task.
    if item.status in _TERMINAL_STATUSES and target != item.status:
        return None
    if target == "running" and item.status in {"waiting", "ready_for_review"}:
        return None

    # Planner/task reconciliation intentionally creates checklist items in
    # ``planned``.  A canonical run.started event is authoritative evidence
    # that execution has begun, so bridge the approval bookkeeping step before
    # applying the normal approved -> running transition.  This keeps the
    # WorkItem transition graph valid without requiring planner callers to
    # know runtime lifecycle internals.
    if target == "running" and item.status == "planned":
        item.transition("approved", reason="projected run.started approval bridge")

    if target not in {item.status, *(_TRANSITIONS.get(item.status, set()))}:
        return None

    normalized_run_id = _safe_id(run_id)
    if target == item.status and item.run_id == normalized_run_id:
        # A duplicate or late replay of an already-applied state must be a
        # true no-op. Rewriting updated_at (or the idempotency ledger) here
        # makes normal persisted replay visibly drift the WorkItem.
        return item

    if target != item.status:
        item.transition(target, run_id=run_id, reason=f"projected {event_type}")
    elif item.run_id != normalized_run_id:
        item.run_id = _safe_id(run_id)
    else:
        # Same-state lifecycle events still bind an unassigned run without
        # manufacturing a lifecycle transition/version bump.
        item.updated_at = _now()

    item.metadata = {
        **item.metadata,
        "_projected_work_event_ids": (seen + [event_id])[-256:],
    }
    _persist_work_item_unlocked(item)
    return item


def project_work_item_event(
    *, root: str, session_id: str, event: Dict[str, Any]
) -> Optional[WorkItem]:
    """Project one event while serializing the load/transition/save cycle."""
    if not isinstance(event, dict):
        return None
    nested = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    task_id = str(event.get("task_id") or nested.get("task_id") or "").strip()
    if not task_id:
        return _project_work_item_event_unlocked(root=root, session_id=session_id, event=event)
    path = work_item_path(root, session_id, task_id)
    with _interprocess_projection_lock(path):
        return _project_work_item_event_unlocked(root=root, session_id=session_id, event=event)


def replay_work_item_event_log(
    *, root: str, session_id: str, event_log_path: str, limit: int = 10000
) -> int:
    """Replay durable lifecycle events into WorkItems after restart.

    The append path normally projects events immediately, but a process can
    crash between event fsync and projection.  Recovery reads the append-only
    log in sequence order, skips malformed/partial lines, and relies on the
    WorkItem event-id ledger for idempotency.  It returns the number of valid
    lifecycle records encountered, not the number of state mutations.
    """
    records: List[Dict[str, Any]] = []
    try:
        with open(event_log_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if len(records) >= max(1, min(int(limit or 10000), 100000)):
                    break
                try:
                    event = json.loads(line)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if str(event.get("event_type") or event.get("type") or "").lower() not in _RUN_EVENT_TARGETS:
                    continue
                records.append(event)
    except OSError:
        return 0

    records.sort(key=_event_sequence)
    failure_path = _projection_failure_path(event_log_path)
    failures = _read_projection_failures(failure_path)
    now = _now()
    for event in records:
        key = _projection_failure_key(event)
        retry_at = float(failures.get(key, {}).get("next_retry_at") or 0.0)
        if retry_at > now:
            continue
        try:
            project_work_item_event(root=root, session_id=session_id, event=event)
            clear_work_item_projection_failure(event_log_path=event_log_path, event=event)
        except Exception as exc:
            # One corrupt item or transient projection failure must not prevent
            # later terminal events from being recovered. The append-only log
            # remains the durable retry source for this failed event.
            logger.warning(
                "WorkItem event projection failed during replay: %s",
                event.get("event_id") or event.get("id") or "unknown",
                exc_info=True,
            )
            record_work_item_projection_failure(
                event_log_path=event_log_path,
                event=event,
                error=exc,
            )
    return len(records)
