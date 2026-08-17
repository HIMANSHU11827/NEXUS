"""Long-horizon mission runner for NEXUS.

Turns one epic goal ("build GTA 5") into a durable, self-driving plan of
milestones that run 24/7 through the same SQLite task queue as everything
else in NEXUS. A mission never abandons its goal while work remains: sub-tasks
are queued with a stable ``payload.meta.mission`` tag, completed milestones are
recorded in a persistent ledger, and a milestone that keeps failing is
re-planned (with an explicit plan-revision counter) instead of the mission
giving up.

Design goals
------------
* One goal, many milestones, one durable queue.
* Survives process crash / OS reboot — the mission ledger and the task queue
  are both on disk; ``hydrate_active()`` re-enqueues unfinished milestones on
  the next start.
* Multi-tasking: many missions share the queue; priority picks the next task.
* Never gives up: a mission stays ``active`` while any milestone is pending or
  running. Only all-milestones-complete transitions it to ``completed``.
* Honest failure: a milestone with exhausted replans is ``blocked`` with a
  reason, but other milestones continue and the mission keeps running.

Stdlib only. No network. No LLM dependency — the milestone planner accepts an
explicit plan; when none is supplied it seeds a generic engineering skeleton so
a mission is never empty.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .store import TaskQueue

log = logging.getLogger("nexus.queue.mission")

# ---------------------------------------------------------------------- #
# default milestone skeleton (used when a goal has no explicit plan)
# ---------------------------------------------------------------------- #
DEFAULT_MILESTONES = [
    "Design the system: write a plan defining modules, interfaces, data model, and acceptance criteria.",
    "Scaffold the project: create the repository layout, package metadata, config, and entry points.",
    "Implement the core module with unit tests proving the primary happy path.",
    "Implement module 2: the next highest-risk sub-system, with tests.",
    "Implement module 3: remaining critical functionality, with tests.",
    "Integrate modules: wire end-to-end flow and fix integration issues.",
    "Harden: error handling, validation, edge cases, cleanup paths.",
    "Polish: docs, examples, final end-to-end verification against the acceptance criteria.",
]


def ensure_mission_root(root: Optional[str] = None) -> str:
    base = root or os.environ.get("NEXUS_ROOT") or os.path.expanduser("~")
    mission_dir = os.path.join(base, "data", "missions")
    try:
        os.makedirs(mission_dir, exist_ok=True)
    except OSError:
        mission_dir = os.path.join(os.path.expanduser("~"), ".nexus", "missions")
        try:
            os.makedirs(mission_dir, exist_ok=True)
        except OSError:
            mission_dir = "/tmp/nexus-missions"
            os.makedirs(mission_dir, exist_ok=True)
    return mission_dir


@dataclass
class Milestone:
    """One sub-task of a mission."""

    index: int
    task_desc: str
    status: str = "pending"          # pending|queued|running|done|blocked
    attempts: int = 0
    replans: int = 0
    last_error: str = ""
    last_queued_task_id: Optional[int] = None
    done_at: Optional[float] = None
    verification: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Mission:
    """A persistent long-horizon goal."""

    id: str
    goal: str
    milestones: List[Milestone] = field(default_factory=list)
    status: str = "active"           # active|completed|paused
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    max_replans: int = 3
    completed_at: Optional[float] = None

    @property
    def done_count(self) -> int:
        return sum(1 for m in self.milestones if m.status == "done")

    @property
    def total(self) -> int:
        return max(1, len(self.milestones))

    def progress(self) -> float:
        return self.done_count / self.total

    def next_pending(self) -> Optional[Milestone]:
        for m in self.milestones:
            if m.status in ("pending", "queued", "running"):
                return m
            if m.status == "blocked":
                continue
        return None


class MissionStore:
    """JSONL ledger of missions under ``data/missions/`` (or a fallback dir)."""

    def __init__(self, root: Optional[str] = None):
        self.dir = ensure_mission_root(root)
        self._cache: Dict[str, Mission] = {}
        self.load_all()

    def _path(self, mission_id: str) -> str:
        safe = "".join(c for c in mission_id if c.isalnum() or c in "-_") or "mission"
        return os.path.join(self.dir, f"{safe}.json")

    def load_all(self) -> None:
        self._cache = {}
        try:
            for fname in os.listdir(self.dir):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(self.dir, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    m = mission_from_dict(data)
                    self._cache[m.id] = m
                except (OSError, ValueError, KeyError, TypeError):
                    log.warning("mission ledger skip unreadable %s", fname)
        except OSError:
            pass

    def save(self, mission: Mission) -> None:
        self._cache[mission.id] = mission
        mission.updated_at = time.time()
        path = self._path(mission.id)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(mission_to_dict(mission), f, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("mission ledger write failed for %s: %s", mission.id, exc)

    def get(self, mission_id: str) -> Optional[Mission]:
        return self._cache.get(mission_id)

    def active(self) -> List[Mission]:
        return [m for m in self._cache.values() if m.status == "active"]


class MissionRunner:
    """Self-driving driver that keeps missions alive across the durable queue.

    Clean separation from ``queue.driver.QueueDriver``: the driver leases and
    executes tasks; this runner decides *what* to queue next for each mission
    and reconciles results back into the ledger. Together they provide the
    24/7 long-horizon behavior.
    """

    def __init__(
        self,
        queue: Optional[TaskQueue] = None,
        root: Optional[str] = None,
        store: Optional[MissionStore] = None,
        completion_verifier: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.root = root or os.environ.get("NEXUS_ROOT") or os.getcwd()
        self.queue = queue or TaskQueue(root=self.root)
        self.store = store or MissionStore(root=self.root)
        # Optional synchronous acceptance hook.  Queue success proves only
        # that the worker returned; this hook proves the milestone's output
        # meets its acceptance contract.  Exceptions fail closed.
        self.completion_verifier = completion_verifier

    def _verify_completion(
        self,
        mission: Mission,
        milestone: Milestone,
        task: Dict[str, Any],
        detail: str,
    ) -> Tuple[bool, str]:
        verifier = self.completion_verifier
        if verifier is None:
            return True, ""
        context = {
            "goal": mission.goal,
            "mission_id": mission.id,
            "milestone_index": milestone.index,
            "milestone": milestone.task_desc,
            "task": task,
            "summary": detail,
        }
        try:
            result = verifier(context)
        except Exception as exc:
            return False, f"completion verifier error: {exc}"
        if isinstance(result, dict):
            verified = result.get("verified", result.get("accepted", False))
            reason = str(result.get("reason", result.get("detail", "")))
        else:
            verified = result
            reason = ""
        if isinstance(verified, bool) and verified:
            return True, reason
        return False, reason or "completion verifier rejected milestone"

    # ---------------------------------------------------------------- #
    # creation / decomposition
    # ---------------------------------------------------------------- #
    @staticmethod
    def mission_id_for(goal: str) -> str:
        digest = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:10]
        slug = "".join(c if c.isalnum() else "-" for c in goal.strip().lower())[:32].strip("-")
        return f"{slug}-{digest}"

    def create_mission(
        self,
        goal: str,
        milestones: Optional[List[str]] = None,
        max_replans: int = 3,
    ) -> Mission:
        goal = goal.strip()
        if not goal:
            raise ValueError("goal must be non-empty")
        plan = [m.strip() for m in (milestones or DEFAULT_MILESTONES) if m and m.strip()]
        mission = Mission(
            id=self.mission_id_for(goal),
            goal=goal,
            max_replans=int(max_replans),
            milestones=[
                Milestone(index=i, task_desc=desc) for i, desc in enumerate(plan)
            ],
        )
        self.store.save(mission)
        return mission

    def get_or_create(
        self,
        goal: str,
        milestones: Optional[List[str]] = None,
        max_replans: int = 3,
    ) -> Mission:
        existing = self.store.get(self.mission_id_for(goal))
        if existing is not None:
            return existing
        return self.create_mission(goal, milestones, max_replans)

    # ---------------------------------------------------------------- #
    # queueing
    # ---------------------------------------------------------------- #
    def _queue_task(self, mission: Mission, ms: Milestone, revision: str) -> int:
        idempotency_key = f"mission:{mission.id}:milestone:{ms.index}:revision:{revision}"
        enqueue_once = getattr(self.queue, "enqueue_once", None)
        if callable(enqueue_once):
            task_id = enqueue_once(
                ms.task_desc,
                idempotency_key=idempotency_key,
                priority=5,
                max_attempts=3,
                mission=mission.id,
                milestone=ms.index,
                revision=revision,
            )
        else:
            task_id = self.queue.enqueue(
                ms.task_desc,
                priority=5,
                max_attempts=3,
                idempotency_key=idempotency_key,
                mission=mission.id,
                milestone=ms.index,
                revision=revision,
            )
        ms.status = "queued"
        ms.last_queued_task_id = task_id
        ms.attempts += 1
        self.store.save(mission)
        return task_id

    def hydrate_active(self) -> int:
        """Re-queue any pending milestones of active missions (restart recovery).

        Safe to call repeatedly: a milestone already in the durable queue as
        ``queued``/``running`` is not duplicated because we only re-queue
        ``pending`` milestones.
        """
        requeued = 0
        for mission in self.store.active():
            for ms in mission.milestones:
                if ms.status == "pending":
                    self._queue_task(mission, ms, revision=f"r{ms.replans}")
                    requeued += 1
        return requeued

    def advance(self, max_enqueues_per_tick: int = 4) -> int:
        """Queue the next pending milestone for every active mission that has one.

        Returns the number of tasks enqueued this tick. A mission with no
        pending milestone (all running/blocked or done) is left alone, so
        concurrent workers are respected.
        """
        enqueued = 0
        for mission in self.store.active():
            if enqueued >= max_enqueues_per_tick:
                break
            ms = mission.next_pending()
            if ms is None:
                continue
            if ms.status == "pending":
                self._queue_task(mission, ms, revision=f"r{ms.replans}")
                enqueued += 1
        return enqueued

    # ---------------------------------------------------------------- #
    # result reconciliation
    # ---------------------------------------------------------------- #
    def reconcile(
        self,
        task: Dict[str, Any],
        outcome: str,
        detail: str = "",
    ) -> Optional[Mission]:
        """Record a queued task's outcome back into its mission ledger.

        ``outcome`` is ``"success"`` or ``"failure"``. On success the milestone
        is marked done. On failure the milestone is re-planned up to
        ``max_replans`` times; beyond that it is marked ``blocked`` with the
        reason, and the mission continues (it never abandons its goal). Tasks
        that didn't originate from a mission are ignored.
        """
        payload = task.get("payload") or {}
        meta = payload.get("meta") or {}
        mission_id = meta.get("mission")
        milestone_idx = meta.get("milestone")
        if not mission_id or not isinstance(milestone_idx, int):
            return None
        mission = self.store.get(mission_id)
        if mission is None:
            return None
        if milestone_idx < 0 or milestone_idx >= len(mission.milestones):
            return None
        ms = mission.milestones[milestone_idx]

        task_id = task.get("id")
        if task_id is not None and ms.last_queued_task_id is not None and task_id != ms.last_queued_task_id:
            log.warning("ignoring stale mission result task=%s active=%s", task_id, ms.last_queued_task_id)
            return None
        expected_revision = f"r{ms.replans}"
        if meta.get("revision") and str(meta.get("revision")) != expected_revision:
            log.warning("ignoring stale mission revision=%s active=%s", meta.get("revision"), expected_revision)
            return None

        # Queue delivery can be duplicated or a late worker result can arrive
        # after the milestone has already reached a terminal state.  The
        # completed task keeps its last task id/revision, so identity checks
        # alone do not make reconciliation idempotent: a late failure would
        # otherwise reopen a done milestone and enqueue replacement work.
        if ms.status in ("done", "blocked"):
            log.info(
                "ignoring duplicate terminal mission result mission=%s milestone=%d status=%s",
                mission.id,
                ms.index,
                ms.status,
            )
            return mission

        if outcome == "success":
            verified, verification_reason = self._verify_completion(
                mission, ms, task, detail
            )
            ms.verification = {
                "configured": self.completion_verifier is not None,
                "verified": verified,
                "reason": verification_reason,
                "checked_at": time.time(),
            }
            if not verified:
                # Treat an unaccepted result as a real failure so it follows
                # the existing durable replan/block path.  Never mark a
                # milestone done merely because the queue task succeeded.
                outcome = "failure"
                detail = f"milestone completion verification failed: {verification_reason}"

        if outcome == "success":
            ms.status = "done"
            ms.last_error = ""
            ms.done_at = time.time()
            log.info(
                "mission %s milestone %d done (%d/%d)",
                mission.id, ms.index, mission.done_count, mission.total,
            )
        else:
            ms.last_error = (detail or "milestone failed")[:500]
            if ms.replans < mission.max_replans:
                ms.replans += 1
                ms.status = "pending"          # re-planned, not abandoned
                log.info(
                    "mission %s milestone %d replan %d/%d: %s",
                    mission.id, ms.index, ms.replans, mission.max_replans, ms.last_error,
                )
                self._queue_task(mission, ms, revision=f"r{ms.replans}")
                self.store.save(mission)
                return mission
            ms.status = "blocked"
            log.warning(
                "mission %s milestone %d blocked after %d replans: %s",
                mission.id, ms.index, ms.replans, ms.last_error,
            )

        # Completion check: all milestones done => mission complete.
        if mission.done_count == mission.total:
            mission.status = "completed"
            mission.completed_at = time.time()
            log.info("mission %s COMPLETED (goal: %s)", mission.id, mission.goal[:80])
        self.store.save(mission)
        return mission


def mission_to_dict(m: Mission) -> Dict[str, Any]:
    data = asdict(m)
    data["milestones"] = [asdict(ms) for ms in m.milestones]
    return data


def mission_from_dict(data: Dict[str, Any]) -> Mission:
    ms_list = [Milestone(**ms) for ms in data.get("milestones", [])]
    fields = {k: v for k, v in data.items() if k != "milestones"}
    return Mission(milestones=ms_list, **fields)
