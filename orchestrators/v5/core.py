"""NEXUS V5 Loop Core - Central orchestration for self-adaptive quantum loop.

This module provides the core NexusLoopV5 class that coordinates all V5 layers:
- Meta-Learning Layer
- Perception Layer
- Enhanced PAORR Loop (real LLM planning + real tool execution)
- Quantum Actor Orchestration
- Self-Evolution
- Emergent Behavior (swarm)
- Consciousness Layer
- Output Layer (real-time streaming final answer)

Plus V5 integration features:
- Permission System
- Tool Execution (risk-scored commands + registry tools)
- Context Management
- Security Integration
- Memory Management (prefetch + sync)
- NATE Integration
- Hook System
- Streaming Support

Design notes:
- All layer instances are EAGERLY initialized in ``__init__``; a failing layer
  import is logged and recorded as ``None`` so the loop never breaks.
- ``run()`` and ``stream_run()`` both delegate to the shared private generator
  ``_turn_events()`` and acquire the run-guard lock exactly once, so the two
  entry points can never deadlock with each other.
- Real LLM calls go through ``_call_model`` / ``_safe_model_call`` /
  ``_stream_model`` using the kernel MoE router (``self.brain``); when no
  model is available the loop falls back to composed text built from the real
  plan and tool observations - never simulated output.
- Modular design: the core class inherits focused mixins that own distinct
  concerns — ``V5EventEmitter`` (canonical events), ``V5ModelCaller`` (LLM
  calls), ``V5ToolExecutor`` (real tool execution), ``V5Planner`` (LLM plan
  generation) and ``V5ResponseBuilder`` (final answer + fallback). The core
  only orchestrates the 7-phase pipeline.
"""

import asyncio
import hashlib
import inspect
import json
import logging
import os
import time
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from .config import V5Config
from .context import V5ContextBuilder
from .control import V5Control
from .cron import V5Cron
from .events import V5EventEmitter
from .evolution import V5Evolution
from .hive import V5Hive
from .learning import V5Learning
from .lifecycle import V5Lifecycle
from .log import V5Logger
from .checkpoint import V5Checkpoint
from nexus.run_control import RunControlRegistry
from nexus.runtime import safe_session_id
from .model import V5ModelCaller
from .direct_loop import V5DirectModelToolLoop
from .parallel import V5ParallelExecutor
from .permissions import V5Permissions
from .planning import V5Planner
from .plugin import V5Plugin
from .response import V5ResponseBuilder
from .retry import V5RetryPolicy
from .sandbox import V5Sandbox
from .skill import V5Skill
from .tools import V5ToolExecutor
from .verification import V5Verifier
from .background_runner import V5BackgroundRunner
from .active_loop import V5ActiveLoop
from .compat import V5Compat
from .grounding import V5ContextGrounding
from .reliability import V5Reliability

logger = logging.getLogger(__name__)

# ── V1 compatibility constants ─────────────────────────────────────────────

DEFAULT_AGENT_IDENTITY = (
    "You are NEXUS, a sovereign AI agent. "
    "You operate locally with full autonomy. "
    "Be concise, precise, and helpful."
)


# ─────────────────────────────────────────────────────────────────────────────
# V5 INTEGRATION: Permission System
# ─────────────────────────────────────────────────────────────────────────────

class PermissionPolicy(str, Enum):
    """Permission policies from V1 loop."""
    AUTO         = "auto"          # Policy 1: Bypass all — run everything
    AI_DECIDE    = "ai_decide"     # Policy 2: AI safety laws + risk scoring (default)
    ASK_ALL      = "ask_all"       # Policy 3: Human-in-the-loop — ask per operation
    CHECKLIST    = "checklist"     # Policy 4: Pre-authorized whitelist only


class ToolCall:
    """Tool call representation from V1 loop."""
    __slots__ = ("name", "params", "call_id")

    def __init__(self, name: str, params: Dict[str, Any], call_id: str = ""):
        self.name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name or "").strip())[:80] or "unknown"
        self.params = params if isinstance(params, dict) else {"value": params}
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(call_id or "").strip())[:120]
        self.call_id = safe_id or self._stable_call_id()

    def _stable_call_id(self) -> str:
        payload = json.dumps(
            {"name": self.name, "params": self.params},
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        )
        return f"call_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "params": self.params, "call_id": self.call_id}


class HookRegistry:
    """Lifecycle hook system from V1 loop."""
    EVENTS = (
        "pre_llm_call",
        "post_llm_call",
        "pre_tool_call",
        "post_tool_call",
        "on_turn_end",
        "on_evolve",
    )

    def __init__(self):
        self._callbacks: Dict[str, List[Callable]] = {e: [] for e in self.EVENTS}

    def register(self, event: str, cb: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(cb)

    async def trigger(self, event: str, *args, **kwargs):
        for cb in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args, **kwargs)
                else:
                    await asyncio.to_thread(cb, *args, **kwargs)
            except Exception as e:
                logging.getLogger("nexus.hooks").debug(f"Hook '{event}' error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# V5 LOOP STATE
# ─────────────────────────────────────────────────────────────────────────────

class V5LoopState(str, Enum):
    """States for the V5 loop lifecycle."""
    INITIALIZING = "initializing"
    PERCEIVING = "perceiving"
    PLANNING = "planning"
    ACTING = "acting"
    OBSERVING = "observing"
    REFLECTING = "reflecting"
    RETRYING = "retrying"
    EVOLVING = "evolving"
    CONSCIOUS = "conscious"
    OUTPUTTING = "outputting"
    RECOVERING = "recovering"
    REPLANNING = "replanning"
    DEGRADED = "degraded"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    WAITING_FOR_CREDENTIALS = "waiting_for_credentials"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    BLOCKED_NON_RECOVERABLE = "blocked_non_recoverable"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


@dataclass
class V5TurnContext:
    """Context for a single V5 turn."""
    turn_id: str
    session_id: str
    user_input: str
    input_type: str = "text"  # text, voice, vision, code
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    state: V5LoopState = V5LoopState.INITIALIZING


@dataclass
class V5Runtime:
    """Overall runtime state for V5 loop with V5 integration."""
    session_id: str
    root_dir: str
    current_turn: Optional[V5TurnContext] = None
    turn_history: List[V5TurnContext] = field(default_factory=list)
    
    # V5 features
    meta_learning_enabled: bool = True
    quantum_mode: bool = False
    consciousness_level: int = 1  # 0-10 scale
    swarm_size: int = 10
    evolution_enabled: bool = True
    
    # V5 integration features
    permission_policy: PermissionPolicy = PermissionPolicy.AI_DECIDE
    hooks: HookRegistry = field(default_factory=HookRegistry)
    memory: List[Dict[str, str]] = field(default_factory=list)
    work_event_sink: Optional[Callable[[Dict[str, Any]], Any]] = None
    background_tasks: set = field(default_factory=set)
    feature_reasoning: bool = True
    feature_planning: bool = True
    feature_evolution: bool = True
    feature_hive: bool = False
    thinking_mode: bool = True
    checklist: set = field(default_factory=lambda: {"view_file", "glob", "grep", "list_dir"})
    context_token_limit: int = 2000000
    compact_threshold: int = 20
    compact_keep: int = 6
    
    # V1 security integration
    risk_scorer = None
    sandbox = None
    permissions = None
    threat_scan_enabled: bool = True

    # Durable turn state restored by checkpoint resume
    plan: List[Any] = field(default_factory=list)
    actions: List[Any] = field(default_factory=list)
    mental_state: Dict[str, Any] = field(default_factory=dict)
    last_result: Optional[Dict[str, Any]] = None
    context_summary: str = ""


class _DuckIntent:
    """Minimal intent stand-in when the perception module is unavailable."""
    value = "chat"


class _DuckPerceived:
    """Duck-typed PerceivedInput used when perception initialization failed."""

    def __init__(self, user_input: str, input_type: str = "text"):
        self.original_input = user_input
        self.input_type = input_type
        self.intent = _DuckIntent()
        self.confidence = 0.5
        self.extracted_entities: Dict[str, Any] = {}
        self.context_summary = user_input
        self.attention_weights: Dict[str, float] = {}
        self.metadata: Dict[str, Any] = {}


class NexusLoopV5(
    V5EventEmitter,
    V5ModelCaller,
    V5ToolExecutor,
    V5Planner,
    V5ResponseBuilder,
    V5ParallelExecutor,
    V5Verifier,
    V5RetryPolicy,
    V5Learning,
    V5ContextBuilder,
    V5Control,
    V5Hive,
    V5ActiveLoop,
    V5Plugin,
    V5Skill,
    V5Evolution,
    V5Cron,
    V5Lifecycle,
    V5Logger,
    V5Checkpoint,
    V5BackgroundRunner,
    V5Config,
    V5Permissions,
    V5Sandbox,
    V5Compat,
    V5DirectModelToolLoop,
    V5ContextGrounding,
    V5Reliability,
):
    """NEXUS V5 Loop - Self-adaptive quantum loop with V5 integration.
    
    This is the main orchestrator for V5, coordinating all layers plus V1 features.
    """

    # Compatibility surface for callers that used to monkeypatch the deleted
    # Keep the public ``orchestrators.NexusLoop`` name backed by V5.
    tool_registry = None

    # ─────────────────────────────────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, root_dir: str, session_id: str = "default"):
        self.root_dir = os.path.abspath(root_dir or os.getcwd())
        self.session_id = safe_session_id(session_id)
        self.runtime = V5Runtime(session_id=self.session_id, root_dir=self.root_dir)
        self.logger = logging.getLogger("nexus.loop.v5")

        # V5 integration: Thread safety
        self._run_guard = threading.Lock()
        self._session_write_lock = threading.Lock()
        # Non-fatal capability degradations hit during the current turn;
        # surfaced on the final result so degraded runs are never silent.
        self._degradations: List[str] = []
        self._abort_flag = asyncio.Event()
        self._run_controls = RunControlRegistry()
        self._run_context_heartbeats: Dict[
            str, tuple[asyncio.Event, asyncio.Task[Any]]
        ] = {}
        self._current_run_context: Any = None
        self._detached_lifecycle_tasks: set[asyncio.Task[Any]] = set()
        self._detached_lifecycle_task_count = 0
        self._shutdown_fenced = False
        # A fresh process cannot own runs persisted by an earlier process.
        # Retire those orphaned contexts before accepting new work so the
        # control plane never reports a permanent running task after restart.
        try:
            from nexus.run_context import recover_orphaned_runs

            recover_orphaned_runs(root=self.root_dir, session_id=self.session_id)
        except Exception:
            self.logger.debug("orphaned run recovery skipped", exc_info=True)

        # Per-turn event plumbing
        self._current_turn_id = ""
        self._stream_events: List[Dict[str, Any]] = []
        self._stage_started_at: Dict[str, float] = {}
        self._tool_started_at: Dict[str, float] = {}
        self.work_event_sink: Optional[Callable[[Dict[str, Any]], Any]] = None

        # V5 integration: Kernel
        self.kernel = None
        self._brain = None
        if not isinstance(getattr(type(self), "tool_registry", None), property):
            self.tool_registry = None
        self._init_kernel()

        # V5 integration: Security
        self._init_security()

        # V5 integration: Permissions
        self._init_permissions()

        # V5 integration: Config
        self._init_config()

        # V5 integration: Context manager
        self._context_manager = None
        self._init_context_manager()

        # V5 integration: Memory manager
        self._memory_manager = None
        self._init_memory_manager()

        # V5 integration: NATE
        self._nate = None
        self._init_nate()

        # V5 compat: MCP servers, soul file, compiler check
        self._mcp_clients: List[Any] = []
        self._init_mcp_servers()
        self._ensure_soul_file()
        self._check_compiler_status()

        # V5 compat: Stable prompt cache
        self._stable_prompt_cache: Optional[str] = None
        self._stable_prompt_built = False

        # V5 compat: Threat scanning
        self._threat_scan_enabled = True

        # V5 compat: Slash command cache
        self._slash_command_cache: Dict[str, str] = {}

        # V5 compat: Profile cache
        self._nexus_profile_cache: Dict[str, str] = {}

        # V5 compat: Gaps found (evolution gap detection)
        self._gaps_found: List[Dict[str, Any]] = []

        # V5 compat: Evolution state
        self._evolution_last_filled: float = 0.0

        # V5 compat: Run state tracking (tests expect these)
        self._last_run_failed: bool = False
        self._last_run_had_tool_execution: bool = False
        self._last_run_verified: bool = False
        self.operator_bypass_mode: bool = False
        self._background_tasks: set = set()

        # Layer instances (eagerly initialized — each wrapped so a failing
        # import can never break the loop)
        self._meta_learning = None
        self._perception = None
        self._paorr_enhanced = None
        self._quantum_actor = None
        self._self_evolution = None
        self._emergent_behavior = None
        self._consciousness = None
        self._output = None
        self._init_layers()

        # Event callbacks
        self._state_callbacks: Dict[V5LoopState, List[Callable]] = {}

        self.logger.info(f"NEXUS V5 Loop initialized for session {session_id}")

    def _init_kernel(self):
        """Initialize NEXUS kernel for V5 integration."""
        try:
            from kernel import get_nexus_kernel
            self.kernel = get_nexus_kernel(root_dir=self.root_dir)
            self._brain = getattr(self.kernel, "moe", None)
            self.tool_registry = getattr(self.kernel, "tools", None)
            self.logger.info("V5 loop connected to NEXUS kernel")
        except Exception as e:
            self.logger.warning(f"Could not connect to kernel: {e}")

    def _init_context_manager(self):
        """Initialize context manager from V1."""
        try:
            from .context_manager import ContextManager
            self._context_manager = ContextManager(self.root_dir)
            self.logger.info("V5 loop context manager initialized")
        except Exception as e:
            self.logger.warning(f"Could not initialize context manager: {e}")

    def _init_memory_manager(self):
        """Initialize memory manager from V1."""
        try:
            from memory import MemoryManager
            self._memory_manager = MemoryManager(self.root_dir, session_id=self.session_id)
            self.logger.info("V5 loop memory manager initialized")
        except Exception as e:
            self.logger.warning(f"Could not initialize memory manager: {e}")

    def _init_nate(self):
        """Initialize NATE from V1."""
        try:
            if self.kernel:
                self._nate = getattr(self.kernel, "nate", None)
                self.logger.info("V5 loop NATE initialized")
        except Exception as e:
            self.logger.warning(f"Could not initialize NATE: {e}")

    def _init_layers(self):
        """Eagerly construct every V5 layer; failures degrade to None."""
        try:
            from .meta import MetaLearningLayer
            self._meta_learning = MetaLearningLayer(self.root_dir)
            self.logger.info("V5 meta-learning layer initialized")
        except Exception as e:
            self.logger.warning(f"Meta-learning layer init failed: {e}")

        try:
            from .perceive import PerceptionLayer
            self._perception = PerceptionLayer(self.root_dir)
            self.logger.info("V5 perception layer initialized")
        except Exception as e:
            self.logger.warning(f"Perception layer init failed: {e}")

        try:
            from .paorr import PAORREnhanced
            params = list(inspect.signature(PAORREnhanced.__init__).parameters.keys())
            kwargs: Dict[str, Any] = {}
            if "planner" in params:
                kwargs["planner"] = self._plan_with_tool
            if "tool_executor" in params:
                kwargs["tool_executor"] = self._run_tool
            if "emitter" in params:
                kwargs["emitter"] = self._emit_stage_event
            try:
                self._paorr_enhanced = PAORREnhanced(self.root_dir, **kwargs)
            except TypeError:
                self._paorr_enhanced = PAORREnhanced(self.root_dir)
            self.logger.info("V5 PAORR enhanced layer initialized")
        except Exception as e:
            self.logger.warning(f"PAORR enhanced init failed: {e}")

        try:
            from .quantum import QuantumActorModel
            self._quantum_actor = QuantumActorModel(self.root_dir)
            self.logger.info("V5 quantum actor initialized")
        except Exception as e:
            self.logger.warning(f"Quantum actor init failed: {e}")

        try:
            from .self_evolution import SelfEvolutionLayer
            self._self_evolution = SelfEvolutionLayer(self.root_dir)
            self.logger.info("V5 self-evolution layer initialized")
        except Exception as e:
            self.logger.warning(f"Self-evolution init failed: {e}")

        try:
            from .emergent import EmergentBehaviorLayer
            self._emergent_behavior = EmergentBehaviorLayer(self.root_dir)
            self.logger.info("V5 emergent behavior layer initialized")
        except Exception as e:
            self.logger.warning(f"Emergent behavior init failed: {e}")

        try:
            from .conscious import ConsciousnessLayer
            self._consciousness = ConsciousnessLayer(self.root_dir)
            self.logger.info("V5 consciousness layer initialized")
        except Exception as e:
            self.logger.warning(f"Consciousness init failed: {e}")

        try:
            from .output import OutputLayer
            self._output = OutputLayer(self.root_dir)
            self.logger.info("V5 output layer initialized")
        except Exception as e:
            self.logger.warning(f"Output layer init failed: {e}")

    # Property getters for lazy fallback (layers are eager, but keep these so
    # external consumers can access layers after a failed eager init).
    @property
    def meta_learning(self):
        if self._meta_learning is None:
            try:
                from .meta import MetaLearningLayer
                self._meta_learning = MetaLearningLayer(self.root_dir)
            except Exception as e:
                self.logger.warning(f"Meta-learning layer init failed: {e}")
        return self._meta_learning

    @property
    def perception(self):
        if self._perception is None:
            try:
                from .perceive import PerceptionLayer
                self._perception = PerceptionLayer(self.root_dir)
            except Exception as e:
                self.logger.warning(f"Perception layer init failed: {e}")
        return self._perception

    @property
    def paorr_enhanced(self):
        if self._paorr_enhanced is None:
            try:
                from .paorr import PAORREnhanced
                params = list(inspect.signature(PAORREnhanced.__init__).parameters.keys())
                kwargs: Dict[str, Any] = {}
                if "planner" in params:
                    kwargs["planner"] = self._plan_with_tool
                if "tool_executor" in params:
                    kwargs["tool_executor"] = self._run_tool
                if "emitter" in params:
                    kwargs["emitter"] = self._emit_stage_event
                try:
                    self._paorr_enhanced = PAORREnhanced(self.root_dir, **kwargs)
                except TypeError:
                    self._paorr_enhanced = PAORREnhanced(self.root_dir)
            except Exception as e:
                self.logger.warning(f"PAORR enhanced init failed: {e}")
        return self._paorr_enhanced

    @property
    def quantum_actor(self):
        if self._quantum_actor is None:
            try:
                from .quantum import QuantumActorModel
                self._quantum_actor = QuantumActorModel(self.root_dir)
            except Exception as e:
                self.logger.warning(f"Quantum actor init failed: {e}")
        return self._quantum_actor

    @property
    def self_evolution(self):
        if self._self_evolution is None:
            try:
                from .self_evolution import SelfEvolutionLayer
                self._self_evolution = SelfEvolutionLayer(self.root_dir)
            except Exception as e:
                self.logger.warning(f"Self-evolution init failed: {e}")
        return self._self_evolution

    @property
    def emergent_behavior(self):
        if self._emergent_behavior is None:
            try:
                from .emergent import EmergentBehaviorLayer
                self._emergent_behavior = EmergentBehaviorLayer(self.root_dir)
            except Exception as e:
                self.logger.warning(f"Emergent behavior init failed: {e}")
        return self._emergent_behavior

    @property
    def consciousness(self):
        if self._consciousness is None:
            try:
                from .conscious import ConsciousnessLayer
                self._consciousness = ConsciousnessLayer(self.root_dir)
            except Exception as e:
                self.logger.warning(f"Consciousness init failed: {e}")
        return self._consciousness

    @property
    def output(self):
        if self._output is None:
            try:
                from .output import OutputLayer
                self._output = OutputLayer(self.root_dir)
            except Exception as e:
                self.logger.warning(f"Output layer init failed: {e}")
        return self._output

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    # ── Memory Persistence ──────────────────────────────────────────────

    def _record_degradation(self, reason: str) -> None:
        """Record a non-fatal capability degradation for the final result.

        Never raises; keeps the most recent 32 distinct entries per turn so a
        broken subsystem cannot flood the report.
        """
        try:
            entries = getattr(self, "_degradations", None)
            if entries is None:
                entries = []
                self._degradations = entries
            text = str(reason or "").strip()[:300]
            if text and text not in entries:
                entries.append(text)
                del entries[:-32]
        except Exception:
            pass

    def save_memory(self) -> None:
        """Persist short-term conversation memory to disk."""
        try:
            from nexus.session_store import atomic_write_json, session_write_lock
            path = os.path.join(self.root_dir, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            memory = getattr(self.runtime, "memory", [])
            with self._session_write_lock:
                with session_write_lock(path):
                    atomic_write_json(path, memory)
        except Exception as e:
            self.logger.warning("save_memory failed: %s", e)

    def load_memory(self, session_id: Optional[str] = None) -> None:
        """Load short-term memory from disk."""
        if session_id:
            self.session_id = safe_session_id(session_id)
            self.runtime.session_id = self.session_id
            if self._memory_manager:
                try:
                    self._memory_manager.session_id = self.session_id
                except Exception:
                    pass
        try:
            path = os.path.join(self.root_dir, "logs", "sessions", f"{self.session_id}.json")
            if not os.path.exists(path) and self.session_id == "default":
                path = os.path.join(self.root_dir, "logs", "session_memory.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self.runtime.memory = json.load(f)
            else:
                self.runtime.memory = []
        except Exception as e:
            # Never silently drop a session into amnesia: quarantine the
            # unreadable file for inspection and record the degradation so the
            # run can surface it instead of pretending nothing was lost.
            self.logger.warning("load_memory failed, quarantining corrupt file: %s", e)
            try:
                corrupt_path = f"{path}.corrupt-{int(time.time())}"
                os.replace(path, corrupt_path)
                self.logger.warning("load_memory: unreadable session moved to %s", corrupt_path)
            except Exception:
                pass
            self.runtime.memory = []
            self._record_degradation(f"session memory reload failed: {e}")

    def sync_memory(self) -> None:
        """High-performance sync — CLI/GUI cohesion. Reload from disk if changed."""
        try:
            path = os.path.join(self.root_dir, "logs", "sessions", f"{self.session_id}.json")
            if not os.path.exists(path) and self.session_id == "default":
                path = os.path.join(self.root_dir, "logs", "session_memory.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    disk_mem = json.load(f)
                    if disk_mem != self.runtime.memory:
                        self.runtime.memory = disk_mem
        except Exception as e:
            # A corrupt on-disk session must not wipe the in-memory state;
            # keep what we have and make the degradation visible.
            self.logger.warning("sync_memory skipped unreadable session file: %s", e)
            self._record_degradation(f"session memory sync failed: {e}")

    def _write_session_bus(self, _messages=None) -> None:
        """Write session to session_bus for CLI/GUI/Gateway sync."""
        try:
            from nexus.session_store import atomic_write_json, session_write_lock
            path = os.path.join(self.root_dir, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with self._session_write_lock:
                with session_write_lock(path):
                    atomic_write_json(path, self.runtime.memory)
        except Exception:
            pass

    @staticmethod
    @contextmanager
    def _session_bus_interprocess_lock(path: str):
        """Compatibility adapter for callers that need the session mutex."""
        from nexus.session_store import session_interprocess_lock
        with session_interprocess_lock(path):
            yield

    # ── Abort / Reset ───────────────────────────────────────────────────

    @property
    def hooks(self):
        """Backward-compatible access to HookRegistry on runtime."""
        return getattr(self.runtime, "hooks", None)

    @property
    def permissions(self):
        return getattr(self.runtime, "permissions", None)

    @permissions.setter
    def permissions(self, value):
        self.runtime.permissions = value

    @property
    def sandbox(self):
        """Backward-compatible access to the runtime command sandbox.

        The server settings API historically addressed ``loop.sandbox`` while
        V5 owns the object on ``runtime``.  Keeping this adapter at the loop
        boundary prevents settings updates from silently failing and ensures
        terminal/tool execution sees the same sandbox instance.
        """
        return getattr(self.runtime, "sandbox", None)

    @sandbox.setter
    def sandbox(self, value):
        self.runtime.sandbox = value

    @property
    def sandbox_tier(self):
        sandbox = self.sandbox
        return getattr(sandbox, "tier", None) if sandbox is not None else None

    @sandbox_tier.setter
    def sandbox_tier(self, value):
        sandbox = self.sandbox
        if sandbox is not None:
            sandbox.tier = value

    @property
    def policy(self):
        return getattr(self.runtime, "permission_policy", PermissionPolicy.AI_DECIDE)

    @policy.setter
    def policy(self, value):
        self.runtime.permission_policy = value

    @property
    def checklist(self):
        return getattr(self.runtime, "checklist", set())

    @checklist.setter
    def checklist(self, value):
        self.runtime.checklist = set(value or [])

    # ── Evolution compatibility stubs ───────────────────────────────────

    def _handle_tool_failure(self, tool_name: str, error: str, params: Optional[Dict] = None) -> None:
        """Record a tool failure gap for evolution (V1 compat)."""
        self._gaps_found.append({
            "tool": tool_name,
            "error": str(error or ""),
            "params": params or {},
            "ts": __import__("time").time(),
        })

    async def _fill_gap_during_session(self) -> bool:
        """Attempt to fill evolution gaps during a session (V1 compat stub)."""
        if not self._gaps_found:
            return False
        now = __import__("time").time()
        if now - getattr(self, "_evolution_last_filled", 0) < 300:
            return False
        self._evolution_last_filled = now
        return False

    async def _fill_gap(self, gap: Dict[str, Any]) -> bool:
        """Fill a single evolution gap (V1 compat stub)."""
        return False

    # ── V1-compat method aliases ────────────────────────────────────────

    def _extract_tool_calls(self, text: str):
        """V1-compat alias for V5's free-text tool call extraction."""
        extractor = getattr(self, "_extract_tool_calls_from_text", None)
        if callable(extractor):
            return extractor(text)
        return []

    def _extract_dsml_tool_calls(self, text: str):
        """V1-compat alias."""
        from .tools import _TextToolCall
        import html
        import re
        calls = []
        if not text or "invoke name=" not in text:
            return calls
        invoke_pattern = re.compile(
            r'<[^>]*invoke\s+name="([^"]+)"[^>]*>(.*?)</[^>]*invoke>',
            re.IGNORECASE | re.DOTALL)
        param_pattern = re.compile(
            r'<[^>]*parameter\s+name="([^"]+)"(?:\s+[^>]*)?>(.*?)</[^>]*parameter>',
            re.IGNORECASE | re.DOTALL)
        for invoke_name, body in invoke_pattern.findall(text):
            params = {}
            for param_name, raw_value in param_pattern.findall(body):
                value = html.unescape(raw_value or "").strip()
                lowered = value.lower()
                if lowered in ("true", "false"):
                    value = lowered == "true"
                params[param_name] = value
            calls.append(_TextToolCall(invoke_name.strip(), params))
        return calls

    @staticmethod
    def _clean_voice_response(text: str) -> str:
        """Strip thinking tags and TASK_COMPLETE markers (V1 compat)."""
        if not text:
            return ""
        import re
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"</?thinking>", "", text, flags=re.IGNORECASE)
        text = text.replace("TASK_COMPLETE", "")
        return text.strip()

    @staticmethod
    def _observation_is_failure(obs: str) -> bool:
        """V1-compat: check if a tool observation indicates failure."""
        if not obs:
            return False
        low = obs.lower()
        if any(kw in low for kw in (
            "error:", "exception:", "traceback", "command exited with code",
            "command not found", "is not recognized", "failed:",
        )):
            return True
        if bool(re.match(r"^\[exit_code\]\s*:?\s*[1-9]\d*", low)):
            return True
        # Loose match: em-dash or unicode dash separators after error/exception
        if re.search(r"\berror\b", low) and not re.search(r"\b0 errors?\b", low):
            return True
        return False

    @staticmethod
    def _normalize_web_query(search_intent: str, full_task: str) -> str:
        """V1-compat web query normalizer with topic extraction."""
        from datetime import datetime
        today = datetime.now().strftime("%B %d %Y").replace(" 0", " ")
        cleaned = re.sub(r"\b\d{4}\b", "", search_intent or "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        intent = (full_task or "").lower()
        if "news" in (search_intent or "").lower() or "news" in intent or "knews" in intent:
            if "ai" in intent or "artificial intelligence" in intent:
                return f"latest artificial intelligence news {today} headlines"
            subject_match = re.search(r"\bnews\b\s+(?:on|about|for|of|regarding)\s+(.+)$", intent, re.IGNORECASE)
            subject = subject_match.group(1).strip(" ?.!") if subject_match else ""
            if subject:
                return f"latest news about {subject} {today}"
            leading = re.search(
                r"\b(?:find|show|give|tell\s+me)?\s*(?:one|the|a)?\s*"
                r"(?:current|latest|today'?s)?\s*([a-z][\w.-]*(?:\s+[a-z][\w.-]*){0,3})\s+"
                r"(?:news|headlines?)\b", intent, re.IGNORECASE)
            if leading:
                subject = re.sub(r"\s+news$", "", leading.group(1).strip(" ?.!,-\n"), flags=re.IGNORECASE)
                if subject and subject.lower() not in {"current", "latest", "today", "s"}:
                    return f"latest {subject} news {today}"
            return f"latest news headlines {today}"
        return cleaned

    @staticmethod
    def _todo_matches_task(todo_plan: str, task: str) -> bool:
        """V1-compat: check if a saved TODO plan matches a new task."""
        if not todo_plan or not task:
            return False
        return any(word in todo_plan.lower() for word in task.lower().split() if len(word) > 3)

    def _compact_memory(self, messages: List[Dict]) -> List[Dict]:
        """V1-compat memory compactor: preserves system + recent messages."""
        if len(messages) <= self.runtime.compact_threshold:
            return messages
        keep = self.runtime.compact_keep
        system = [m for m in messages if m.get("role") == "system"]
        recent = messages[-max(1, keep):]
        return system + recent

    def _contains_tool_protocol(self, text: str) -> bool:
        """V1-compat: check for tool protocol markers."""
        stripped = getattr(self, "_strip_internal_tool_protocol", None)
        if callable(stripped):
            return stripped(text) != text
        return bool(getattr(self, "_extract_tool_calls_from_text", lambda t: [])(text))

    # ── V1 tool extraction aliases ───────────────────────────────────────

    def _extract_compact_tags(self, text):
        """V1-compat: extract compact XML tool tags."""
        from .tools import _TextToolCall
        import html
        calls = []
        if not text or "<" not in text:
            return calls
        pattern = re.compile(
            r"<(?P<name>[a-zA-Z_][a-zA-Z0-9_-]*)\b(?P<attrs>[^>]*)"
            r"(?:/\s*>|>(?P<body>.*?)</(?P=name)\s*>)", re.DOTALL)
        attr_pattern = re.compile(r'([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*["\'](.*?)["\']', re.DOTALL)
        known = {"file_ops", "reading", "creating", "modifying", "deleting",
                  "bash", "code_search", "web_search", "http_client", "git_ops", "test_runner"}
        try:
            if self.tool_registry:
                known |= set(self.tool_registry.list_tools().keys())
        except Exception:
            pass
        for match in pattern.finditer(text):
            name = match.group("name").strip()
            if name not in known:
                continue
            params = {k: html.unescape(v) for k, v in attr_pattern.findall(match.group("attrs") or "")}
            body = html.unescape((match.group("body") or "").strip())
            if body and "content" not in params:
                params["content"] = body
            calls.append(_TextToolCall(name, params))
        return calls

    def _extract_action_fences(self, response):
        """V1-compat: recover action blocks from code fences."""
        from .tools import _TextToolCall
        pattern = re.compile(r"```(?:bash|sh|shell|powershell|ps1|cmd)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
        calls = []
        for block in pattern.findall(response)[:20]:
            command = block.strip()
            if not command or len(command) > 12000:
                continue
            read_match = re.fullmatch(r'(?:cat|type)\s+["\']([^"\']+)["\']', command, re.IGNORECASE)
            if read_match:
                calls.append(_TextToolCall("reading", {"path": read_match.group(1)}))
            else:
                calls.append(_TextToolCall("bash", {"command": command, "cwd": self.root_dir}))
        return calls

    # ── V1 static analysis methods ───────────────────────────────────────

    @staticmethod
    def _final_response_contains_evidence(response, observations):
        if not response or not observations:
            return False
        rwords = set(re.findall(r"[a-z0-9]{4,}", response.lower()))
        etext = " ".join(str(o) for o in observations)
        eurls = re.findall(r"\[([^\]]+)\]\(https?://", etext)
        if eurls:
            if any(url in response for url in eurls):
                return True
            titles = re.findall(r"\[([^\]\n]+)\]\(https?://", etext)
            ewords = set(re.findall(r"[a-z0-9]{4,}", " ".join(titles).lower()))
            return len(rwords & ewords) >= 3 and len(response) >= 80
        return len(response) >= 40

    @staticmethod
    def _deterministic_evidence_summary(observations):
        if not observations:
            return "No tool results available."
        text = "\n".join(str(o) for o in observations)
        if NexusLoopV5._observations_contain_failure(observations):
            return f"Work failed based on the tool evidence:\n\n{text[:1500]}"
        return f"Work completed and verified.\n\nSummary of the verified results:\n{text[:1500]}"

    @staticmethod
    def _deterministic_failure_summary(observations):
        return NexusLoopV5._deterministic_evidence_summary(observations)

    @staticmethod
    def _verified_evidence_from_result(result: Any) -> "tuple[List[Dict[str, Any]], List[Dict[str, Any]]]":
        """Extract verified tool evidence from a run result for memory sync.

        Returns ``(verified_actions, tool_results)``.  Only actions backed by
        real tool evidence (success / ``verified``) are included; the durable
        memory sinks must never record unverified model prose as a fact.
        """
        verified_actions: List[Dict[str, Any]] = []
        tool_results: List[Dict[str, Any]] = []
        if not isinstance(result, dict):
            return verified_actions, tool_results
        for action in result.get("actions") or []:
            if not isinstance(action, dict):
                continue
            # The direct loop records success on actions; the PAORR path stamps
            # ``verified``.  Either counts as verified evidence for memory.
            if not bool(action.get("verified", action.get("success", False))):
                continue
            verified_actions.append(action)
            tool_results.append({
                "tool": action.get("tool") or action.get("name"),
                "output": action.get("output"),
                "error": action.get("error"),
                "success": bool(action.get("success", False)),
            })
        return verified_actions, tool_results

    @staticmethod
    def _observations_contain_failure(observations):
        for obs in (observations or []):
            if NexusLoopV5._observation_is_failure(str(obs)):
                return True
        return False

    @staticmethod
    def _is_raw_tool_result_dump(text):
        s = str(text or "").strip()
        if s.startswith("[") and s.endswith("]"):
            import json as _j
            try:
                p = _j.loads(s)
                if isinstance(p, list) and p and all(isinstance(i, dict) for i in p):
                    return True
            except Exception:
                pass
        return any(k in s.lower() for k in ('"tool_calls"', '"tool_result"'))

    @staticmethod
    def _strip_internal_tool_protocol(text):
        """V1-compat static: strip tool protocol from text."""
        import re
        if not text:
            return ""
        t = text
        # <function: name>...</function> or <function:name>...</function>
        t = re.sub(r"<function:\s*\w+>.*?</function>", "", t, flags=re.DOTALL | re.IGNORECASE)
        # <function>...</function>
        t = re.sub(r"<function>.*?</function>", "", t, flags=re.DOTALL | re.IGNORECASE)
        # <function attrs>...</function>
        t = re.sub(r"<function\s+[^>]*>.*?</function>", "", t, flags=re.DOTALL | re.IGNORECASE)
        # Tool blocks
        t = re.sub(r"```(?:tool_use|json|tool)\s*\n.*?\n```", "", t, flags=re.DOTALL | re.IGNORECASE)
        t = re.sub(r"\{[^}]*\"tool_calls\"[^}]*\}", "", t, flags=re.DOTALL)
        t = re.sub(r"\{[^}]*\"tool_result\"[^}]*\}", "", t, flags=re.DOTALL)
        return t.strip()

    @staticmethod
    def _contains_tool_protocol(text):
        """V1-compat static: check for tool protocol markers."""
        if not text:
            return False
        stripped = NexusLoopV5._strip_internal_tool_protocol(text)
        return stripped != text

    # ── V1 pipeline stubs (monkeypatched by tests) ───────────────────────

    async def _audit_and_approve(self, tool_calls):
        """Compatibility audit that delegates to the canonical policy gate.

        The live direct loop uses ``_audit_tool_call`` from V5ToolExecutor.
        This adapter exists for older integrations that still submit a batch
        of ``ToolCall`` objects; it does not execute tools or select tools.
        """
        registry = getattr(self, "tool_registry", None)
        if registry is None:
            return False if tool_calls else True
        try:
            available = registry.list_tools(include_unavailable=False)
        except TypeError:
            available = registry.list_tools()
        if isinstance(available, dict):
            available = available.keys()
        available = {str(name) for name in (available or [])}
        permission_system = getattr(self, "permissions", None)
        for call in tool_calls or []:
            name = str(getattr(call, "name", ""))
            if name not in available and name not in {"bash", "shell", "terminal", "run_command"}:
                return False
            params = getattr(call, "params", {}) or {}
            action = str(params.get("command") or params.get("CommandLine") or params.get("path") or params)
            policy = str(getattr(self, "policy", "") or "").lower()
            checklist = getattr(self, "checklist", None) or []
            if policy.endswith("checklist") and action.strip() not in {str(item).strip() for item in checklist}:
                return False
            if permission_system is not None and hasattr(permission_system, "check"):
                result = permission_system.check(
                    name,
                    action,
                    context={
                        "run_id": str(getattr(self, "_current_turn_id", "") or ""),
                        "turn_id": str(getattr(self, "_current_turn_id", "") or ""),
                        "session_id": str(getattr(self, "session_id", "") or ""),
                        "surface": "loop",
                    },
                )
                if not bool(getattr(result, "granted", False)):
                    return False
        return True

    async def _execute_tools(self, tool_calls):
        """Execute tool calls through the tool executor, returning real results."""
        if not tool_calls:
            return []
        try:
            from providers.reliability import redact_secrets
        except Exception:
            redact_secrets = None
        results = []
        for call in tool_calls:
            try:
                result = await self._run_tool(call)
                results.append(result)
            except Exception as e:
                error_text = str(e)
                if redact_secrets is not None:
                    try:
                        error_text = str(redact_secrets(error_text) or "")[:4000]
                    except Exception:
                        pass
                results.append(f"Error executing tool: {error_text}")
        return results

    async def _create_plan_via_tool(self, task_desc):
        return None

    def _is_trivial_task(self, task_desc):
        """Return True for conversational input that must not create a plan.

        Planning is reserved for requests that ask NEXUS to do, inspect, make,
        change, search, or run something.  Greetings and short social replies
        should go through the normal response path without touching todo.md,
        emitting plan events, or activating Hive.
        """
        text = re.sub(r"\s+", " ", str(task_desc or "").strip().lower())
        if not text:
            return True
        if len(text) <= 48 and re.fullmatch(
            r"(?:hi|hello|hey|hiya|howdy|yo|good morning|good afternoon|good evening|thanks|thank you|ok|okay|great|nice|cool|bye|goodbye|help|how are you|how do you do|what's up|what is up)\s*[!.?]*",
            text,
        ):
            return True
        return False

    def _requires_planning(self, task_desc, perceived=None) -> bool:
        """Decide whether this turn needs PAORR planning and execution.

        Intent classification is useful context, but verbs and request shape
        are the authority here.  A factual question such as ``what is AI?``
        should not create a todo plan merely because perception labels it as
        research; an explicit request to search, edit, run, or investigate
        should.
        """
        learned_decision = getattr(perceived, "metadata", {}).get("planning_required") if perceived is not None else None
        # A route model may under-classify an explicit action request. Treat a
        # learned `false` as a hint only; the deterministic request-shape
        # checks below must still force planning for run/search/edit/file/MCP/
        # Hive work. A learned `true` remains useful for longer implicit tasks.
        if learned_decision is True:
            return True

        text = re.sub(r"\s+", " ", str(task_desc or "").strip().lower())
        if self._is_trivial_task(text):
            return False

        actionable = re.search(
            r"\b(?:build|create|write|implement|edit|modify|refactor|fix|debug|test|run|execute|deploy|install|remove|delete|read|inspect|open|review|analy[sz]e|compare|search|research|investigate|look\s+up|find|download|generate|design|update|change|set\s+up)\b",
            text,
        )
        explicit_research = re.search(r"\b(?:current|latest|today|news|web|internet|source|sources|citation|citations)\b", text)
        has_workspace_target = bool(re.search(r"(?:[a-z0-9_.-]+\.(?:py|ts|tsx|js|json|md|yaml|yml|toml|html|css)|repo|repository|project|codebase|files?)\b", text))
        multi_step = bool(re.search(r"\b(?:then|after that|and then|step by step|multiple|all of|end to end)\b", text))
        question_only = text.endswith("?") and not actionable and not explicit_research and not has_workspace_target

        if question_only:
            return False
        if actionable or explicit_research or has_workspace_target or multi_step:
            return True

        # Long, imperative requests are usually execution work even when the
        # exact verb is domain-specific; short conversational prose is not.
        return len(text.split()) >= 24 and not text.endswith("?")

    @staticmethod
    def _should_auto_hive(task_desc: str) -> bool:
        """Use Hive automatically only when parallel reasoning is useful."""
        text = re.sub(r"\s+", " ", str(task_desc or "").strip().lower())
        if not text:
            return False
        if re.search(
            r"\b(?:parallel|multiple|all of|end[- ]to[- ]end|full architecture|"
            r"compare|research|investigate|deep dive|refactor|migration|"
            r"sub[- ]agent|specialist)\b",
            text,
        ):
            return True
        action_count = len(re.findall(
            r"\b(?:build|create|implement|edit|modify|refactor|fix|debug|test|"
            r"run|execute|deploy|install|read|inspect|review|analy[sz]e|"
            r"search|research|find|generate|design|update|change)\b",
            text,
        ))
        return action_count >= 2 and len(text.split()) >= 10

    async def _decide_planning(self, perceived) -> None:
        """Let V5 choose the complete execution route for this turn.

        The result is stored as internal metadata consumed by planning, Hive,
        MCP/tool selection, and phase-model routing.  The model chooses the
        route; the deterministic fallback is used only when unavailable or
        when the response is malformed.
        """
        metadata = getattr(perceived, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            perceived.metadata = metadata
        request = str(getattr(perceived, "original_input", "") or "")
        fallback_plan = self._requires_planning(request, None)
        auto_hive = fallback_plan and self._should_auto_hive(request)
        # The router must not turn greetings/social conversation into fake
        # execution plans, even if a provider over-predicts PLAN.
        if self._is_trivial_task(request):
            metadata.update({
                "planning_required": False,
                "planning_decision": "conversation:direct",
                "tool_route": "none",
                "hive_required": False,
                "hive_auto": False,
                "mcp_required": False,
                "model_route": "fast",
                "permission_route": "auto",
                "sandbox_route": "no_sandbox",
                "voice_route": False,
                "skills_route": False,
                "plugins_route": True,
                "compact_route": False,
                "evolution_route": False,
                "forge_route": False,
                "gap_finder_route": False,
                "background_route": False,
                "decision_source": "conversation-boundary",
            })
            return
        try:
            raw = await self._safe_model_call([
                {
                    "role": "system",
                    "content": (
                        "You are NEXUS's execution router. Decide how NEXUS should handle "
                        "the request. Reply with one compact JSON object only: "
                        '{"mode":"PLAN"|"DIRECT","tool":"none"|"read"|"write"|"command"|"search"|"mixed",'
                        '"hive":true|false,"mcp":true|false,"model":"fast"|"strong",'
                        '"permission":"auto"|"ask"|"allowlist","sandbox":"normal"|"docker"|"no_sandbox",'
                        '"voice":true|false,"skills":true|false,"plugins":true|false,"compact":true|false,'
                        '"evolution":true|false,"forge":true|false,"gap_finder":true|false,"background":true|false}. '
                        "Use PLAN for coordinated work, tools, file/code changes, commands, "
                        "research, debugging, or multi-step execution. Use DIRECT for simple "
                        "answers and conversation. Use HIVE only when parallel specialist work "
                        "materially helps. Use MCP only when an external MCP capability is needed."
                    ),
                },
                {"role": "user", "content": str(getattr(perceived, "original_input", ""))[:4000]},
            ], timeout=12.0)
            text = str(raw or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.IGNORECASE).strip()
            legacy_decision = re.sub(r"[^a-z]", "", text.lower())
            if legacy_decision.startswith("direct"):
                # The router is advisory.  An actionable request must never
                # lose the planning/execution path because a fast router
                # under-classified it as ordinary conversation.  This is the
                # boundary that keeps requests such as "fix the failing test"
                # from skipping planning entirely.
                if fallback_plan:
                    metadata.update({
                        "planning_required": True,
                        "planning_decision": "model:direct-overridden",
                        "tool_route": "none",
                        "hive_required": auto_hive,
                        "hive_auto": auto_hive,
                        "mcp_required": False,
                        "model_route": "strong",
                        "decision_source": "deterministic-action-boundary",
                    })
                    return
                metadata.update({
                    "planning_required": False,
                    "planning_decision": "model:direct",
                    "tool_route": "none",
                    "hive_required": auto_hive,
                    "hive_auto": auto_hive,
                    "mcp_required": False,
                    "model_route": "fast",
                    "decision_source": "model",
                })
                return
            if legacy_decision.startswith("plan"):
                metadata.update({
                    "planning_required": True,
                    "planning_decision": "model:plan",
                    "tool_route": "none",
                    "hive_required": auto_hive,
                    "hive_auto": auto_hive,
                    "mcp_required": False,
                    "model_route": "strong",
                    "decision_source": "model",
                })
                return
            route = json.loads(text)
            if not isinstance(route, dict):
                raise ValueError("router response is not an object")
            mode = str(route.get("mode", "")).upper()
            if mode not in {"PLAN", "DIRECT"}:
                raise ValueError("router mode is invalid")
            planning_required = mode == "PLAN" or fallback_plan
            tool = str(route.get("tool", "none")).lower()
            if tool not in {"none", "read", "write", "command", "search", "mixed"}:
                tool = "none"
            metadata.update({
                "planning_required": planning_required,
                "planning_decision": (
                    f"model:{mode.lower()}-overridden"
                    if mode == "DIRECT" and fallback_plan
                    else f"model:{mode.lower()}"
                ),
                "tool_route": tool,
                "hive_required": (
                    bool(route.get("hive", False)) and mode == "PLAN"
                ) or auto_hive,
                "hive_auto": auto_hive,
                "mcp_required": bool(route.get("mcp", False)),
                "model_route": (
                    "strong" if planning_required
                    else str(route.get("model", "fast")).lower()
                ),
                "permission_route": str(route.get("permission", "auto")).lower(),
                "sandbox_route": str(route.get("sandbox", "normal")).lower(),
                "voice_route": bool(route.get("voice", False)),
                "skills_route": bool(route.get("skills", True)),
                "plugins_route": bool(route.get("plugins", True)),
                "compact_route": bool(route.get("compact", False)),
                "evolution_route": bool(route.get("evolution", planning_required)),
                "forge_route": bool(route.get("forge", False)),
                "gap_finder_route": bool(route.get("gap_finder", planning_required)),
                "background_route": bool(route.get("background", planning_required)),
                "decision_source": (
                    "deterministic-action-boundary" if fallback_plan and mode == "DIRECT"
                    else "model"
                ),
            })
            if metadata["mcp_required"]:
                current = str(getattr(perceived, "context_summary", "") or "")
                perceived.context_summary = f"{current}\n\n[ROUTE] Use configured MCP capabilities when appropriate.".strip()
            return
        except Exception:
            metadata.update({
                "planning_required": fallback_plan,
                "planning_decision": "fallback",
                # A router outage must never guess a concrete tool, Hive, or
                # MCP route from keywords. The planner receives the complete
                # discovered registry and makes that decision itself.
                "tool_route": "none",
                "hive_required": auto_hive,
                "hive_auto": auto_hive,
                "mcp_required": False,
                "model_route": "strong" if fallback_plan else "fast",
                "permission_route": "auto",
                "sandbox_route": "normal" if fallback_plan else "no_sandbox",
                "voice_route": False,
                "skills_route": True,
                "plugins_route": True,
                "compact_route": False,
                "evolution_route": fallback_plan,
                "forge_route": False,
                "gap_finder_route": fallback_plan,
                "background_route": fallback_plan,
                "decision_source": "fallback",
            })
            metadata["planning_decision"] = "fallback"

    def _apply_execution_policy(self, perceived) -> None:
        """Apply the router's safe runtime decisions to V5 subsystems."""
        metadata = getattr(perceived, "metadata", {}) or {}
        runtime = self.runtime
        runtime.feature_planning = bool(metadata.get("planning_required", True))
        runtime.feature_hive = bool(metadata.get("hive_required", False))
        # The Hive mixin reads this per-turn flag when NEXUS_HIVE is automatic.
        # An explicit NEXUS_HIVE=0 remains a fail-safe override.
        self._v5_auto_hive = bool(metadata.get("hive_auto", False))
        runtime.evolution_enabled = bool(metadata.get("evolution_route", runtime.evolution_enabled))

        # The model may choose the interaction level, but never bypass safety.
        permission = str(metadata.get("permission_route", "auto")).lower()
        permission_name = {"ask": "APPROVE", "allowlist": "PRE_AUTHORIZED"}.get(permission, "AUTO_PILOT")
        try:
            self._set_permission_mode(permission_name)
        except Exception:
            pass

        requested_sandbox = str(metadata.get("sandbox_route", "normal")).lower()
        tool_route = str(metadata.get("tool_route", "none")).lower()
        if tool_route in {"write", "command", "mixed"} and requested_sandbox == "no_sandbox":
            requested_sandbox = "normal"
        try:
            self._set_sandbox_tier(requested_sandbox)
        except Exception:
            pass

        if bool(metadata.get("compact_route", False)):
            try:
                runtime.memory = self._compact_memory(runtime.memory)
            except Exception:
                pass

    def _read_todo_md(self):
        # Canonical plan path is ``workspace/todo.md`` (lowercase, written by
        # the planning tool); ``TODO.md`` is accepted as a legacy fallback so
        # a case-sensitive filesystem never loses the plan (audit P39).
        workspace = os.path.join(self.root_dir, "workspace")
        for name in ("todo.md", "TODO.md"):
            p = os.path.join(workspace, name)
            try:
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8") as f:
                        return f.read()
            except Exception:
                pass
        return ""

    def _save_checkpoint(self, messages, task_desc, turn):
        pass

    def _log_mission_replay(self, tool_calls, observations):
        pass

    def _start_background_finalization(self, *args):
        pass

    @staticmethod
    def _bounded_memory_recall(memory_context: Any, max_chars: int = 8000) -> str:
        """Render every populated memory channel within a fair hard budget.

        A single large session or RAG result must not consume the whole recall
        envelope and hide later channels such as procedural memory.  Short
        channels are kept in full; the remaining budget is shared evenly by
        oversized channels.  The channel order remains stable for predictable
        prompts and tests.
        """
        try:
            limit = max(0, int(max_chars))
        except (TypeError, ValueError):
            limit = 8000
        if memory_context is None or limit <= 0:
            return ""

        channels = (
            ("session_history", "SESSION"),
            ("rag_context", "RAG"),
            ("failure_vaccines", "FAILURES"),
            ("knowledge_context", "KNOWLEDGE"),
            ("episodic", "EPISODIC"),
            ("working", "WORKING"),
            ("semantic", "SEMANTIC"),
            ("procedural", "PROCEDURAL"),
        )
        try:
            from providers.reliability import redact_secrets
        except Exception:
            redact_secrets = None
        blocks: List[str] = []
        for attribute, label in channels:
            value = str(getattr(memory_context, attribute, "") or "").strip()
            if not value:
                continue
            prefix = f"[{label}]"
            block = value if value.upper().startswith(prefix) else f"{prefix}\n{value}"
            if redact_secrets is not None:
                try:
                    block = redact_secrets(block)
                except Exception:
                    pass
            blocks.append(block)

        if not blocks:
            return ""
        separator = "\n\n"
        if len(separator.join(blocks)) <= limit:
            return separator.join(blocks)

        content_budget = max(0, limit - len(separator) * (len(blocks) - 1))
        allocations = [0] * len(blocks)
        pending = set(range(len(blocks)))
        remaining = content_budget
        while pending and remaining > 0:
            share = max(1, remaining // len(pending))
            completed = [index for index in pending if len(blocks[index]) <= share]
            if not completed:
                for index in sorted(pending):
                    amount = min(share, remaining)
                    allocations[index] = amount
                    remaining -= amount
                break
            for index in completed:
                amount = min(len(blocks[index]), remaining)
                allocations[index] = amount
                remaining -= amount
                pending.remove(index)

        # Integer division can leave a few characters undistributed. Give
        # them to channels in stable order without exceeding their content.
        for index, block in enumerate(blocks):
            if remaining <= 0:
                break
            available = len(block) - allocations[index]
            if available <= 0:
                continue
            extra = min(available, remaining)
            allocations[index] += extra
            remaining -= extra

        return separator.join(
            block[: allocations[index]]
            for index, block in enumerate(blocks)
            if allocations[index] > 0
        )[:limit]

    @staticmethod
    def _merge_memory_context(
        context_summary: Any,
        memory_context: Any,
        max_recall_chars: int = 8000,
    ) -> str:
        """Append bounded recall without replacing or duplicating context."""
        current = str(context_summary or "").strip()
        recall = NexusLoopV5._bounded_memory_recall(
            memory_context, max_chars=max_recall_chars
        )
        if not recall:
            return current
        recall_block = f"[RECALL]\n{recall}"
        if recall_block in current:
            return current
        return f"{current}\n\n{recall_block}".strip() if current else recall_block

    def _session_messages(self):
        """Return current conversation messages from runtime memory."""
        return getattr(self.runtime, "memory", [])

    def _persist_turn_message(self, role: str, content: str, turn_id: str,
                              *, kind: str = "") -> None:
        """Persist one user-visible transcript message for refresh/resume.

        The streamed V5 path does not use the legacy ``run()`` voice setup,
        so it must explicitly write its transcript.  Keying by turn id makes
        a reconnect/retry idempotent instead of duplicating the same message.
        """
        role = str(role or "").strip()
        content = str(content or "")
        turn_id = str(turn_id or "").strip()
        if not role or not content or not turn_id:
            return
        memory = getattr(self.runtime, "memory", None)
        if not isinstance(memory, list):
            memory = []
            self.runtime.memory = memory
        for item in reversed(memory):
            if not isinstance(item, dict):
                continue
            if (
                str(item.get("turn_id") or "") == turn_id
                and str(item.get("role") or "") == role
                and (not kind or str(item.get("kind") or "") == kind)
            ):
                item["content"] = content
                if kind:
                    item["kind"] = kind
                self._write_session_bus()
                return
        entry = {"role": role, "content": content, "turn_id": turn_id}
        if kind:
            entry["kind"] = kind
        memory.append(entry)
        self._write_session_bus()

    def _persist_direct_message(self, message: Dict[str, Any], turn_id: str) -> None:
        """Persist model/tool observations before side effects and after each tool.

        Hermes flushes the assistant tool-call block before executing tools and
        flushes each tool result immediately afterward. V5 keeps the same
        durable boundary so a crash cannot erase the exact model decision or
        leave an orphaned tool result out of the next continuation context.
        """
        if not isinstance(message, dict) or not turn_id:
            return
        role = str(message.get("role") or "").strip()
        if role not in {"assistant", "tool"}:
            return
        try:
            entry = {
                "role": role,
                "content": str(message.get("content") or "")[:20000],
                "turn_id": str(turn_id),
                "kind": "tool_call" if role == "assistant" and message.get("tool_calls") else "tool_result" if role == "tool" else "assistant_partial",
            }
            if message.get("tool_calls"):
                entry["tool_calls"] = message["tool_calls"]
            for key in ("name", "tool_call_id"):
                if message.get(key):
                    entry[key] = str(message[key])
            memory = getattr(self.runtime, "memory", None)
            if not isinstance(memory, list):
                memory = []
                self.runtime.memory = memory
            identity = (
                entry["kind"], entry.get("tool_call_id", ""),
                json.dumps(entry.get("tool_calls", []), sort_keys=True, ensure_ascii=False, default=str),
            )
            for existing in reversed(memory):
                if not isinstance(existing, dict) or str(existing.get("turn_id") or "") != str(turn_id):
                    continue
                existing_identity = (
                    str(existing.get("kind") or ""), str(existing.get("tool_call_id") or ""),
                    json.dumps(existing.get("tool_calls", []), sort_keys=True, ensure_ascii=False, default=str),
                )
                if existing_identity == identity:
                    existing.update(entry)
                    self._write_session_bus()
                    return
            memory.append(entry)
            self._write_session_bus()
        except Exception as exc:
            self.logger.debug("direct message persistence failed: %s", exc)

    async def _persist_direct_message_async(self, message: Dict[str, Any], turn_id: str) -> None:
        """Async variant of ``_persist_direct_message``.

        The blocking session-bus write is offloaded to a worker thread so
        the event loop never stalls mid-tool-execution.
        """
        await asyncio.to_thread(self._persist_direct_message, message, turn_id)

    async def _persist_turn_message_async(self, role: str, content: str, turn_id: str,
                                          *, kind: str = "") -> None:
        """Async variant of ``_persist_turn_message``.

        The blocking session-bus write is offloaded to a worker thread so
        the event loop never stalls during transcript persistence.
        """
        await asyncio.to_thread(
            self._persist_turn_message, role, content, turn_id, kind=kind
        )

    # Background tasks set (for test compatibility)
    @property
    def _background_tasks(self):
        if not hasattr(self, "_bg_tasks"):
            self._bg_tasks = set()
        return self._bg_tasks

    @_background_tasks.setter
    def _background_tasks(self, value):
        self._bg_tasks = value

    async def _finalize_session(self, task_desc, messages):
        pass

    def _observe_detached_lifecycle_task(
        self, task: asyncio.Task[Any], *, owner: str
    ) -> None:
        """Consume a detached task's result without letting shutdown await it.

        Cancellation-resistant code may outlive the bounded shutdown window.
        Such a task is deliberately removed from every active-owner set and
        retained only for observability.  Its eventual exception is consumed
        so the event loop never reports an unhandled-task warning.
        """
        self._detached_lifecycle_tasks.add(task)
        self._detached_lifecycle_task_count += 1

        def _finished(completed: asyncio.Task[Any]) -> None:
            self._detached_lifecycle_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                error = completed.exception()
            except asyncio.CancelledError:
                return
            if error is not None:
                self.logger.warning(
                    "Detached lifecycle task %s failed after its owner was fenced: %s",
                    owner,
                    error,
                )
            else:
                self.logger.info(
                    "Detached lifecycle task %s exited after its owner was fenced",
                    owner,
                )

        task.add_done_callback(_finished)

    async def _cancel_tasks_bounded(
        self,
        tasks: set[asyncio.Task[Any]],
        *,
        timeout: float,
        owner: str,
    ) -> set[asyncio.Task[Any]]:
        """Cancel tasks and await them for at most ``timeout`` seconds."""
        active = {task for task in tasks if not task.done()}
        for task in active:
            task.cancel()
        if not active:
            return set()
        done, pending = await asyncio.wait(active, timeout=max(0.0, timeout))
        for task in done:
            if task.cancelled():
                continue
            try:
                task.exception()
            except asyncio.CancelledError:
                pass
        for task in pending:
            self._observe_detached_lifecycle_task(task, owner=owner)
        return pending

    async def _stop_run_context_heartbeat(
        self, turn_id: str, *, timeout: float = 1.0
    ) -> None:
        """Stop, cancel, and boundedly await one turn's lease heartbeat."""
        entry = self._run_context_heartbeats.pop(str(turn_id or ""), None)
        if entry is None:
            return
        stop, task = entry
        stop.set()
        pending = await self._cancel_tasks_bounded(
            {task}, timeout=timeout, owner=f"run-context-heartbeat:{turn_id}"
        )
        if pending:
            self.logger.warning(
                "Run-context heartbeat for %s ignored bounded cancellation and was detached",
                turn_id,
            )

    async def aclose(self):
        """Boundedly drain every V5/V1 background owner."""
        import asyncio as _asyncio
        import os as _os
        try:
            shutdown_timeout = max(
                0.1, float(os.environ.get("NEXUS_SHUTDOWN_TIMEOUT", "10"))
            )
        except (TypeError, ValueError):
            shutdown_timeout = 10.0
        cancellation_timeout = min(1.0, shutdown_timeout)
        self._shutdown_fenced = True
        # Detached work must not publish terminal UI events after this loop has
        # relinquished ownership. Durable jobs are fenced separately below.
        self.work_event_sink = None
        if getattr(self, "runtime", None) is not None:
            self.runtime.work_event_sink = None

        heartbeat_tasks = {
            task for _stop, task in self._run_context_heartbeats.values()
        }
        for stop, _task in self._run_context_heartbeats.values():
            stop.set()
        self._run_context_heartbeats.clear()
        await self._cancel_tasks_bounded(
            heartbeat_tasks,
            timeout=cancellation_timeout,
            owner="run-context-heartbeats",
        )
        stop_scheduler = getattr(self, "_stop_scheduler", None)
        if callable(stop_scheduler):
            try:
                stop_scheduler()
            except Exception:
                self.logger.debug("Could not stop scheduler", exc_info=True)
        stop_watchdog = getattr(self, "_stop_durable_background_watchdog", None)
        if callable(stop_watchdog):
            try:
                watchdog_stop_task = asyncio.create_task(stop_watchdog())
                stopped, still_stopping = await asyncio.wait(
                    {watchdog_stop_task}, timeout=cancellation_timeout
                )
                if stopped:
                    await asyncio.gather(*stopped, return_exceptions=True)
                if still_stopping:
                    await self._cancel_tasks_bounded(
                        still_stopping,
                        timeout=cancellation_timeout,
                        owner="durable-background-watchdog",
                    )
            except Exception:
                self.logger.debug("Could not stop durable background watchdog", exc_info=True)
        task_sets = [
            getattr(self, "_background_tasks", set()),
            getattr(self, "_v5_bg", set()),
            getattr(self, "_v5_runner_tasks_set", set()),
        ]
        tasks = {
            task for task_set in task_sets if isinstance(task_set, set)
            for task in task_set if isinstance(task, _asyncio.Task)
        }
        if tasks:
            done, pending = await _asyncio.wait(tasks, timeout=shutdown_timeout)
            if done:
                await _asyncio.gather(*done, return_exceptions=True)
            if pending:
                try:
                    self._durable_background_store().interrupt_owned(
                        _os.getpid(), "loop shutdown interrupted active job"
                    )
                except Exception:
                    self.logger.debug("Could not persist interrupted background jobs", exc_info=True)
                for task in pending:
                    task.cancel()
                cancelled_done, resistant = await _asyncio.wait(
                    pending, timeout=cancellation_timeout
                )
                if cancelled_done:
                    await _asyncio.gather(*cancelled_done, return_exceptions=True)
                for task in resistant:
                    self._observe_detached_lifecycle_task(
                        task, owner="v5-background-shutdown"
                    )
                if resistant:
                    self.logger.warning(
                        "Detached %d cancellation-resistant V5 background task(s)",
                        len(resistant),
                    )
        self._background_tasks = set()
        self._v5_bg = set()
        self._v5_runner_tasks_set = set()

    async def _retry_gap(self, gap):
        return False

    # ── ObservationCache (V1 class used by tests) ────────────────────────

    class ObservationCache:
        """V1-compat: simple max-size observation cache for deduplication."""
        __slots__ = ("_max_size", "_entries")

        def __init__(self, max_size: int = 20):
            self._max_size = max(1, int(max_size))
            self._entries: list = []

        def add(self, observation):
            self._entries.append(observation)
            if len(self._entries) > self._max_size:
                self._entries.pop(0)

        def __iter__(self):
            return iter(self._entries)

        def __len__(self):
            return len(self._entries)

        def __contains__(self, item):
            return item in self._entries

    @property
    def is_running(self) -> bool:
        guard = getattr(self, "_run_guard", None)
        return bool(guard and guard.locked())

    def reset(self) -> bool:
        """Compatibility reset used by GUI/API before a fresh chat turn."""
        if self.is_running:
            return False
        # A completed run clears its own abort signal in ``run``/``stream_run``
        # finally blocks.  Keep reset idempotent for compatibility, but do not
        # clear a signal while a run is active.
        self._abort_flag.clear()
        self._current_turn_id = ""
        runtime = getattr(self, "runtime", None)
        if runtime is not None:
            runtime.current_turn = None
            runtime.turn_history = []
            runtime.memory = []
            if hasattr(runtime, "last_result"):
                runtime.last_result = None
        self._stage_started_at.clear()
        self._tool_started_at.clear()
        self._stream_events.clear()
        self._last_run_failed = False
        self._last_run_had_tool_execution = False
        self._last_run_verified = False
        return True

    def request_abort(self, turn_id: str, reason: str = "user_cancelled") -> bool:
        """Request cancellation for one active or pre-start registered run."""
        target = str(turn_id or "").strip()
        if not target:
            return False
        control = self._run_controls.get(target)
        if control is None and target != str(getattr(self, "_current_turn_id", "") or ""):
            return False
        self._run_controls.request_cancel(target, reason)
        return True

    # ── Main API ────────────────────────────────────────────────────────

    @property
    def brain(self):
        """Lazily re-fetches the MoE brain from kernel (supports monkeypatching)."""
        if self.kernel is not None:
            instances = getattr(self.kernel, "_instances", None)
            if isinstance(instances, dict) and "moe" in instances:
                return instances["moe"]
            moe = getattr(self.kernel, "moe", None)
            if moe is not None:
                return moe
        return self._brain

    @property
    def memory(self):
        """V1-compat: short-term conversation memory."""
        return self.runtime.memory

    @memory.setter
    def memory(self, value):
        self.runtime.memory = value

    def configure_thinking(self, enabled: bool) -> None:
        """Toggle thinking mode on the kernel MoE router."""
        self.runtime.thinking_mode = enabled
        brain = getattr(self, "brain", None)
        if brain and hasattr(brain, "configure_thinking"):
            brain.configure_thinking(enabled)

    def set_work_event_sink(self, sink: Optional[Callable]) -> None:
        """Attach a sink that receives every canonical work event payload."""
        self.runtime.work_event_sink = sink
        self.work_event_sink = sink

    async def run(
        self,
        user_input: str,
        input_type: str = "text",
        voice_mode: bool = False,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        task_id: str = "",
        idempotency_key: str = "",
        execution_fence: Optional[Callable[[], bool]] = None,
        deadline_seconds: Optional[float] = None,
        deadline_at: Optional[float] = None,
    ) -> Any:
        """Run a single turn through the V5 loop. Returns dict (V5) or str (V1 compat)."""
        if not self._run_guard.acquire(blocking=False):
            raise RuntimeError("A NEXUS V5 run is already active for this session")

        # Voice mode: sync + clean + append to memory (V1 compat)
        if voice_mode:
            self.sync_memory()
            clean_desc = user_input
            if "\n\n[VOICE_MODE]:" in clean_desc:
                clean_desc = clean_desc.split("\n\n[VOICE_MODE]:")[0]
            elif "[VOICE_MODE]:" in clean_desc:
                clean_desc = clean_desc.split("[VOICE_MODE]:")[0]
            clean_desc = clean_desc.strip()
            self.runtime.memory.append({"role": "user", "content": clean_desc})
            self.runtime.memory.append({"role": "assistant", "content": ""})
            self._write_session_bus()

        try:
            result: Dict[str, Any] = {
                "success": False,
                "error": "Turn produced no result",
                "state": V5LoopState.FAILED.value,
            }
            response_parts: List[str] = []
            async for event in self._turn_events(
                user_input,
                input_type=input_type,
                voice_mode=voice_mode,
                provider=provider,
                profile=profile,
                model=model,
                max_tokens=max_tokens,
                conversation_history=conversation_history,
                task_id=task_id,
                idempotency_key=idempotency_key,
                execution_fence=execution_fence,
                deadline_seconds=deadline_seconds,
                deadline_at=deadline_at,
            ):
                if event.get("type") == "content":
                    response_parts.append(str(event.get("data", "")))
                if event["type"] == "done":
                    result = event["data"]
            # Post-turn memory persistence, gated on verified tool evidence.
            if self._memory_manager is not None:
                try:
                    verified_actions, tool_results = self._verified_evidence_from_result(result)
                    await asyncio.to_thread(
                        asyncio.run,
                        self._memory_manager.sync_all(
                            user_input,
                            str(result.get("response") or ""),
                            verified_actions=verified_actions,
                            tool_results=tool_results,
                        ),
                    )
                except Exception as e:
                    self.logger.warning(f"Memory sync failed: {e}")
            # Per-turn learning signals (tool failures, reflections, turn
            # replay) are collected inside ``_turn_events`` exactly once per
            # turn; here only deferred background finalization is scheduled.
            self._start_background_finalization(
                user_input, self._session_messages(), bool(result.get("success"))
            )
            # V1 compat: if the turn used the V1 compat path, return the response string
            if result.get("used_v1_compat"):
                response = result.get("response", "")
                if voice_mode:
                    return self._clean_voice_response(response)
                return response
            return result
        finally:
            self._run_controls.unregister(getattr(self, "_current_turn_id", ""))
            self._run_guard.release()
            # Clear only after the generator has fully terminated.  Clearing
            # at the top of ``_turn_events`` loses a cancellation that arrives
            # after scheduling but before the generator's first iteration.
            self._abort_flag.clear()

    async def stream_run(
        self,
        task_desc: str,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        voice_mode: bool = False,
        turn_id: str = "",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        task_id: str = "",
        idempotency_key: str = "",
        execution_fence: Optional[Callable[[], bool]] = None,
        deadline_seconds: Optional[float] = None,
        deadline_at: Optional[float] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream V5 loop execution with real-time events.

        Acquires the run-guard lock exactly once, then relays everything the
        shared ``_turn_events`` generator produces.

        Args:
            task_desc: Task description
            provider: Optional provider override
            model: Optional model override
            max_tokens: Optional max tokens
            voice_mode: Enable voice mode
            turn_id: Optional turn ID

        Yields:
            Dicts: {"type": "content", "data": str} for streamed answer text,
            {"type": "status", "data": {event}} for lifecycle events, and
            {"type": "done", "data": {result}} at the end.
        """
        if not self._run_guard.acquire(blocking=False):
            raise RuntimeError("A NEXUS V5 run is already active for this session")
        deadline_at = deadline_at or (time.monotonic() + float(deadline_seconds) if deadline_seconds else None)
        if turn_id:
            self._run_controls.register(turn_id, deadline_at=deadline_at)

        done_result: Optional[Dict[str, Any]] = None
        try:
            async for event in self._turn_events(
                task_desc,
                input_type="text",
                voice_mode=voice_mode,
                provider=provider,
                profile=profile,
                model=model,
                max_tokens=max_tokens,
                turn_id=turn_id,
                conversation_history=conversation_history,
                task_id=task_id,
                idempotency_key=idempotency_key,
                execution_fence=execution_fence,
                deadline_seconds=deadline_seconds,
                deadline_at=deadline_at,
            ):
                if event.get("type") == "done" and isinstance(event.get("data"), dict):
                    done_result = event["data"]
                yield event
        finally:
            self._run_controls.unregister(getattr(self, "_current_turn_id", ""))
            self._run_guard.release()
            self._abort_flag.clear()

        # Post-turn memory persistence, gated on verified tool evidence.  Runs
        # off the event loop in a fresh loop so streaming is never blocked.
        if done_result and self._memory_manager is not None:
            try:
                verified_actions, tool_results = self._verified_evidence_from_result(done_result)
                await asyncio.to_thread(
                    asyncio.run,
                    self._memory_manager.sync_all(
                        task_desc,
                        str(done_result.get("response") or ""),
                        verified_actions=verified_actions,
                        tool_results=tool_results,
                    ),
                )
            except Exception as e:
                self.logger.warning(f"Memory sync failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # SHARED TURN PIPELINE
    # ─────────────────────────────────────────────────────────────────────────

    async def _turn_events(
        self,
        task_desc: str,
        *,
        input_type: str = "text",
        voice_mode: bool = False,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        turn_id: str = "",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        task_id: str = "",
        idempotency_key: str = "",
        execution_fence: Optional[Callable[[], bool]] = None,
        deadline_seconds: Optional[float] = None,
        deadline_at: Optional[float] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Contain setup failures so a caller always receives a terminal result.

        The implementation below owns the normal lifecycle and its existing
        timeout/cancel handling.  This outer boundary covers the small but
        important preflight window before that lifecycle's inner ``try`` starts
        (transcript restore, run registration, persistence, and ``run.started``).
        A failure there must not leave a client waiting forever or a durable run
        looking permanently active.
        """
        active_turn_id = str(turn_id or "")
        try:
            async for event in self._turn_events_impl(
                task_desc,
                input_type=input_type,
                voice_mode=voice_mode,
                provider=provider,
                profile=profile,
                model=model,
                max_tokens=max_tokens,
                turn_id=turn_id,
                conversation_history=conversation_history,
                task_id=task_id,
                idempotency_key=idempotency_key,
                execution_fence=execution_fence,
                deadline_seconds=deadline_seconds,
                deadline_at=deadline_at,
            ):
                if event.get("type") == "done" and isinstance(event.get("data"), dict):
                    active_turn_id = str(
                        event["data"].get("turn_id") or active_turn_id
                    )
                yield event
        except asyncio.CancelledError:
            # A caller's explicit stop is a run-level decision and is handled
            # by stream_run/_turn_events' cancellation contract.
            raise
        except Exception as exc:
            failure = str(exc) or exc.__class__.__name__
            self.logger.error("V5 turn failed before terminal lifecycle: %s", failure, exc_info=True)
            fallback_turn_id = str(turn_id or getattr(self, "_current_turn_id", "") or "")
            if not fallback_turn_id:
                try:
                    fallback_turn_id = self._generate_turn_id()
                except Exception:
                    fallback_turn_id = "turn_failed"
            try:
                await self._emit_runtime_event(
                    "run.failed",
                    "Run failed before execution started",
                    "failed",
                    event_id=f"run_{fallback_turn_id}",
                    task_id=task_id,
                    error=failure,
                )
                for event in self._yield_pending_events():
                    yield event
            except Exception:
                self.logger.debug("Could not emit preflight failure event", exc_info=True)
            yield {
                "type": "done",
                "data": {
                    "success": False,
                    "error": failure,
                    "response": "",
                    "output": {"response": ""},
                    "mental_state": {},
                    "turn_id": fallback_turn_id,
                    "state": V5LoopState.FAILED.value,
                },
            }
        finally:
            heartbeat_turn_id = str(
                active_turn_id or getattr(self, "_current_turn_id", "") or ""
            )
            if heartbeat_turn_id:
                await self._stop_run_context_heartbeat(heartbeat_turn_id)

    async def _turn_events_impl(
        self,
        task_desc: str,
        *,
        input_type: str = "text",
        voice_mode: bool = False,
        provider: Optional[str] = None,
        profile: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        turn_id: str = "",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        task_id: str = "",
        idempotency_key: str = "",
        execution_fence: Optional[Callable[[], bool]] = None,
        deadline_seconds: Optional[float] = None,
        deadline_at: Optional[float] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Shared private turn pipeline used by run() and stream_run().

        Runs the full 7-phase V5 pipeline and yields status/content/done
        events. All exceptions are contained: the turn transitions to FAILED,
        failure events are emitted, and a done event with success=False is
        always yielded so consumers can never hang.
        """
        self._stream_events.clear()
        # These are per-run values. Reusing them across turns eventually
        # exhausts every later task and can write a prior success into a new
        # failed turn's checkpoint.
        init_budget = getattr(self, "_init_budget", None)
        if callable(init_budget):
            init_budget(reset=True)
        self._degradations = []
        self.runtime.last_result = None
        self.runtime.actions = []
        self.runtime.plan = {}

        # API callers may reset the transient runtime before a new request.
        # Restore the prior transcript as data only; tool side effects are
        # never replayed automatically, but the model keeps the context it
        # needs for follow-ups and repair decisions.
        if isinstance(conversation_history, list):
            restored: List[Dict[str, Any]] = []
            for item in conversation_history[-80:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                if role not in {"user", "assistant", "tool"}:
                    continue
                content = item.get("content", "")
                if not isinstance(content, str):
                    content = ""
                entry: Dict[str, Any] = {"role": role, "content": content[:20000]}
                if role == "assistant" and isinstance(item.get("tool_calls"), list):
                    entry["tool_calls"] = item["tool_calls"][:32]
                for key in ("name", "tool_call_id"):
                    if item.get(key):
                        entry[key] = str(item[key])[:200]
                restored.append(entry)
            self.runtime.memory = restored

        if voice_mode:
            task_desc = self._clean_voice_input(task_desc)

        turn = V5TurnContext(
            turn_id=turn_id or self._generate_turn_id(),
            session_id=self.session_id,
            user_input=task_desc,
            input_type=input_type,
            metadata={"idempotency_key": str(idempotency_key or "")}
            if idempotency_key else {},
        )
        self.runtime.current_turn = turn
        self._current_turn_id = turn.turn_id
        self._active_execution_plan = {}
        if deadline_at is None and deadline_seconds:
            deadline_at = time.monotonic() + float(deadline_seconds)
        control = self._run_controls.register(turn.turn_id, deadline_at=deadline_at)
        control.execution_fence = execution_fence

        # Save the user message before model/tool work starts.  If the process
        # or browser disappears mid-run, refresh can still show the exact turn
        # and continuity inspection can offer a truthful resume.
        self.sync_memory()
        self._persist_turn_message("user", task_desc, turn.turn_id)

        # Durable run identity is separate from the chat transcript.  A
        # process crash can therefore leave a truthful non-terminal record
        # that the next session can offer to resume instead of guessing from
        # an incomplete assistant message.
        run_context = None
        run_context_heartbeat_stop = asyncio.Event()
        run_context_heartbeat_task = None
        try:
            from nexus.run_context import start_run_context

            run_context = start_run_context(
                root=self.root_dir,
                session_id=self.session_id,
                run_id=turn.turn_id,
                task_id=task_id,
                prompt=task_desc,
                provider=provider,
                model=model,
                max_tokens=max_tokens,
                voice_mode=voice_mode,
                lease_seconds=900,
            )
            self._current_run_context = run_context
            async def _renew_run_context_lease() -> None:
                while not run_context_heartbeat_stop.is_set():
                    try:
                        await asyncio.wait_for(
                            run_context_heartbeat_stop.wait(), timeout=300.0
                        )
                        return
                    except asyncio.TimeoutError:
                        renewed = await asyncio.to_thread(
                            run_context.heartbeat, 900.0
                        )
                        if not renewed:
                            self._run_controls.request_cancel(
                                turn.turn_id, "run_context_lease_lost"
                            )
                            return

            run_context_heartbeat_task = asyncio.create_task(
                _renew_run_context_lease()
            )
            self._run_context_heartbeats[turn.turn_id] = (
                run_context_heartbeat_stop,
                run_context_heartbeat_task,
            )
        except Exception as exc:
            self.logger.debug("Could not persist run start: %s", exc)

        if task_id:
            try:
                from nexus.work_items import load_work_item, persist_work_item
                item = load_work_item(self.root_dir, self.session_id, task_id)
                if item is not None:
                    item.transition("running", run_id=turn.turn_id, reason="run.started")
                    persist_work_item(item)
            except Exception as exc:
                self.logger.debug("Could not persist work-item start: %s", exc)

        def finish_run_context(status: str, terminal_event: str, error: str = "") -> None:
            run_context_heartbeat_stop.set()
            self._current_run_context = None
            if run_context is None:
                return
            try:
                run_context.finish(status, terminal_event, error)
            except Exception as exc:
                self.logger.debug("Could not persist run finish: %s", exc)
            if task_id:
                try:
                    from nexus.work_items import load_work_item, persist_work_item
                    item = load_work_item(self.root_dir, self.session_id, task_id)
                    if item is not None:
                        target = {"success": "applied", "timed_out": "failed"}.get(status, status)
                        if target in {"failed", "cancelled", "applied"}:
                            item.transition(target, run_id=turn.turn_id, reason=error or terminal_event)
                            persist_work_item(item)
                except Exception as exc:
                    self.logger.debug("Could not persist work-item finish: %s", exc)

        try:
            await self._emit_runtime_event(
                "run.started",
                "Run started",
                "running",
                event_id=f"run_{turn.turn_id}",
                payload={"input_type": input_type, "voice_mode": voice_mode},
                task_id=task_id,
            )
        except Exception as exc:
            # The durable context was created before the first lifecycle
            # event. If that event sink fails, close the context explicitly so
            # recovery never sees a run that is permanently "running".
            failure = str(exc) or exc.__class__.__name__
            finish_run_context("failed", "run.failed", failure)
            try:
                await self._transition_to(V5LoopState.FAILED)
            except Exception:
                self.logger.debug("Could not transition failed preflight turn", exc_info=True)
            turn.end_time = datetime.now(timezone.utc)
            try:
                await self._emit_runtime_event(
                    "run.failed",
                    "Run failed before execution started",
                    "failed",
                    event_id=f"run_{turn.turn_id}",
                    task_id=task_id,
                    error=failure,
                )
                for event in self._yield_pending_events():
                    yield event
            except Exception:
                self.logger.debug("Could not emit preflight terminal event", exc_info=True)
            yield {"type": "done", "data": {
                "success": False,
                "error": failure,
                "response": "",
                "output": {"response": ""},
                "mental_state": {},
                "turn_id": turn.turn_id,
                "state": V5LoopState.FAILED.value,
            }}
            return

        mental_state: Dict[str, Any] = {}
        output: Dict[str, Any] = {}

        try:
            # Phase 0: Meta-Learning (if enabled)
            if self.runtime.meta_learning_enabled:
                await self._transition_to(V5LoopState.INITIALIZING)
                try:
                    await self._meta_learning_optimize()
                except Exception as e:
                    self.logger.warning(f"Meta-learning phase failed: {e}")
            for event in self._yield_pending_events():
                yield event

            # The live path is still transcript-driven, but the canonical
            # lifecycle now makes one model-driven route decision before the
            # tool loop.  This activates planning/Hive/MCP policy and emits
            # truthful lifecycle evidence without mapping keywords to tools.
            context_summary = ""
            planning_gate_error = ""
            perceived = await self._perceive_input(turn)
            inject_skill = getattr(self, "_inject_skill_context", None)
            if callable(inject_skill):
                await inject_skill(perceived)
            effective_task_desc = str(
                getattr(perceived, "original_input", "") or task_desc
            )
            conversational = self._is_trivial_task(effective_task_desc)
            if not conversational:
                await self._transition_to(V5LoopState.PLANNING)
                await self._emit_runtime_event(
                    "planning.started",
                    "Choosing an execution route",
                    "running",
                    event_id=f"planning_{turn.turn_id}",
                    parent_id=f"run_{turn.turn_id}",
                    payload={"input_type": input_type},
                    visibility="internal",
                )
            await self._decide_planning(perceived)
            self._apply_execution_policy(perceived)
            route_metadata = dict(getattr(perceived, "metadata", {}) or {})
            if bool(route_metadata.get("planning_required")):
                # The live direct loop is the execution authority, but plans
                # must still be produced by and persisted through the real
                # planning tool before acting.  The old PAORR block below is
                # unreachable after the direct loop return, so do not rely on
                # it to create a plan.
                try:
                    planned_steps = await self._plan_with_tool(perceived)
                    if planned_steps:
                        plan_context = "\n\n[ACTIVE EXECUTION PLAN]\n" + "\n".join(
                            f"{index}. {step.get('description', '')}"
                            for index, step in enumerate(planned_steps, start=1)
                            if isinstance(step, dict) and step.get("description")
                        )
                        perceived.context_summary = (
                            f"{getattr(perceived, 'context_summary', '')}{plan_context}"
                        ).strip()
                    else:
                        planning_gate_error = "planning required but no executable plan was produced"
                        detail = str(getattr(self, "_last_planning_error", "") or "").strip()
                        if detail:
                            planning_gate_error += f": {detail[:4000]}"
                except Exception as exc:
                    planning_gate_error = (
                        "planning required but plan generation failed"
                    )
                    self.logger.warning(
                        "Live plan generation failed; stopping before tool execution: %s",
                        exc,
                    )
                if planning_gate_error:
                    await self._emit_runtime_event(
                        "planning.failed",
                        "No executable plan was produced",
                        "failed",
                        event_id=f"planning_failed_{turn.turn_id}",
                        parent_id=f"planning_{turn.turn_id}",
                        payload={
                            "planning_required": True,
                            "error": planning_gate_error,
                        },
                        visibility="internal",
                    )
                    # A planner outage must not erase durable continuation
                    # context. Allow one explicit direct-loop fallback, but
                    # require a real tool result before accepting success.
                    context_summary = (
                        f"{getattr(perceived, 'context_summary', '')}\n\n"
                        "[PLANNING FALLBACK]\n"
                        "The required planner did not produce an executable plan. "
                        "You may proceed only with a justified registered tool call; "
                        "a prose-only answer is not completion."
                    ).strip()
                    await self._emit_runtime_event(
                        "planning.fallback",
                        "Using verified direct-loop fallback",
                        "running",
                        event_id=f"planning_fallback_{turn.turn_id}",
                        parent_id=f"planning_{turn.turn_id}",
                        payload={"reason": planning_gate_error, "requires_tool_result": True},
                        visibility="internal",
                    )
            if not conversational:
                await self._emit_runtime_event(
                    "planning.decided",
                    "Execution route selected" if not planning_gate_error else "Execution blocked",
                    "completed" if not planning_gate_error else "failed",
                    event_id=f"planning_decided_{turn.turn_id}",
                    parent_id=f"planning_{turn.turn_id}",
                    payload={
                        "planning_required": bool(route_metadata.get("planning_required")),
                        "planning_succeeded": not bool(planning_gate_error),
                        "hive_required": bool(route_metadata.get("hive_required")),
                        "mcp_required": bool(route_metadata.get("mcp_required")),
                        "decision_source": route_metadata.get("decision_source", "unknown"),
                    },
                )
            await self._inject_hive_context(perceived)
            if getattr(perceived, "context_summary", ""):
                context_summary = str(getattr(perceived, "context_summary", ""))[:10000]
            await self._transition_to(V5LoopState.ACTING)
            self._check_abort()
            self._check_deadline()
            context_summary = context_summary or ""
            if self._memory_manager is not None and hasattr(self._memory_manager, "prefetch_all"):
                try:
                    # Perception already fetched the same turn's memory
                    # context. Reuse that immutable snapshot instead of
                    # launching the four-way memory fan-out a second time.
                    ctx = turn.metadata.get("_memory_context")
                    if ctx is None:
                        ctx = await self._memory_manager.prefetch_all(effective_task_desc)
                    context_summary = self._merge_memory_context(
                        context_summary, ctx
                    )
                except Exception as exc:
                    self.logger.debug("Direct-loop memory prefetch failed: %s", exc)

            # Close the learning read-half: surface collected
            # failures/reflections so the model can avoid repeating
            # known-bad actions. Runs EVERY turn (placed outside the
            # memory-prefetch branch, because perception always
            # pre-populates turn.metadata["_memory_context"], so a
            # nested injection would silently never fire). Bounded,
            # best-effort, never raises.
            try:
                learn_digest = ""
                learn_fn = getattr(self, "learning_signals_digest", None)
                if callable(learn_fn):
                    try:
                        learn_digest = learn_fn()
                    except Exception:
                        learn_digest = ""
                if learn_digest:
                    context_summary = (
                        f"{context_summary}\n\n[LEARNING]\n{learn_digest}"
                    ).strip()

                # Close the self-evolution read-half: the durable
                # improvement backlog (written by _evolve_self_improve
                # / _evolve_gap_forge) was write-only -- nothing ever
                # read it back, so Nexus recorded how to improve but
                # never applied it. Surface the top pending action(s)
                # as model-visible context and mark them in_progress so
                # they are not re-proposed on every future session.
                # All backlog I/O runs in a worker thread so it never
                # blocks the event loop (the synchronous open()/os.replace
                # would otherwise stall SSE streaming and heartbeat tasks).
                try:
                    from evolution.backlog import (
                        pending_actions, mark_action_status
                    )
                    pending = await asyncio.to_thread(
                        pending_actions, self.root_dir
                    )
                    surfaced = []
                    for action in pending[:3]:
                        label = str(action.get("action") or "").strip()
                        if not label:
                            continue
                        surfaced.append("- " + label[:200])
                        try:
                            await asyncio.to_thread(
                                mark_action_status,
                                action.get("id"), "in_progress", self.root_dir
                            )
                        except Exception:
                            pass
                    if surfaced:
                        evolve_digest = "Pending self-improvement actions (consider applying):\n" + "\n".join(surfaced)
                        context_summary = (
                            f"{context_summary}\n\n[SELF-EVOLUTION]\n{evolve_digest}"
                        ).strip()
                except Exception:
                    pass
            except Exception:
                pass
            try:
                skills = self._skills_index_text()
                if skills:
                    context_summary = f"{context_summary}\n\n{skills}".strip()
            except Exception:
                pass
            # Explicit continuation requests receive the latest durable
            # checkpoint evidence, including the prior plan/actions/results.
            # The model still decides whether to continue; this does not run
            # a second loop or replay tools blindly.
            if any(token in task_desc.lower() for token in (
                "continue", "resume", "carry on", "keep going", "finish it",
            )):
                try:
                    from memory.continuity import inspect_continuity
                    continuity = inspect_continuity(self.root_dir, self.session_id)
                    if continuity.available and continuity.run_id:
                        checkpoint = self._checkpoint_load(continuity.run_id)
                        if checkpoint:
                            evidence = {
                                "run_id": continuity.run_id,
                                "status": continuity.status,
                                "checkpoint": checkpoint.get("file", ""),
                                "phase": checkpoint.get("phase", ""),
                                "plan": checkpoint.get("plan"),
                                "actions": checkpoint.get("actions"),
                                "mental_state": checkpoint.get("mental_state"),
                            }
                            context_summary = (
                                f"{context_summary}\n\n[RESUME CHECKPOINT EVIDENCE]\n"
                                f"{json.dumps(evidence, ensure_ascii=False, default=str)[:12000]}"
                            ).strip()
                except Exception as exc:
                    self.logger.debug("Resume checkpoint context unavailable: %s", exc)
            result = await self._run_direct_model_tool_loop(
                effective_task_desc, context_summary=context_summary,
                conversation_history=self._session_messages(),
                provider=provider, profile=profile, model=model,
                max_tokens=max_tokens,
            )
            # Surface every degraded subsystem/fallback the turn hit so users
            # are never shown a silent half-success story.
            _degradations = list(getattr(self, "_degradations", []) or [])
            _extra = result.get("degradation") if isinstance(result, dict) else None
            if isinstance(_extra, list):
                _degradations.extend(str(item) for item in _extra)
            if _degradations and isinstance(result, dict):
                result["degradation"] = sorted(set(_degradations))

            if planning_gate_error:
                fallback_calls = int(result.get("calls_executed", 0) or 0)
                fallback_verified = bool(result.get("success")) and fallback_calls > 0
                result["planning_fallback"] = True
                result["planning_error"] = planning_gate_error
                if not fallback_verified:
                    response = (
                        "I couldn't complete this actionable request because no "
                        "executable plan was produced and the direct fallback did not "
                        "produce a verified tool result."
                    )
                    result.update({
                        "success": False,
                        "response": response,
                        "error": planning_gate_error,
                        "verification": self._verification_payload(
                            result.get("actions") or [],
                            fallback_calls,
                            response,
                            planning_gate_error,
                        ),
                    })
            for event in self._yield_pending_events():
                yield event
            if not isinstance(result, dict):
                result = {"success": False, "result": result}

            # Forward only provider-reported telemetry.  The direct loop may
            # use conservative estimates internally for safety limits, but
            # those estimates are intentionally never exposed as UI usage.
            measured = getattr(self, "_last_turn_usage", None)
            if isinstance(measured, dict) and (
                int(measured.get("input_tokens", 0) or 0)
                or int(measured.get("output_tokens", 0) or 0)
            ):
                result["usage"] = {
                    "source": "provider",
                    "available": True,
                    "input_tokens": int(measured.get("input_tokens", 0) or 0),
                    "output_tokens": int(measured.get("output_tokens", 0) or 0),
                    "reasoning_tokens": int(measured.get("reasoning_tokens", 0) or 0),
                    "total_tokens": int(measured.get("input_tokens", 0) or 0)
                    + int(measured.get("output_tokens", 0) or 0),
                    "context_tokens": int(measured.get("context_tokens", 0) or 0),
                    "context_window": self._context_window_for_provider(provider, model),
                }
            budget_report = getattr(self, "_budget_report", None)
            if callable(budget_report):
                result["budget"] = budget_report()

            # Keep all run-level state and checkpoints aligned with the
            # canonical direct loop.  Older PAORR paths updated these fields;
            # leaving them stale makes a later successful turn look failed
            # and makes resume snapshots lose the actual evidence.
            self.runtime.last_result = dict(result)
            self.runtime.actions = list(result.get("actions") or [])
            self.runtime.plan = dict(
                getattr(self, "_active_execution_plan", {}) or {}
            )
            # Close the per-turn learning loop: collect tool-failure and
            # reflection signals into runtime.failures / runtime.learnings
            # and log the turn replay exactly once. Isolated so a learning
            # failure can never break the turn.
            collect = getattr(self, "_collect_turn_signals", None)
            if callable(collect):
                await collect(perceived, result, turn)
            # Arbitration point: a cancel/deadline request may arrive after
            # the provider/tool loop returns but before terminal persistence.
            # Re-check here so a late request cannot be overwritten by a
            # success event or a WorkItem `applied` transition.
            self._check_abort()
            self._check_deadline()
            self._last_run_failed = not bool(result.get("success", False))
            verification_state = result.get("verification")
            self._last_run_verified = bool(
                isinstance(verification_state, dict)
                and verification_state.get("success")
            )
            self._last_run_had_tool_execution = bool(result.get("calls_executed", 0))

            verification = result.get("verification")
            if isinstance(verification, dict):
                verification_ok = bool(verification.get("success"))
                await self._emit_runtime_event(
                    "verification.completed" if verification_ok else "verification.failed",
                    "Work verified" if verification_ok else "Verification found failures",
                    "completed" if verification_ok else "failed",
                    event_id=f"verification_{turn.turn_id}",
                    parent_id=f"run_{turn.turn_id}",
                    payload=verification,
                    visibility="internal",
                )

            response = str(result.get("response") or "")
            output = {"response": response}
            self._persist_turn_message("assistant", response, turn.turn_id, kind="final")
            if response:
                yield {"type": "content", "data": response}
            terminal_state = V5LoopState.COMPLETED if bool(result.get("success", False)) else V5LoopState.FAILED
            await self._transition_to(terminal_state)
            turn.end_time = datetime.now(timezone.utc)
            self.runtime.turn_history.append(turn)
            done = {
                **result,
                "success": bool(result.get("success", False)),
                "response": response,
                "output": output,
                "mental_state": {},
                "turn_id": turn.turn_id,
                "state": terminal_state.value,
            }
            event_name = "run.completed" if done["success"] else "run.failed"
            event_status = "completed" if done["success"] else "failed"
            finish_run_context(event_status, event_name, str(done.get("error") or ""))
            await self._emit_runtime_event(
                event_name,
                "Run completed" if done["success"] else "Run produced no verified tool success",
                event_status,
                event_id=f"run_{turn.turn_id}",
                task_id=task_id,
            )
            for event in self._yield_pending_events():
                yield event
            yield {"type": "done", "data": done}
            return
        except asyncio.TimeoutError:
            await self._transition_to(V5LoopState.TIMED_OUT)
            if turn.end_time is None:
                turn.end_time = datetime.now(timezone.utc)
            finish_run_context("timed_out", "run.timed_out", "deadline exceeded")
            await self._emit_runtime_event(
                "run.timed_out", "Run timed out", "failed", event_id=f"run_{turn.turn_id}",
                task_id=task_id,
                error="deadline exceeded",
            )
            for event in self._yield_pending_events():
                yield event
            yield {"type": "done", "data": {
                "success": False, "error": "deadline exceeded", "response": "",
                "output": output, "mental_state": mental_state, "turn_id": turn.turn_id,
                "state": "timed_out",
            }}

        except asyncio.CancelledError:
            await self._transition_to(V5LoopState.CANCELLED)
            if turn.end_time is None:
                turn.end_time = datetime.now(timezone.utc)
            finish_run_context("cancelled", "run.cancelled", "cancelled")
            await self._emit_runtime_event(
                "message.failed",
                "Assistant response cancelled",
                "cancelled",
                event_id=f"message_{turn.turn_id}",
                parent_id=f"run_{turn.turn_id}",
            )
            await self._emit_runtime_event(
                "run.cancelled",
                "Run cancelled",
                "cancelled",
                event_id=f"run_{turn.turn_id}",
                task_id=task_id,
            )
            for event in self._yield_pending_events():
                yield event
            yield {
                "type": "done",
                "data": {
                    "success": False,
                    "error": "cancelled",
                    "response": "",
                    "output": output,
                    "mental_state": mental_state,
                    "turn_id": turn.turn_id,
                    "state": V5LoopState.CANCELLED.value,
                },
            }

        except Exception as e:
            self.logger.error(f"V5 loop error: {e}", exc_info=True)
            await self._transition_to(V5LoopState.FAILED)
            if turn.end_time is None:
                turn.end_time = datetime.now(timezone.utc)
            finish_run_context("failed", "run.failed", str(e))
            await self._emit_runtime_event(
                "message.failed",
                "Assistant response failed",
                "failed",
                event_id=f"message_{turn.turn_id}",
                parent_id=f"run_{turn.turn_id}",
                error=str(e),
            )
            await self._emit_runtime_event(
                "run.failed",
                "Run failed",
                "failed",
                event_id=f"run_{turn.turn_id}",
                task_id=task_id,
                error=str(e),
            )
            for event in self._yield_pending_events():
                yield event
            yield {
                "type": "done",
                "data": {
                    "success": False,
                    "error": str(e),
                    "response": "",
                    "output": output,
                    "mental_state": mental_state,
                    "turn_id": turn.turn_id,
                    "state": V5LoopState.FAILED.value,
                },
            }

    def _yield_pending_events(self) -> List[Dict[str, Any]]:
        """Snapshot queued work events as status events for stream consumers."""
        pending, self._stream_events = self._stream_events, []
        return [{"type": "status", "data": event} for event in pending]

    def _clean_voice_input(self, text: str) -> str:
        """Clean voice mode input (V1 feature)."""
        if not text:
            return ""
        text = re.sub(r"\[VOICE_MODE\]:.*", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = text.replace("TASK_COMPLETE", "")
        return text.strip()

    # ─────────────────────────────────────────────────────────────────────────
    # STATE MACHINE
    # ─────────────────────────────────────────────────────────────────────────

    async def _transition_to(self, new_state: V5LoopState, reason: str = ""):
        """Transition to a new state and trigger callbacks.

        Mirrors every transition through the validated reliability state
        machine; a failed checkpoint save is surfaced (logged + event) but
        never crashes the run, so state changes remain observable even when
        persistence degrades.
        """
        if self.runtime.current_turn:
            self.runtime.current_turn.state = new_state

        try:
            self._mirror_transition(new_state, reason=reason or "loop phase")
        except Exception:
            pass

        try:
            self._log_stage(new_state.value)
        except Exception:
            pass

        try:
            # fsync'd JSON checkpoint I/O is blocking: run it in a worker
            # thread so a save can never stall the async state transition
            # (heartbeat tasks, SSE streaming, cancellation checks).
            await asyncio.to_thread(self._checkpoint_save, phase=new_state.value)
        except Exception as exc:
            self._checkpoint_failed("_transition_to.checkpoint_save", exc)

        try:
            self._progress_record("state_change", signature=f"state:{new_state.value}", status="ok")
        except Exception:
            pass

        if new_state in (
            V5LoopState.COMPLETED,
            V5LoopState.CANCELLED,
            V5LoopState.TIMED_OUT,
            V5LoopState.FAILED,
        ):
            try:
                evidence = None
                verification = getattr(self, "last_verification_payload", None) or (
                    getattr(self.runtime, "last_result", None) or {}
                ).get("verification")
                if isinstance(verification, dict):
                    evidence = [
                        str(item)
                        for item in (
                            verification.get("evidence")
                            or verification.get("summary")
                            or verification.get("result", "")
                        )
                        if str(item)
                    ]
                    evidence = evidence[:5] or None
                self._record_terminal_goal(new_state, evidence=evidence)
            except Exception:
                pass

        for callback in self._state_callbacks.get(new_state, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self.runtime)
                else:
                    callback(self.runtime)
            except Exception as e:
                self.logger.warning(f"State callback error for {new_state}: {e}")

    def register_state_callback(self, state: V5LoopState, callback: Callable):
        """Register a callback for a specific state transition."""
        if state not in self._state_callbacks:
            self._state_callbacks[state] = []
        self._state_callbacks[state].append(callback)

    def _generate_turn_id(self) -> str:
        """Generate a unique turn ID."""
        return f"turn_{uuid.uuid4().hex[:12]}"

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE IMPLEMENTATIONS
    # ─────────────────────────────────────────────────────────────────────────

    async def _meta_learning_optimize(self):
        """Apply meta-learning optimizations."""
        if self._meta_learning is not None:
            await self._meta_learning.optimize(self.runtime)

    async def _perceive_input(self, turn: V5TurnContext):
        """Process input through the perception layer with real enrichment.

        Returns a PerceivedInput (or a duck-typed equivalent) with intent,
        confidence, extracted entities and a context summary enriched with
        prefetched memory. A lightweight LLM call refines the intent; if the
        model is unavailable the regex-based intent from the perception layer
        is kept.
        """
        if self._perception is not None:
            try:
                perceived = await self._perception.process(turn)
            except Exception as e:
                self.logger.warning(f"Perception processing failed: {e}")
                perceived = None
            if perceived is None:
                perceived = _DuckPerceived(turn.user_input, turn.input_type)
        else:
            perceived = _DuckPerceived(turn.user_input, turn.input_type)

        # Enrich with prefetched memory context
        if self._memory_manager is not None and hasattr(self._memory_manager, "prefetch_all"):
            try:
                ctx = await self._memory_manager.prefetch_all(turn.user_input)
                turn.metadata["_memory_context"] = ctx
                perceived.context_summary = self._merge_memory_context(
                    perceived.context_summary, ctx
                )
            except Exception as e:
                self.logger.debug(f"Memory prefetch failed: {e}")

        if isinstance(getattr(perceived, "metadata", None), dict):
            turn.metadata.update(perceived.metadata)

        return perceived
