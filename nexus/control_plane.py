"""Durable Task -> PlanVersion -> Step control-plane records.

``todo.md`` remains the editable compatibility view, while this module stores
the runtime facts that a checklist cannot express: dependencies, step attempts,
run ownership, and verification evidence.  It deliberately does not depend on
the loop, FastAPI, or a model provider, so every surface can adopt it safely.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional


PLAN_STATUSES = frozenset({"draft", "active", "completed", "superseded", "cancelled"})
STEP_STATUSES = frozenset({"pending", "ready", "running", "waiting", "succeeded", "failed", "blocked", "cancelled", "skipped"})
_STEP_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "skipped"})
_STEP_TRANSITIONS = {
    "pending": {"ready", "blocked", "cancelled", "skipped"},
    "ready": {"running", "blocked", "cancelled", "skipped"},
    "running": {"waiting", "succeeded", "failed", "blocked", "cancelled"},
    "waiting": {"ready", "running", "succeeded", "failed", "blocked", "cancelled"},
    "failed": {"ready", "cancelled", "skipped"},
    "blocked": {"ready", "cancelled", "skipped"},
    "succeeded": set(), "cancelled": set(), "skipped": set(),
}
_RUN_EVENT_TARGETS = {
    "run.started": "running", "run.completed": "succeeded", "run.failed": "failed",
    "run.timed_out": "failed", "run.cancelled": "cancelled",
}


def _now() -> float:
    return time.time()


def _safe_id(value: str, default: str = "default") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())[:120]
    return cleaned or default


def _atomic_write(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@dataclass
class PlanStep:
    step_id: str
    title: str
    description: str = ""
    status: str = "pending"
    dependencies: List[str] = field(default_factory=list)
    assigned_run_id: str = ""
    attempt_run_ids: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    version: int = 0

    def __post_init__(self) -> None:
        self.step_id = _safe_id(self.step_id, "step")
        self.title = str(self.title or "Untitled step").strip()[:300]
        self.description = str(self.description or "")[:4000]
        self.status = str(self.status or "pending").lower()
        if self.status not in STEP_STATUSES:
            raise ValueError(f"Unsupported step status: {self.status!r}")
        self.dependencies = [_safe_id(value, "") for value in self.dependencies if str(value).strip()]
        self.attempt_run_ids = [_safe_id(value, "") for value in self.attempt_run_ids if str(value).strip()]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "PlanStep":
        return cls(**dict(value))


@dataclass
class PlanVersion:
    plan_id: str
    task_id: str
    session_id: str
    root: str
    title: str
    goal: str = ""
    status: str = "draft"
    parent_plan_id: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    version: int = 1

    def __post_init__(self) -> None:
        self.plan_id = _safe_id(self.plan_id, "plan")
        self.task_id = _safe_id(self.task_id, "task")
        self.session_id = _safe_id(self.session_id)
        self.root = os.path.abspath(self.root)
        self.title = str(self.title or "Untitled plan").strip()[:300]
        self.goal = str(self.goal or "")[:4000]
        self.status = str(self.status or "draft").lower()
        if self.status not in PLAN_STATUSES:
            raise ValueError(f"Unsupported plan status: {self.status!r}")
        self.steps = [step if isinstance(step, PlanStep) else PlanStep.from_dict(step) for step in self.steps]
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Plan step ids must be unique")
        known = set(ids)
        for step in self.steps:
            unknown = set(step.dependencies) - known
            if unknown:
                raise ValueError(f"Unknown step dependencies for {step.step_id}: {sorted(unknown)}")

    @property
    def path(self) -> Path:
        return plan_path(self.root, self.session_id, self.plan_id)

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["steps"] = [step.to_dict() for step in self.steps]
        return value

    @classmethod
    def from_dict(cls, value: Dict[str, Any], *, root: Optional[str] = None) -> "PlanVersion":
        data = dict(value)
        if root is not None:
            data["root"] = root
        return cls(**data)

    def step(self, step_id: str) -> PlanStep:
        key = _safe_id(step_id, "")
        for step in self.steps:
            if step.step_id == key:
                return step
        raise KeyError(f"Plan step not found: {step_id}")


_LOCKS: Dict[str, RLock] = {}
_LOCK_GUARD = RLock()


def _lock(path: Path) -> RLock:
    with _LOCK_GUARD:
        return _LOCKS.setdefault(str(path), RLock())


def plan_path(root: str, session_id: str, plan_id: str) -> Path:
    return Path(os.path.abspath(root)) / ".nexus" / "plans" / _safe_id(session_id) / f"{_safe_id(plan_id)}.json"


def persist_plan(plan: PlanVersion) -> Path:
    path = plan.path
    with _lock(path):
        _atomic_write(path, plan.to_dict())
    return path


def load_plan(root: str, session_id: str, plan_id: str) -> Optional[PlanVersion]:
    path = plan_path(root, session_id, plan_id)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return PlanVersion.from_dict(json.load(handle), root=root)
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid plan state at {path}: {exc}") from exc


def list_plans(root: str, session_id: str = "", limit: int = 100) -> List[PlanVersion]:
    base = Path(os.path.abspath(root)) / ".nexus" / "plans"
    folders: Iterable[Path] = [base / _safe_id(session_id)] if session_id else (base.iterdir() if base.is_dir() else [])
    result: List[PlanVersion] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    result.append(PlanVersion.from_dict(json.load(handle), root=root))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
    result.sort(key=lambda item: item.updated_at, reverse=True)
    return result[:max(1, min(int(limit or 100), 1000))]


def create_plan_version(*, root: str, session_id: str, task_id: str, title: str, goal: str = "", steps: Iterable[Dict[str, Any] | PlanStep] = (), parent_plan_id: str = "", status: str = "active", plan_id: str = "") -> PlanVersion:
    values: List[PlanStep] = []
    for index, raw in enumerate(steps, start=1):
        if isinstance(raw, PlanStep):
            step = raw
        else:
            value = dict(raw)
            value.setdefault("step_id", f"step_{index}")
            step = PlanStep.from_dict(value)
        values.append(step)
    plan = PlanVersion(plan_id=plan_id or f"plan_{uuid.uuid4().hex[:12]}", task_id=task_id, session_id=session_id, root=root, title=title, goal=goal, status=status, parent_plan_id=parent_plan_id, steps=values)
    if load_plan(root, session_id, plan.plan_id) is not None:
        raise FileExistsError(f"Plan already exists: {plan.plan_id}")
    persist_plan(plan)
    return plan


def create_checklist_plan(*, root: str, session_id: str, title: str, goal: str, rows: Iterable[Dict[str, Any]]) -> PlanVersion:
    """Version a Markdown checklist without making Markdown runtime truth.

    Checklist marks are kept as import metadata only.  A checked box is not
    execution evidence and therefore cannot manufacture ``succeeded`` here.
    """
    prior = next((plan for plan in list_plans(root, session_id) if plan.status == "active"), None)
    if prior is not None:
        prior.status = "superseded"
        prior.updated_at = _now()
        prior.version += 1
        persist_plan(prior)
    normalized_rows = list(rows)
    steps = [
        {
            "step_id": str(row.get("id") or f"step_{index}"),
            "title": str(row.get("title") or "Untitled step"),
            "metadata": {"checklist_status": str(row.get("status") or "pending"), "ordinal": index},
        }
        for index, row in enumerate(normalized_rows, start=1)
    ]
    return create_plan_version(
        root=root, session_id=session_id, task_id="checklist",
        title=title or "Checklist plan", goal=goal or title,
        steps=steps, parent_plan_id=prior.plan_id if prior else "", status="active",
    )


def ready_steps(plan: PlanVersion) -> List[PlanStep]:
    succeeded = {step.step_id for step in plan.steps if step.status == "succeeded"}
    return [step for step in plan.steps if step.status in {"pending", "ready"} and set(step.dependencies).issubset(succeeded)]


def transition_step(*, root: str, session_id: str, plan_id: str, step_id: str, status: str, run_id: str = "", evidence: Optional[Dict[str, Any]] = None, reason: str = "") -> PlanVersion:
    path = plan_path(root, session_id, plan_id)
    with _lock(path):
        plan = load_plan(root, session_id, plan_id)
        if plan is None:
            raise KeyError(f"Plan not found: {plan_id}")
        step = plan.step(step_id)
        target = str(status or "").lower()
        if target not in STEP_STATUSES:
            raise ValueError(f"Unsupported step status: {status!r}")
        if target in {"ready", "running"} and not set(step.dependencies).issubset({item.step_id for item in plan.steps if item.status == "succeeded"}):
            raise ValueError(f"Step dependencies are not complete: {step.step_id}")
        if target != step.status and target not in _STEP_TRANSITIONS[step.status]:
            raise ValueError(f"Invalid step transition: {step.status} -> {target}")
        if run_id:
            normalized = _safe_id(run_id, "")
            if step.assigned_run_id and step.assigned_run_id != normalized and step.status not in {"failed", "blocked"}:
                raise ValueError(f"Step is already owned by run: {step.assigned_run_id}")
            step.assigned_run_id = normalized
            if normalized not in step.attempt_run_ids:
                step.attempt_run_ids.append(normalized)
        step.status = target
        if evidence is not None:
            step.evidence.append(dict(evidence))
        if reason:
            step.metadata = {**step.metadata, "last_transition_reason": str(reason)[:1000]}
        step.updated_at = _now(); step.version += 1
        plan.updated_at = step.updated_at; plan.version += 1
        if all(item.status in _STEP_TERMINAL for item in plan.steps) and all(item.status in {"succeeded", "skipped"} for item in plan.steps):
            plan.status = "completed"
        persist_plan(plan)
        return plan


def project_plan_event(*, root: str, session_id: str, event: Dict[str, Any]) -> Optional[PlanVersion]:
    """Apply an optional plan/step lifecycle projection from a canonical event."""
    if not isinstance(event, dict):
        return None
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    plan_id = str(event.get("plan_id") or payload.get("plan_id") or "").strip()
    step_id = str(event.get("step_id") or payload.get("step_id") or "").strip()
    event_type = str(event.get("event_type") or event.get("type") or "").lower()
    target = _RUN_EVENT_TARGETS.get(event_type)
    if not plan_id or not step_id or not target:
        return None
    run_id = str(event.get("run_id") or payload.get("run_id") or "")
    try:
        # Runtime evidence that a run began is allowed to perform the same
        # bookkeeping bridge as the existing WorkItem projector.  It never
        # bypasses dependencies, and terminal events still require a prior
        # compatible execution state.
        plan = load_plan(root, session_id, plan_id)
        if plan is not None and target == "running":
            step = plan.step(step_id)
            if step.status == "pending":
                transition_step(root=root, session_id=session_id, plan_id=plan_id, step_id=step_id, status="ready", reason="projected run.started readiness bridge")
        return transition_step(root=root, session_id=session_id, plan_id=plan_id, step_id=step_id, status=target, run_id=run_id, evidence={"event_id": str(event.get("event_id") or event.get("id") or ""), "event_type": event_type, "at": _now()}, reason=f"projected {event_type}")
    except (KeyError, ValueError):
        return None
