"""Real local Hive orchestration primitives for NEXUS.

This replaces the old fake swarm implementation that only spawned subprocesses
and wrote blackboard logs. The new engine is intentionally local and lightweight:
it has task planning, role assignment, shared state, retries, cancellation,
artifacts, progress tracking, and result consolidation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
import json
import os
import queue
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from world_model import WorldModel


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class HiveTask:
    id: str
    hive_id: str
    role: str
    objective: str
    status: str = TaskStatus.PENDING.value
    attempts: int = 0
    max_retries: int = 1
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    contract_id: str = ""
    parent_id: str = ""
    constraints: List[str] = field(default_factory=list)
    required_outputs: List[str] = field(default_factory=list)
    context_refs: List[str] = field(default_factory=list)


@dataclass
class HiveArtifact:
    task_id: str
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HiveContract:
    id: str
    hive_id: str
    task_id: str
    role: str
    objective: str
    persona: str
    constraints: List[str]
    required_outputs: List[str]
    allowed_tools: List[str]
    parent_id: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class HandoffPacket:
    id: str
    hive_id: str
    task_id: str
    role: str
    objective: str
    constraints: List[str]
    required_outputs: List[str]
    context_refs: List[str]
    prior_artifacts: List[Dict[str, Any]]
    memory_pointers: List[str]
    failure_context: List[str]
    short_term_memory: List[str] = field(default_factory=list)
    long_term_memory: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_worker_context(self) -> Dict[str, Any]:
        return asdict(self)


class NexusHiveEngine:
    """Local Hive task economy (formerly Swarm)."""

    DEFAULT_PERSONAS = {
        "ARCHITECT": "Plan dependencies and autonomously delegate work via 'hive_spawn'. Define the collective 'hive_intent' and initialize the 'hive_team' mission board.",
        "ENGINEER": "Implement code. Delegate testing via 'hive_spawn' and post technical updates to the 'hive_team' mission board.",
        "AUDITOR": "Find reliability flaws. Delegate urgent fixes and document high-risk discoveries on the 'hive_team' mission board.",
        "QA_EXPERT": "Design and run verification. Report failed scenarios and debug steps to the 'hive_team' mission board.",
        "RESEARCHER": "Collect outside facts. Summarize breakthroughs on the 'hive_team' mission board for other agents to use immediately.",
        "LIBRARIAN": "Team Knowledge Manager. Curate the 'hive_team' mission board, merge artifacts, and evaluate the final 'hive_intent' completion.",
        "WORKER": "Execute tasks and coordinate with the team via signals, spawns, and the shared mission board.",
    }
    PROFILE_ROLE_ALIASES = {
        "ARCHITECT": "ARCHITECT",
        "PLANNER": "ARCHITECT",
        "CODER": "ENGINEER",
        "DEBUGGER": "QA_EXPERT",
        "REVIEWER": "AUDITOR",
        "RESEARCHER": "RESEARCHER",
    }

    def __init__(self, root_dir: str, worker_fn: Optional[Callable[[HiveTask, Dict[str, Any]], str]] = None):
        self.root = os.path.abspath(root_dir)
        self.logs_dir = os.path.join(self.root, "logs", "hive")
        self.workspace = os.path.join(self.root, "workspace", "hive")
        self.personas_path = os.path.join(self.root, "configs", "hive_personas.json")
        
        os.makedirs(self.logs_dir, exist_ok=True)
        os.makedirs(self.workspace, exist_ok=True)
        os.makedirs(os.path.dirname(self.personas_path), exist_ok=True)

        self._blackboard_path = os.path.join(self.logs_dir, "hive_blackboard.jsonl")
        self._manifest_path = os.path.join(self.logs_dir, "hive_manifest.json")
        
        self._tasks: Dict[str, HiveTask] = {}
        self._artifacts: List[HiveArtifact] = []
        self._contracts: Dict[str, HiveContract] = {}
        self._handoffs: Dict[str, HandoffPacket] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()
        self._workers: List[threading.Thread] = []
        self.shared_state: Dict[str, Any] = {}
        self.world = WorldModel(self.root)
        self.worker_fn = worker_fn or self._select_default_worker()
        
        self.personas = self._load_personas()
        self._load_manifest()

    def _select_default_worker(self) -> Callable[[HiveTask, Dict[str, Any]], str]:
        if os.environ.get("NEXUS_HIVE_LLM_WORKERS", "").lower() in {"1", "true", "yes"}:
            from hive.workers import HiveLLMWorker

            return HiveLLMWorker(self.root, fallback_worker=self._default_worker)
        return self._default_worker

    def _load_personas(self) -> Dict[str, str]:
        personas = self.DEFAULT_PERSONAS.copy()
        personas.update(self._load_profile_personas())
        if os.path.exists(self.personas_path):
            try:
                with open(self.personas_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    personas.update({self._normalize_role(k): str(v) for k, v in data.items()})
            except Exception:
                pass
        return personas

    def _load_profile_personas(self) -> Dict[str, str]:
        """Load Hive role/persona text from hive/profiles/*/profile.yaml.

        Profiles describe role posture and config. Hive is the execution system
        that uses those role descriptions for delegated workers.
        """
        profiles_root = os.path.join(self.root, "hive", "profiles")
        legacy_profiles_root = os.path.join(self.root, "profiles")
        if not os.path.isdir(profiles_root) and os.path.isdir(legacy_profiles_root):
            profiles_root = legacy_profiles_root
        if not os.path.isdir(profiles_root):
            return {}
        try:
            yaml_mod = None
            try:
                import yaml as yaml_mod  # type: ignore
            except Exception:
                yaml_mod = None
            personas: Dict[str, str] = {}
            for name in sorted(os.listdir(profiles_root)):
                profile_yaml = os.path.join(profiles_root, name, "profile.yaml")
                if not os.path.isfile(profile_yaml):
                    continue
                try:
                    with open(profile_yaml, "r", encoding="utf-8") as f:
                        if yaml_mod:
                            data = yaml_mod.safe_load(f) or {}
                        else:
                            data = self._read_minimal_profile_yaml(f.read())
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                profile_name = str(data.get("name") or name).strip()
                description = str(data.get("description") or "").strip()
                if not profile_name or not description:
                    continue
                role = self.PROFILE_ROLE_ALIASES.get(profile_name.upper(), profile_name.upper())
                personas[role] = description
            return personas
        except Exception:
            return {}

    @staticmethod
    def _read_minimal_profile_yaml(text: str) -> Dict[str, str]:
        data: Dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if key in {"name", "description", "inherits"}:
                data[key] = value.strip().strip("'\"")
        return data

    def _load_manifest(self) -> None:
        if not os.path.exists(self._manifest_path):
            return
        try:
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        with self._lock:
            for raw in data.get("tasks", []):
                task = self._dataclass_from_dict(HiveTask, raw)
                if not task or not task.id:
                    continue
                if task.status == TaskStatus.RUNNING.value:
                    task.status = TaskStatus.PENDING.value
                    task.updated_at = time.time()
                self._tasks[task.id] = task
                if task.status == TaskStatus.PENDING.value:
                    self._queue.put(task.id)

            self._artifacts = [
                artifact for artifact in (
                    self._dataclass_from_dict(HiveArtifact, raw) for raw in data.get("artifacts", [])
                )
                if artifact is not None
            ]
            self._contracts = {
                contract.id: contract for contract in (
                    self._dataclass_from_dict(HiveContract, raw) for raw in data.get("contracts", [])
                )
                if contract is not None and contract.id
            }
            self._handoffs = {
                handoff.id: handoff for handoff in (
                    self._dataclass_from_dict(HandoffPacket, raw) for raw in data.get("handoffs", [])
                )
                if handoff is not None and handoff.id
            }

    @staticmethod
    def _dataclass_from_dict(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return None
        names = {item.name for item in fields(cls)}
        clean = {key: value for key, value in data.items() if key in names}
        try:
            return cls(**clean)
        except TypeError:
            return None

    def _save_personas(self) -> None:
        self._atomic_write_json(self.personas_path, self.personas)

    # ── Persona Management (Hive Workers) ──

    def create_persona(self, name: str, description: str) -> str:
        name = self._normalize_role(name)
        description = str(description or "").strip() or self._synthesize_persona(name, "")
        with self._lock:
            self.personas[name] = description
            self._save_personas()
        return f"[HIVE]: Persona '{name}' created."

    def modify_persona(self, name: str, description: str) -> str:
        name = self._normalize_role(name)
        with self._lock:
            if name not in self.personas:
                return f"[HIVE_ERROR]: Persona '{name}' does not exist."
            self.personas[name] = description
            self._save_personas()
        return f"[HIVE]: Persona '{name}' updated."

    def delete_persona(self, name: str) -> str:
        name = self._normalize_role(name)
        with self._lock:
            if name in self.DEFAULT_PERSONAS:
                return f"[HIVE_ERROR]: Cannot delete default persona '{name}'."
            if name not in self.personas:
                return f"[HIVE_ERROR]: Persona '{name}' does not exist."
            del self.personas[name]
            self._save_personas()
        return f"[HIVE]: Persona '{name}' deleted."

    def list_personas(self) -> Dict[str, str]:
        return self.personas.copy()

    # ── Mission & Agent Logic ──

    def plan_mission(self, mission: str) -> List[Dict[str, str]]:
        text = mission.lower()
        plan: List[Dict[str, str]] = [{"role": "ARCHITECT", "objective": f"Create execution plan for: {mission}"}]
        if any(k in text for k in ["bug", "test", "crash", "debug", "verify"]):
            plan.append({"role": "QA_EXPERT", "objective": f"Design verification and failure checks for: {mission}"})
        if any(k in text for k in ["code", "fix", "implement", "refactor", "file"]):
            plan.append({"role": "ENGINEER", "objective": f"Implement required code changes for: {mission}"})
            plan.append({"role": "AUDITOR", "objective": f"Review implementation risks for: {mission}"})
        if any(k in text for k in ["research", "latest", "compare", "internet"]):
            plan.append({"role": "RESEARCHER", "objective": f"Research and summarize evidence for: {mission}"})
        plan.append({"role": "LIBRARIAN", "objective": f"Merge artifacts and capture final memory for: {mission}"})
        return plan

    def create_mission(self, mission: str, hive_id: Optional[str] = None, autostart: bool = True) -> str:
        hive = hive_id or f"HIVE-{uuid.uuid4().hex[:6].upper()}"
        for item in self.plan_mission(mission):
            task = self._new_task(hive, item["role"], item["objective"])
            with self._lock:
                self._tasks[task.id] = task
                self._queue.put(task.id)
            self.post_to_blackboard(task.role, hive, f"QUEUED {task.id}: {task.objective}")
        self._persist_manifest()
        if autostart:
            self.start_workers()
        return hive

    def spawn_agent(
        self,
        task: str,
        persona: str = "WORKER",
        hive_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        persona_description: Optional[str] = None,
    ) -> str:
        hive = hive_id or f"HIVE-{uuid.uuid4().hex[:6].upper()}"
        role = self._normalize_role(persona)
        self.ensure_persona(role, task, description=persona_description)
        item = self._new_task(hive, role, task, parent_id=parent_id or "")
        with self._lock:
            self._tasks[item.id] = item
            self._queue.put(item.id)
        self.post_to_blackboard(role, hive, f"QUEUED {item.id}: {task}")
        self._persist_manifest()
        self.start_workers()
        return f"[HIVE_DEPLOY]: {role} task {item.id} queued in {hive}."

    def start_workers(self, count: int = 2) -> None:
        with self._lock:
            alive = [w for w in self._workers if w.is_alive()]
            self._workers = alive
            while len(self._workers) < count:
                worker = threading.Thread(target=self._worker_loop, daemon=True)
                worker.start()
                self._workers.append(worker)

    def wait_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                workers = list(self._workers)
            alive = [worker for worker in workers if worker.is_alive()]
            if not alive:
                with self._lock:
                    self._workers = []
                return True
            for worker in alive:
                worker.join(timeout=min(0.05, max(0.0, deadline - time.time())))
        return False

    def cancel_hive(self, hive_id: str) -> int:
        count = 0
        with self._lock:
            self._cancelled.add(hive_id)
            for task in self._tasks.values():
                if task.hive_id == hive_id and task.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
                    task.status = TaskStatus.CANCELLED.value
                    task.updated_at = time.time()
                    count += 1
        self.post_to_blackboard("SYSTEM", hive_id, f"CANCELLED {count} task(s)")
        self._persist_manifest()
        return count

    def resume_hive(self, hive_id: str, workers: int = 2) -> Dict[str, Any]:
        with self._lock:
            self._cancelled.discard(hive_id)
            pending = [
                task.id for task in self._tasks.values()
                if task.hive_id == hive_id and task.status == TaskStatus.PENDING.value
            ]
        if pending:
            self.start_workers(count=max(1, int(workers or 1)))
            self.post_to_blackboard("SYSTEM", hive_id, f"RESUME requested for {len(pending)} pending task(s)")
        return {"hive_id": hive_id, "pending": len(pending), "started_workers": bool(pending)}

    def get_progress(self, hive_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            tasks = [t for t in self._tasks.values() if hive_id is None or t.hive_id == hive_id]
            by_status: Dict[str, int] = {}
            for task in tasks:
                by_status[task.status] = by_status.get(task.status, 0) + 1
            return {
                "hive_id": hive_id,
                "total": len(tasks),
                "by_status": by_status,
                "tasks": [asdict(t) for t in tasks],
                "contracts": [asdict(c) for c in self._contracts.values() if hive_id is None or c.hive_id == hive_id],
                "handoffs": [asdict(h) for h in self._handoffs.values() if hive_id is None or h.hive_id == hive_id],
            }

    def consolidate_hive(self, hive_id: str) -> str:
        progress = self.get_progress(hive_id)
        artifacts = [a for a in self._artifacts if self._tasks.get(a.task_id, HiveTask("", "", "", "")).hive_id == hive_id]
        merge_plan = self.merge_plan(hive_id)
        lines = [f"--- NEXUS HIVE REPORT: {hive_id} ---", f"Progress: {progress['by_status']}"]
        for artifact in artifacts:
            lines.append(f"[{artifact.role}::{artifact.task_id}] {artifact.content}")
            quality = artifact.metadata.get("quality") if isinstance(artifact.metadata, dict) else None
            if quality == "incomplete":
                missing = ", ".join(artifact.metadata.get("missing_outputs", []))
                lines.append(f"[ARTIFACT_WARNING::{artifact.role}] Missing required outputs: {missing}")
        if merge_plan["conflicts"]:
            lines.append("--- MERGE CONFLICTS ---")
            for path, entries in merge_plan["conflicts"].items():
                owners = ", ".join(f"{entry['role']}::{entry['task_id']}" for entry in entries)
                lines.append(f"{path}: {owners}")
        else:
            lines.append("--- MERGE CHECK: no overlapping changed files claimed ---")
        failures = [t for t in progress["tasks"] if t["status"] == TaskStatus.FAILED.value]
        for failed in failures:
            lines.append(f"[FAILED::{failed['role']}] {failed['error']}")
        return "\n".join(lines)

    def merge_plan(self, hive_id: str) -> Dict[str, Any]:
        """Return claimed changed files and overlap warnings for a hive.

        Hive workers can be either deterministic local workers or LLM-backed
        specialists, so this accepts a few common report shapes instead of
        requiring strict JSON.
        """
        artifacts = [
            a for a in self._artifacts
            if self._tasks.get(a.task_id, HiveTask("", "", "", "")).hive_id == hive_id
        ]
        by_file: Dict[str, List[Dict[str, str]]] = {}
        for artifact in artifacts:
            for path in self.extract_changed_files(artifact.content):
                by_file.setdefault(path, []).append({"task_id": artifact.task_id, "role": artifact.role})

        conflicts = {
            path: entries
            for path, entries in sorted(by_file.items())
            if len({entry["task_id"] for entry in entries}) > 1
        }
        return {
            "hive_id": hive_id,
            "claimed_files": by_file,
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
        }

    @staticmethod
    def extract_changed_files(content: str) -> List[str]:
        if not content:
            return []
        text = str(content)
        candidates: List[str] = []

        try:
            decoded = json.loads(text)
            candidates.extend(NexusHiveEngine._extract_paths_from_json(decoded))
        except Exception:
            pass

        key_pattern = re.compile(
            r"(?im)^\s*(?:changed_files|files_touched|touched_files|modified_files)\s*[:=]\s*(.+)$"
        )
        for match in key_pattern.finditer(text):
            candidates.extend(re.split(r"[,;]", match.group(1)))

        path_pattern = re.compile(
            r"(?<![\w.-])(?:[\w.-]+[/\\])*[\w.-]+\."
            r"(?:py|ts|tsx|js|jsx|md|json|ya?ml|toml|css|scss|html|sql|sh|ps1|bat|txt)\b",
            re.IGNORECASE,
        )
        candidates.extend(path_pattern.findall(text))

        seen: set[str] = set()
        normalized: List[str] = []
        for raw in candidates:
            path = str(raw).strip().strip("`'\"[](){}<>")
            if not path or "://" in path:
                continue
            path = path.replace("\\", "/")
            path = re.sub(r"^\./+", "", path)
            path = path.rstrip(".,;:")
            if not path or path.startswith("../") or path.startswith("/"):
                continue
            lowered = path.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(path)
        return normalized

    @staticmethod
    def _extract_paths_from_json(value: Any) -> List[str]:
        if isinstance(value, dict):
            found: List[str] = []
            for key, item in value.items():
                if str(key).lower() in {"changed_files", "files_touched", "touched_files", "modified_files"}:
                    found.extend(NexusHiveEngine._extract_paths_from_json(item))
                elif isinstance(item, (dict, list, tuple)):
                    found.extend(NexusHiveEngine._extract_paths_from_json(item))
            return found
        if isinstance(value, (list, tuple)):
            found = []
            for item in value:
                found.extend(NexusHiveEngine._extract_paths_from_json(item))
            return found
        if isinstance(value, str):
            return [value]
        return []

    def post_to_blackboard(self, sender_id: str, hive_id: str, message: str) -> None:
        signal = {"timestamp": time.time(), "sender": sender_id, "hive": hive_id, "message": message}
        os.makedirs(os.path.dirname(self._blackboard_path), exist_ok=True)
        with open(self._blackboard_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(signal, ensure_ascii=False) + "\n")

    def broadcast_signal(self, sender_id: str, hive_id: str, message: str) -> None:
        """Compatibility wrapper for older hive tools."""
        self.post_to_blackboard(sender_id, hive_id, message)

    def get_blackboard_findings(self, hive_id: str) -> List[str]:
        return [s for s in self.get_live_signals(hive_id)]

    def get_live_signals(self, hive_id: Optional[str] = None) -> List[str]:
        if not os.path.exists(self._blackboard_path):
            return []
        signals: List[str] = []
        with open(self._blackboard_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if hive_id is None or data.get("hive") == hive_id:
                    signals.append(f"[{data.get('sender')} @ {data.get('hive')}]: {data.get('message')}")
        return signals[-20:]

    def world_simulate(self, command: str, target: str) -> str:
        return self.world.simulate(command, target).summary()

    def _worker_loop(self) -> None:
        while True:
            try:
                task_id = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                task = self._tasks.get(task_id)
                if task:
                    self._execute_task(task)
            finally:
                self._queue.task_done()

    def _execute_task(self, task: HiveTask) -> None:
        if task.hive_id in self._cancelled:
            task.status = TaskStatus.CANCELLED.value
            return
        task.status = TaskStatus.RUNNING.value
        task.attempts += 1
        task.updated_at = time.time()
        self.post_to_blackboard(task.role, task.hive_id, f"STARTED {task.id}")
        try:
            handoff = self.create_handoff_packet(task)
            task.context_refs = [handoff.id] + handoff.memory_pointers
            checkpoint = self._checkpoint(task, "started", {"handoff": handoff.id})
            context = {
                "shared_state": self.shared_state,
                "contract": asdict(self._contracts.get(task.contract_id)) if task.contract_id in self._contracts else {},
                "handoff": handoff.to_worker_context(),
                "checkpoint": checkpoint,
            }
            result = self.worker_fn(task, context)
            
            # --- EVALUATE ARTIFACT QUALITY ---
            quality_info = self.evaluate_artifact_quality(task, result)
            if quality_info["quality"] == "incomplete" and task.attempts <= task.max_retries:
                # Triggers retry by raising exception
                missing = ", ".join(quality_info["missing_outputs"])
                raise ValueError(f"Artifact quality check failed. Missing outputs: {missing}")
                
            task.result = result
            task.status = TaskStatus.SUCCEEDED.value
            self._artifacts.append(HiveArtifact(task.id, task.role, result, metadata=quality_info))
            self.post_to_blackboard(task.role, task.hive_id, f"RESULT {task.id}: SUCCESS")
            self._checkpoint(task, "succeeded", {"result": result[:1000]})
        except Exception as exc:
            task.error = str(exc)
            if task.attempts <= task.max_retries:
                task.status = TaskStatus.PENDING.value
                with self._lock:
                    self._queue.put(task.id)
                self.post_to_blackboard(task.role, task.hive_id, f"RETRY {task.id} (attempt {task.attempts}): {task.error[:200]}")
                self._checkpoint(task, "pending", {"error": task.error[:1000]})
            else:
                task.status = TaskStatus.FAILED.value
                self.post_to_blackboard(task.role, task.hive_id, f"FAIL {task.id}: {task.error[:200]}")
                self._checkpoint(task, "failed", {"error": task.error[:1000]})
        finally:
            task.updated_at = time.time()
            self._persist_manifest()

    async def _async_worker_loop(self) -> None:
        """Truly asynchronous worker loop for parallel mission execution."""
        while True:
            try:
                # Use a small sleep to prevent busy-waiting while allowing async context switching
                await asyncio.sleep(0.1)
                
                with self._lock:
                    if self._queue.empty():
                        continue
                    task_id = self._queue.get_nowait()
                
                task = self._tasks.get(task_id)
                if not task:
                    continue
                    
                # Run the task execution as a background task to allow true parallelism
                asyncio.create_task(self._async_execute_task(task))
                self._queue.task_done()
                
            except Exception as e:
                self.logger.error(f"Async Hive Worker Error: {e}")

    async def _async_execute_task(self, task: HiveTask) -> None:
        """Asynchronously executes a single Hive worker mission."""
        if task.hive_id in self._cancelled:
            task.status = TaskStatus.CANCELLED.value
            return

        task.status = TaskStatus.RUNNING.value
        task.attempts += 1
        task.updated_at = time.time()
        self.post_to_blackboard(task.role, task.hive_id, f"STARTED {task.id}")

        try:
            # 🧠 Prepare Handoff Packet
            handoff = self.create_handoff_packet(task)
            task.context_refs = [handoff.id] + handoff.memory_pointers
            
            # 🏃 [PARALLEL_EXECUTION]: Execute the worker function
            # If the worker function is synchronous, we run it in a thread to avoid blocking the loop
            if asyncio.iscoroutinefunction(self.worker_fn):
                result = await self.worker_fn(task, {"handoff": handoff.to_worker_context()})
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, self.worker_fn, task, {"handoff": handoff.to_worker_context()})

            task.result = result
            task.status = TaskStatus.SUCCEEDED.value
            self._artifacts.append(HiveArtifact(task.id, task.role, result))
            self.post_to_blackboard(task.role, task.hive_id, f"RESULT {task.id}: SUCCESS")
            
        except Exception as exc:
            task.error = str(exc)
            if task.attempts <= task.max_retries:
                task.status = TaskStatus.PENDING.value
                with self._lock:
                    self._queue.put(task.id)
            else:
                task.status = TaskStatus.FAILED.value
                self.post_to_blackboard(task.role, task.hive_id, f"FAIL {task.id}: {task.error[:200]}")
        finally:
            task.updated_at = time.time()
            self._persist_manifest()

    def start_async_engine(self) -> None:
        """Boots the true asynchronous Hive engine."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if not loop.is_running():
            threading.Thread(target=loop.run_forever, daemon=True).start()
            
        asyncio.run_coroutine_threadsafe(self._async_worker_loop(), loop)
        self.logger.info("NEXUS Async Hive Engine Online.")

    def _default_worker(self, task: HiveTask, shared_state: Dict[str, Any]) -> str:
        if "shared_state" in shared_state:
            shared_state = shared_state["shared_state"]
        shared_state.setdefault("roles_seen", []).append(task.role)
        if task.role == "ARCHITECT":
            return f"plan: Execution plan created for {task.objective}\nrisks: none identified\nhandoff_notes: Ready for downstream agents."
        if task.role == "ENGINEER":
            return f"changed_files: none\nimplementation_notes: Scoped implementation notes for {task.objective}\nverification_needed: targeted tests"
        if task.role == "QA_EXPERT":
            return f"test_plan: Verification checklist prepared for {task.objective}\ncommands: pytest -q\nexpected_signals: passing tests"
        if task.role == "AUDITOR":
            return f"findings: Audit completed for {task.objective}\nrisk_level: low\nrequired_fixes: none"
        if task.role == "LIBRARIAN":
            return f"merged_summary: Artifacts merged for {task.objective}\nmemory_candidates: mission summary\nopen_questions: none"
        if task.role not in self.DEFAULT_PERSONAS:
            return (
                f"specialist_summary: {task.role} completed scoped analysis for {task.objective}\n"
                "evidence: local handoff reviewed\nhandoff_for_teammates: no blocker\nrisks_or_blockers: none"
            )
        return f"result: {task.role} completed {task.objective}\nevidence: local worker\nopen_questions: none"

    def evaluate_artifact_quality(self, task: HiveTask, content: str) -> Dict[str, Any]:
        text = str(content or "")
        present_outputs = []
        missing_outputs = []
        for output in task.required_outputs:
            if self._artifact_has_output(text, output):
                present_outputs.append(output)
            else:
                missing_outputs.append(output)

        score = 1.0
        if task.required_outputs:
            score = len(present_outputs) / len(task.required_outputs)
        return {
            "quality": "complete" if not missing_outputs else "incomplete",
            "score": round(score, 3),
            "required_outputs": list(task.required_outputs),
            "present_outputs": present_outputs,
            "missing_outputs": missing_outputs,
            "changed_files": self.extract_changed_files(text),
        }

    @staticmethod
    def _artifact_has_output(content: str, output_name: str) -> bool:
        key = re.escape(output_name)
        if re.search(rf"(?im)^\s*[-*]?\s*{key}\s*[:=]", content):
            return True
        try:
            decoded = json.loads(content)
        except Exception:
            decoded = None
        if isinstance(decoded, dict) and output_name in decoded:
            return True
        return False

    def _persist_manifest(self) -> None:
        with self._lock:
            data = {
                "tasks": [asdict(t) for t in self._tasks.values()],
                "artifacts": [asdict(a) for a in self._artifacts[-200:]],
                "contracts": [asdict(c) for c in self._contracts.values()],
                "handoffs": [asdict(h) for h in self._handoffs.values()],
                "updated_at": time.time(),
            }
            self._atomic_write_json(self._manifest_path, data)

    def _new_task(self, hive_id: str, role: str, objective: str, parent_id: str = "") -> HiveTask:
        role = self._normalize_role(role)
        self.ensure_persona(role, objective)
        task = HiveTask(
            id=f"TASK-{uuid.uuid4().hex[:8]}",
            hive_id=hive_id,
            role=role,
            objective=objective,
            parent_id=parent_id,
            constraints=self._default_constraints(role),
            required_outputs=self._default_required_outputs(role),
        )
        contract = HiveContract(
            id=f"CONTRACT-{uuid.uuid4().hex[:8]}",
            hive_id=hive_id,
            task_id=task.id,
            role=role,
            objective=objective,
            persona=self.persona_for_role(role, objective),
            constraints=task.constraints,
            required_outputs=task.required_outputs,
            allowed_tools=self._allowed_tools(role),
            parent_id=parent_id,
        )
        task.contract_id = contract.id
        self._contracts[contract.id] = contract
        return task

    def _normalize_role(self, role: str) -> str:
        role = re.sub(r"[^A-Za-z0-9_ -]", "", str(role or "WORKER")).strip()
        role = re.sub(r"[\s-]+", "_", role).upper()
        return role[:64] or "WORKER"

    def ensure_persona(self, role: str, objective: str = "", description: Optional[str] = None) -> None:
        role = self._normalize_role(role)
        with self._lock:
            if role not in self.personas:
                self.personas[role] = str(description or "").strip() or self._synthesize_persona(role, objective)
                self._save_personas()

    def persona_for_role(self, role: str, objective: str = "") -> str:
        role = self._normalize_role(role)
        if role not in self.personas:
            self.ensure_persona(role, objective)
        return self.personas.get(role, self.personas.get("WORKER", "Generic worker."))

    def _synthesize_persona(self, role: str, objective: str) -> str:
        readable = role.replace("_", " ").title()
        focus = self._infer_focus(role, objective)
        return (
            f"{readable} specialist. Own the {focus} slice of the mission, work from the scoped handoff, "
            "coordinate through hive_broadcast/hive_team, surface blockers early, and return evidence-backed findings."
        )

    def _infer_focus(self, role: str, objective: str = "") -> str:
        text = f"{role} {objective}".lower()

        def has_any(keywords: List[str]) -> bool:
            for keyword in keywords:
                if " " in keyword:
                    if keyword in text:
                        return True
                elif re.search(rf"\b{re.escape(keyword)}\b", text):
                    return True
            return False

        if has_any(["perf", "performance", "speed", "latency", "benchmark"]):
            return "performance and benchmark"
        if has_any(["ux", "ui", "gui", "frontend", "react"]):
            return "frontend and operator experience"
        if has_any(["security", "secret", "auth", "risk", "audit"]):
            return "security and risk"
        if has_any(["memory", "context", "rag", "knowledge"]):
            return "memory and context"
        if has_any(["provider", "model", "routing", "llm"]):
            return "provider and model routing"
        if has_any(["docs", "document", "readme"]):
            return "documentation"
        if has_any(["product", "market", "roadmap", "ceo", "strategy"]):
            return "product strategy"
        return "specialized"

    def create_handoff_packet(self, task: HiveTask) -> HandoffPacket:
        prior_artifacts = [
            {"task_id": artifact.task_id, "role": artifact.role, "content": artifact.content[:1000], "timestamp": artifact.timestamp}
            for artifact in self._artifacts
            if self._tasks.get(artifact.task_id) and self._tasks[artifact.task_id].hive_id == task.hive_id
        ][-8:]
        
        # 🧠 Short-Term Memory: Recent blackboard signals for this hive
        short_term = self.get_live_signals(task.hive_id)
        
        # 🧠 Long-Term Memory: Content from the Adaptive Memory Graph
        long_term = []
        memory_ids = []
        try:
            from cognition.memory_graph import AdaptiveMemoryGraph
            graph = AdaptiveMemoryGraph(self.root)
            nodes = graph.recall(task.objective, limit=5)
            for node in nodes:
                memory_ids.append(node.id)
                long_term.append(f"[{node.id}]: {node.content}")
        except Exception:
            pass

        failures = [
            f"{item.role}:{item.error[:300]}"
            for item in self._tasks.values()
            if item.hive_id == task.hive_id and item.status == TaskStatus.FAILED.value and item.error
        ][-5:]
        
        packet = HandoffPacket(
            id=f"HANDOFF-{uuid.uuid4().hex[:8]}",
            hive_id=task.hive_id,
            task_id=task.id,
            role=task.role,
            objective=task.objective,
            constraints=task.constraints,
            required_outputs=task.required_outputs,
            context_refs=[task.contract_id],
            prior_artifacts=prior_artifacts,
            memory_pointers=memory_ids,
            failure_context=failures,
            short_term_memory=short_term,
            long_term_memory=long_term,
        )
        self._handoffs[packet.id] = packet
        self._persist_json(os.path.join(self.workspace, f"{packet.id}.json"), asdict(packet))
        return packet

    def _memory_pointers(self, task: HiveTask) -> List[str]:
        # Deprecated by direct injection in create_handoff_packet but kept for internal logic
        try:
            from cognition.memory_graph import AdaptiveMemoryGraph

            return [node.id for node in AdaptiveMemoryGraph(self.root).recall(task.objective, limit=5)]
        except Exception:
            return []

    def _checkpoint(self, task: HiveTask, status: str, data: Dict[str, Any]) -> Dict[str, Any]:
        checkpoint = {
            "timestamp": time.time(),
            "hive_id": task.hive_id,
            "task_id": task.id,
            "role": task.role,
            "status": status,
            "attempts": task.attempts,
            "contract_id": task.contract_id,
            "data": data,
        }
        path = os.path.join(self.workspace, f"{task.hive_id}_checkpoints.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(checkpoint, ensure_ascii=False) + "\n")
        return checkpoint

    def _default_constraints(self, role: str) -> List[str]:
        base = [
            "🧠 SHORT-TERM MEMORY: Use recent blackboard signals and prior artifacts to maintain mission coherence.",
            "🧠 LONG-TERM MEMORY: Leverage past knowledge retrieved from the memory graph for technical consistency.",
            "Use only scoped handoff context and cited artifacts; do not assume hidden history.",
            "Return concise structured findings with evidence or uncertainty.",
            "Record blockers explicitly instead of pretending completion.",
        ]
        if role == "ENGINEER":
            base.append("Identify files touched and verification required.")
        if role in {"AUDITOR", "QA_EXPERT"}:
            base.append("Prioritize failure modes, regressions, and missing tests.")
        if role not in self.DEFAULT_PERSONAS:
            base.append(f"Stay inside the {role} specialty and coordinate with complementary Hive workers instead of duplicating their work.")
        return base

    def _default_required_outputs(self, role: str) -> List[str]:
        if role == "ARCHITECT":
            return ["plan", "risks", "handoff_notes"]
        if role == "ENGINEER":
            return ["changed_files", "implementation_notes", "verification_needed"]
        if role == "AUDITOR":
            return ["findings", "risk_level", "required_fixes"]
        if role == "QA_EXPERT":
            return ["test_plan", "commands", "expected_signals"]
        if role == "RESEARCHER":
            return ["sources", "summary", "confidence"]
        if role == "LIBRARIAN":
            return ["merged_summary", "memory_candidates", "open_questions"]
        if role not in self.DEFAULT_PERSONAS:
            return ["specialist_summary", "evidence", "handoff_for_teammates", "risks_or_blockers"]
        return ["result", "evidence", "open_questions"]

    def _allowed_tools(self, role: str) -> List[str]:
        hive_tools = ["hive_broadcast", "hive_pulse", "hive_spawn", "hive_intent"]
        mapping = {
            "ARCHITECT": ["code_graph", "unified_graph", "roadmap", "grep", "glob"] + hive_tools,
            "ENGINEER": ["file_edit", "diagnostics", "test_select", "rollback", "patch_ledger"] + hive_tools,
            "AUDITOR": ["grep", "diagnostics", "evidence_ledger", "unified_graph"] + hive_tools,
            "QA_EXPERT": ["bash", "diagnostics", "test_select", "benchmark"] + hive_tools,
            "RESEARCHER": ["web_search", "web_fetch", "evidence_ledger"] + hive_tools,
            "LIBRARIAN": ["cognition", "evidence_ledger", "unified_graph"] + hive_tools,
            "WORKER": ["bash", "grep", "glob"] + hive_tools,
        }
        if role in mapping:
            return mapping[role]

        text = role.lower()
        tools = set(mapping["WORKER"])
        if any(k in text for k in ["perf", "benchmark", "speed"]):
            tools.update(["benchmark", "diagnostics", "test_select"])
        if any(k in text for k in ["ux", "ui", "frontend", "gui"]):
            tools.update(["grep", "glob", "diagnostics", "browser"])
        if any(k in text for k in ["security", "audit", "risk"]):
            tools.update(["grep", "diagnostics", "evidence_ledger", "unified_graph"])
        if any(k in text for k in ["memory", "context", "rag", "knowledge"]):
            tools.update(["cognition", "unified_graph", "grep"])
        if any(k in text for k in ["provider", "model", "routing", "llm"]):
            tools.update(["grep", "diagnostics", "evidence_ledger"])
        if any(k in text for k in ["docs", "writer", "readme"]):
            tools.update(["file_edit", "grep", "glob"])
        if any(k in text for k in ["product", "strategy", "ceo", "roadmap"]):
            tools.update(["roadmap", "unified_graph", "evidence_ledger"])
        return sorted(tools)

    def _persist_json(self, path: str, data: Dict[str, Any]) -> None:
        self._atomic_write_json(path, data)

    @staticmethod
    def _atomic_write_json(path: str, data: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        for attempt in range(5):
            try:
                os.replace(temp_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    break
                time.sleep(0.02 * (attempt + 1))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        try:
            os.remove(temp_path)
        except OSError:
            pass
