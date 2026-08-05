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
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
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
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class V5TurnContext:
    """Context for a single V5 turn."""
    turn_id: str
    session_id: str
    user_input: str
    input_type: str = "text"  # text, voice, vision, code
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.utcnow)
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
        self.session_id = session_id
        self.runtime = V5Runtime(session_id=session_id, root_dir=self.root_dir)
        self.logger = logging.getLogger("nexus.loop.v5")

        # V5 integration: Thread safety
        self._run_guard = threading.Lock()
        self._abort_flag = asyncio.Event()

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

    def save_memory(self) -> None:
        """Persist short-term conversation memory to disk."""
        try:
            path = os.path.join(self.root_dir, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            memory = getattr(self.runtime, "memory", [])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(memory, f, indent=2)
        except Exception as e:
            self.logger.warning("save_memory failed: %s", e)

    def load_memory(self, session_id: Optional[str] = None) -> None:
        """Load short-term memory from disk."""
        if session_id:
            self.session_id = session_id
            if self._memory_manager:
                try:
                    self._memory_manager.session_id = session_id
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
            self.logger.warning("load_memory: %s", e)
            self.runtime.memory = []

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
        except Exception:
            pass

    def _write_session_bus(self, _messages=None) -> None:
        """Write session to session_bus for CLI/GUI/Gateway sync."""
        try:
            path = os.path.join(self.root_dir, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.runtime.memory, f, indent=2)
        except Exception:
            pass

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
        import html, re
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
        results = []
        for call in tool_calls:
            try:
                result = await self._run_tool(call)
                results.append(result)
            except Exception as e:
                results.append(f"Error executing tool: {str(e)}")
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
        # The router must not turn greetings/social conversation into fake
        # execution plans, even if a provider over-predicts PLAN.
        if self._is_trivial_task(request):
            metadata.update({
                "planning_required": False,
                "planning_decision": "conversation:direct",
                "tool_route": "none",
                "hive_required": False,
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
                metadata.update({
                    "planning_required": False,
                    "planning_decision": "model:direct",
                    "tool_route": "none",
                    "hive_required": False,
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
                    "hive_required": False,
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
            tool = str(route.get("tool", "none")).lower()
            if tool not in {"none", "read", "write", "command", "search", "mixed"}:
                tool = "none"
            metadata.update({
                "planning_required": mode == "PLAN",
                "planning_decision": f"model:{mode.lower()}",
                "tool_route": tool,
                "hive_required": bool(route.get("hive", False)) and mode == "PLAN",
                "mcp_required": bool(route.get("mcp", False)),
                "model_route": str(route.get("model", "fast")).lower(),
                "permission_route": str(route.get("permission", "auto")).lower(),
                "sandbox_route": str(route.get("sandbox", "normal")).lower(),
                "voice_route": bool(route.get("voice", False)),
                "skills_route": bool(route.get("skills", True)),
                "plugins_route": bool(route.get("plugins", True)),
                "compact_route": bool(route.get("compact", False)),
                "evolution_route": bool(route.get("evolution", mode == "PLAN")),
                "forge_route": bool(route.get("forge", False)),
                "gap_finder_route": bool(route.get("gap_finder", mode == "PLAN")),
                "background_route": bool(route.get("background", mode == "PLAN")),
                "decision_source": "model",
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
                "hive_required": False,
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
        p = os.path.join(self.root_dir, "workspace", "TODO.md")
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

    async def aclose(self):
        """Drain background finalizers (V1 compat)."""
        import asyncio as _asyncio
        tasks = list(getattr(self, "_background_tasks", set()))
        self._background_tasks = set()
        for task in tasks:
            try:
                if not task.done():
                    await _asyncio.wait_for(task, timeout=5)
            except Exception:
                pass

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
            self._run_guard.release()

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
            ):
                if event.get("type") == "done" and isinstance(event.get("data"), dict):
                    done_result = event["data"]
                yield event
        finally:
            self._run_guard.release()

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
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Shared private turn pipeline used by run() and stream_run().

        Runs the full 7-phase V5 pipeline and yields status/content/done
        events. All exceptions are contained: the turn transitions to FAILED,
        failure events are emitted, and a done event with success=False is
        always yielded so consumers can never hang.
        """
        self._abort_flag.clear()
        self._stream_events.clear()

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
        )
        self.runtime.current_turn = turn
        self._current_turn_id = turn.turn_id

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
        try:
            from nexus.run_context import start_run_context

            run_context = start_run_context(
                root=self.root_dir,
                session_id=self.session_id,
                run_id=turn.turn_id,
                prompt=task_desc,
                provider=provider,
                model=model,
                max_tokens=max_tokens,
                voice_mode=voice_mode,
            )
        except Exception as exc:
            self.logger.debug("Could not persist run start: %s", exc)

        def finish_run_context(status: str, terminal_event: str, error: str = "") -> None:
            if run_context is None:
                return
            try:
                run_context.finish(status, terminal_event, error)
            except Exception as exc:
                self.logger.debug("Could not persist run finish: %s", exc)

        await self._emit_runtime_event(
            "run.started",
            "Run started",
            "running",
            event_id=f"run_{turn.turn_id}",
            payload={"input_type": input_type, "voice_mode": voice_mode},
        )

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
            perceived = await self._perceive_input(turn)
            conversational = self._is_trivial_task(task_desc)
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
                except Exception as exc:
                    self.logger.warning("Live plan generation failed; continuing with direct loop: %s", exc)
            if not conversational:
                await self._emit_runtime_event(
                    "planning.decided",
                    "Execution route selected",
                    "completed",
                    event_id=f"planning_decided_{turn.turn_id}",
                    parent_id=f"planning_{turn.turn_id}",
                    payload={
                        "planning_required": bool(route_metadata.get("planning_required")),
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
            context_summary = context_summary or ""
            if self._memory_manager is not None and hasattr(self._memory_manager, "prefetch_all"):
                try:
                    ctx = await self._memory_manager.prefetch_all(task_desc)
                    context_summary = "\n".join(
                        part for part in (
                            getattr(ctx, "session_history", ""),
                            getattr(ctx, "rag_context", ""),
                            getattr(ctx, "failure_vaccines", ""),
                            getattr(ctx, "knowledge_context", ""),
                            getattr(ctx, "episodic", ""),
                            getattr(ctx, "procedural", ""),
                        ) if part
                    )[:10000]
                except Exception as exc:
                    self.logger.debug("Direct-loop memory prefetch failed: %s", exc)
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
                task_desc, context_summary=context_summary,
                conversation_history=self._session_messages(),
                provider=provider, profile=profile, model=model,
                max_tokens=max_tokens,
            )
            for event in self._yield_pending_events():
                yield event
            if not isinstance(result, dict):
                result = {"success": False, "result": result}

            # Keep all run-level state and checkpoints aligned with the
            # canonical direct loop.  Older PAORR paths updated these fields;
            # leaving them stale makes a later successful turn look failed
            # and makes resume snapshots lose the actual evidence.
            self.runtime.last_result = dict(result)
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
            turn.end_time = datetime.utcnow()
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
            )
            for event in self._yield_pending_events():
                yield event
            yield {"type": "done", "data": done}
            return
        except asyncio.CancelledError:
            await self._transition_to(V5LoopState.FAILED)
            if turn.end_time is None:
                turn.end_time = datetime.utcnow()
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
                    "state": V5LoopState.FAILED.value,
                },
            }

        except Exception as e:
            self.logger.error(f"V5 loop error: {e}", exc_info=True)
            await self._transition_to(V5LoopState.FAILED)
            if turn.end_time is None:
                turn.end_time = datetime.utcnow()
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

    async def _transition_to(self, new_state: V5LoopState):
        """Transition to a new state and trigger callbacks."""
        if self.runtime.current_turn:
            self.runtime.current_turn.state = new_state

        try:
            self._log_stage(new_state.value)
        except Exception:
            pass

        try:
            self._checkpoint_save(phase=new_state.value)
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
                memory_parts = [
                    part for part in (
                        getattr(ctx, "session_history", ""),
                        getattr(ctx, "rag_context", ""),
                        getattr(ctx, "failure_vaccines", ""),
                        getattr(ctx, "knowledge_context", ""),
                    ) if part
                ]
                if memory_parts:
                    recall = "\n".join(memory_parts[:3])
                    perceived.context_summary = (
                        f"{perceived.context_summary}\n\n[RECALL]\n{recall}"
                    )
            except Exception as e:
                self.logger.debug(f"Memory prefetch failed: {e}")

        if isinstance(getattr(perceived, "metadata", None), dict):
            turn.metadata.update(perceived.metadata)

        return perceived
