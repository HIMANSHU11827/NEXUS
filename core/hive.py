"""Real local multi-agent orchestration primitives for NEXUS.

This replaces the old fake swarm implementation that only spawned subprocesses
and wrote blackboard logs. The new engine is intentionally local and lightweight:
it has task planning, role assignment, shared state, retries, cancellation,
artifacts, progress tracking, and result consolidation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import os
import queue
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from core.world_model import WorldModel


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


@dataclass
class AgentContract:
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
    """Local multi-agent task economy (formerly Swarm)."""

    DEFAULT_PERSONAS = {
        "ARCHITECT": "Plan dependencies and autonomously delegate work via 'hive_spawn'. Define the collective 'hive_intent' and initialize the 'hive_team' mission board.",
        "ENGINEER": "Implement code. Delegate testing via 'hive_spawn' and post technical updates to the 'hive_team' mission board.",
        "AUDITOR": "Find reliability flaws. Delegate urgent fixes and document high-risk discoveries on the 'hive_team' mission board.",
        "QA_EXPERT": "Design and run verification. Report failed scenarios and debug steps to the 'hive_team' mission board.",
        "RESEARCHER": "Collect outside facts. Summarize breakthroughs on the 'hive_team' mission board for other agents to use immediately.",
        "LIBRARIAN": "Team Knowledge Manager. Curate the 'hive_team' mission board, merge artifacts, and evaluate the final 'hive_intent' completion.",
        "WORKER": "Execute tasks and coordinate with the team via signals, spawns, and the shared mission board.",
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
        self._contracts: Dict[str, AgentContract] = {}
        self._handoffs: Dict[str, HandoffPacket] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()
        self._workers: List[threading.Thread] = []
        self.shared_state: Dict[str, Any] = {}
        self.world = WorldModel(self.root)
        self.worker_fn = worker_fn or self._default_worker
        
        self.personas = self._load_personas()

    def _load_personas(self) -> Dict[str, str]:
        if os.path.exists(self.personas_path):
            try:
                with open(self.personas_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return self.DEFAULT_PERSONAS.copy()

    def _save_personas(self) -> None:
        with open(self.personas_path, "w", encoding="utf-8") as f:
            json.dump(self.personas, f, indent=2)

    # ── Persona Management (Dynamic Sub-Agents) ──

    def create_persona(self, name: str, description: str) -> str:
        name = name.upper()
        with self._lock:
            self.personas[name] = description
            self._save_personas()
        return f"[HIVE]: Persona '{name}' created."

    def modify_persona(self, name: str, description: str) -> str:
        name = name.upper()
        with self._lock:
            if name not in self.personas:
                return f"[HIVE_ERROR]: Persona '{name}' does not exist."
            self.personas[name] = description
            self._save_personas()
        return f"[HIVE]: Persona '{name}' updated."

    def delete_persona(self, name: str) -> str:
        name = name.upper()
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

    def spawn_agent(self, task: str, persona: str = "WORKER", hive_id: Optional[str] = None, parent_id: Optional[str] = None) -> str:
        hive = hive_id or f"HIVE-{uuid.uuid4().hex[:6].upper()}"
        role = persona.upper()
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
        lines = [f"--- NEXUS HIVE REPORT: {hive_id} ---", f"Progress: {progress['by_status']}"]
        for artifact in artifacts:
            lines.append(f"[{artifact.role}::{artifact.task_id}] {artifact.content}")
        failures = [t for t in progress["tasks"] if t["status"] == TaskStatus.FAILED.value]
        for failed in failures:
            lines.append(f"[FAILED::{failed['role']}] {failed['error']}")
        return "\n".join(lines)

    def post_to_blackboard(self, sender_id: str, hive_id: str, message: str) -> None:
        signal = {"timestamp": time.time(), "sender": sender_id, "hive": hive_id, "message": message}
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
                task_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                return
            task = self._tasks.get(task_id)
            if not task:
                continue
            self._execute_task(task)
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
            task.result = result
            task.status = TaskStatus.SUCCEEDED.value
            self._artifacts.append(HiveArtifact(task.id, task.role, result))
            self._checkpoint(task, "succeeded", {"result_preview": result[:500]})
            self.post_to_blackboard(task.role, task.hive_id, f"RESULT {task.id}: {result[:300]}")
        except Exception as exc:
            task.error = str(exc)
            if task.attempts <= task.max_retries and task.hive_id not in self._cancelled:
                task.status = TaskStatus.PENDING.value
                self.post_to_blackboard(task.role, task.hive_id, f"RETRY {task.id}: {task.error[:200]}")
                self._queue.put(task.id)
            else:
                task.status = TaskStatus.FAILED.value
                self._checkpoint(task, "failed", {"error": task.error})
                self.post_to_blackboard(task.role, task.hive_id, f"FAIL {task.id}: {task.error[:300]}")
        finally:
            task.updated_at = time.time()
            self._persist_manifest()

    def _default_worker(self, task: HiveTask, shared_state: Dict[str, Any]) -> str:
        if "shared_state" in shared_state:
            shared_state = shared_state["shared_state"]
        shared_state.setdefault("roles_seen", []).append(task.role)
        if task.role == "ARCHITECT":
            return f"Plan created for objective: {task.objective}"
        if task.role == "QA_EXPERT":
            return f"Verification checklist prepared for: {task.objective}"
        if task.role == "AUDITOR":
            return f"Audit completed for: {task.objective}"
        if task.role == "LIBRARIAN":
            return f"Artifacts merged for: {task.objective}"
        return f"{task.role} completed: {task.objective}"

    def _persist_manifest(self) -> None:
        with self._lock:
            data = {
                "tasks": [asdict(t) for t in self._tasks.values()],
                "artifacts": [asdict(a) for a in self._artifacts[-200:]],
                "contracts": [asdict(c) for c in self._contracts.values()],
                "handoffs": [asdict(h) for h in self._handoffs.values()],
                "updated_at": time.time(),
            }
        with open(self._manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _new_task(self, hive_id: str, role: str, objective: str, parent_id: str = "") -> HiveTask:
        task = HiveTask(
            id=f"TASK-{uuid.uuid4().hex[:8]}",
            hive_id=hive_id,
            role=role,
            objective=objective,
            parent_id=parent_id,
            constraints=self._default_constraints(role),
            required_outputs=self._default_required_outputs(role),
        )
        contract = AgentContract(
            id=f"CONTRACT-{uuid.uuid4().hex[:8]}",
            hive_id=hive_id,
            task_id=task.id,
            role=role,
            objective=objective,
            persona=self.personas.get(role, self.personas.get("WORKER", "Generic worker.")),
            constraints=task.constraints,
            required_outputs=task.required_outputs,
            allowed_tools=self._allowed_tools(role),
            parent_id=parent_id,
        )
        task.contract_id = contract.id
        self._contracts[contract.id] = contract
        return task

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
            from core.cognition.memory_graph import AdaptiveMemoryGraph
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
            from core.cognition.memory_graph import AdaptiveMemoryGraph

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
        return mapping.get(role, mapping["WORKER"])

    def _persist_json(self, path: str, data: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
