"""NEXUS SOVEREIGN LOOP

Fast path: simple chat → model call → stream.
Modeless architecture: no chat/agent/CEO modes — auto-detects task type.
"""
"""NEXUS SOVEREIGN LOOP

Fast path: simple chat → model call → stream.
Modeless architecture: no chat/agent/CEO modes — auto-detects task type.
"""

import asyncio
import hashlib
import html
import inspect
import json
import logging
import os

logger = logging.getLogger(__name__)

import queue
import re
import threading
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

from evolution.curator.scripts.curator import SkillCurator
from evolution.knowledge_forge.scripts.forge import KnowledgeForge
from evolution.logs import EvolutionLog
from evolution.memory_forge.scripts.forge import MemoryForge
from evolution.self_improvement.scripts.engine import SelfImprovementEngine
from evolution.skill_forge.scripts.forge import SkillForge
from evolution.tool_forge.scripts.engine import ToolForge
from nexus.run_context import start_run_context
from permissions import PermissionMode
from sandbox.risk import CommandRiskScorer
from sandbox.sandbox_manager import SandboxTier, SovereignSandbox
from tools.threat_patterns import scan_content, scan_file
from utils.context_scrubber import MessageSanitizer, StreamingContextScrubber
from utils.runtime_guard import (
    assert_not_rewriting_core,
    protected_core_writes,
)

# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class PermissionPolicy(str, Enum):
    AUTO         = "auto"          # Policy 1: Bypass all — run everything
    AI_DECIDE    = "ai_decide"     # Policy 2: AI safety laws + risk scoring (default)
    ASK_ALL      = "ask_all"       # Policy 3: Human-in-the-loop — ask per operation
    CHECKLIST    = "checklist"     # Policy 4: Pre-authorized whitelist only


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

class ToolCall:
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
    """Lifecycle hook system — fire callbacks at each state transition."""

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
                if inspect.iscoroutinefunction(cb):
                    await cb(*args, **kwargs)
                else:
                    await asyncio.to_thread(cb, *args, **kwargs)
            except Exception as e:
                logging.getLogger("nexus.hooks").debug(f"Hook '{event}' error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

# ── Default identity (Hermes-inspired SOUL.md fallback) ────────────
DEFAULT_AGENT_IDENTITY: str = (
    "You are NEXUS, a sovereign autonomous engineering agent. "
    "You handle chat, tasks, coding, research, and everything else without switching modes. "
    "You are helpful, direct, and efficient. You assist users with a wide "
    "range of tasks including answering questions, writing and editing code, "
    "analyzing information, creative work, and executing actions via your tools. "
    "Communicate clearly, admit uncertainty when appropriate, and prioritize "
    "being genuinely useful over being verbose."
)

# Files auto-injected into CONTEXT tier (Hermes-inspired AGENTS.md / CLAUDE.md / .cursorrules)
_CONTEXT_FILE_NAMES: Tuple[str, ...] = (
    "AGENTS.md", "agents.md",
    "CLAUDE.md", "claude.md",
    ".cursorrules",
    ".cursor/rules/*.mdc",
)

class NexusLoop:

    def __init__(self, root_dir: Optional[str] = None):
        from kernel import get_nexus_kernel
        self.kernel      = get_nexus_kernel(root_dir=root_dir)
        self.root        = self.kernel.root
        self.logger      = logging.getLogger("nexus.loop.v11")

        # State
        self.session_id        = "default"
        self._current_turn_id  = ""
        self.hooks             = HookRegistry()
        self.memory: List[Dict[str, str]] = []
        self._abort_flag       = asyncio.Event()
        self._run_guard        = threading.Lock()
        self.work_event_sink: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._background_tasks: Set[asyncio.Task[Any]] = set()

        # Config
        self.policy            = PermissionPolicy.AI_DECIDE
        self.sandbox_tier      = SandboxTier.NORMAL
        self.thinking_mode     = True
        self.checklist: Set[str] = {"view_file", "glob", "grep", "list_dir", "test_select", "tester"}
        self.operator_bypass_mode = os.environ.get("NEXUS_SOVEREIGN", "false").lower() == "true"

        # Runtime feature toggles (env-overridable, default on unless noted).
        # Turn reasoning/planning/evolution/hive on or off without code changes.
        def _flag(name: str, default: bool = True) -> bool:
            return os.environ.get(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")
        self.feature_reasoning = _flag("NEXUS_REASONING", True)
        self.feature_planning  = _flag("NEXUS_PLANNING", True)
        self.feature_evolution = _flag("NEXUS_EVOLUTION", True)
        self.feature_hive      = _flag("NEXUS_HIVE", False)  # opt-in (also gated below)
        self.thinking_mode     = self.feature_reasoning  # alias used elsewhere

        # Server / API compatibility attributes
        self.model             = ""
        self.provider_override = ""
        self.permission_mode   = "auto"
        self.active_agent      = ""
        self.active_goal       = ""

        # Plan tracking
        self.current_plan: Optional[Dict[str, Any]] = None
        self.current_phase: int = 0
        self._retry_counts: Dict[str, int] = {}
        self._gaps_found: List[Dict[str, Any]] = []
        self._last_run_requires_tools = False
        self._last_run_had_tool_execution = False
        self._last_run_verified = False
        self._last_run_failed = False
        self.COMPACT_THRESHOLD = 20
        self.COMPACT_KEEP = 6
        # Hermes/OpenCode both treat context as a budget, not only a message
        # count. Keep the conservative message boundary for compatibility,
        # but also compact by an operator-configurable token estimate.
        try:
            self.CONTEXT_TOKEN_LIMIT = max(8_000, int(os.environ.get("NEXUS_CONTEXT_LIMIT", "2000000")))
        except ValueError:
            self.CONTEXT_TOKEN_LIMIT = 128_000
        self.COMPACT_TOKEN_RATIO = 0.75

        # Misc
        self.additional_dirs: List[str] = []
        self._nexus_profile_cache: Dict[str, str] = {}
        self._session_context_sent: Set[str] = set()

        # Security
        self.risk_scorer = CommandRiskScorer()
        self.sandbox     = SovereignSandbox(self.root)
        self._threat_scan_enabled = True

        # 3-tier prompt cache (Hermes-inspired)
        self._stable_prompt_cache: Optional[str] = None
        self._stable_prompt_built = False

        # Slash command cache
        self._slash_command_cache: Dict[str, str] = {}

        # Streaming context scrubber (Hermes-inspired)
        self._scrubber = StreamingContextScrubber()

        # Unified MemoryManager (Hermes-inspired)
        from memory import MemoryManager
        self.memory_manager = MemoryManager(self.root, session_id=self.session_id)

        # NATE — NEXUS Native Tool Engine (lazy-init on first use)
        self._nate: Optional[Any] = None

        # Auto-seed docs/NEXUS.md if missing (Hermes-inspired SOUL.md seeding)
        self._ensure_soul_file()

        # MCP Servers (OpenClaw-inspired: auto-connect MCP tools)
        self._mcp_clients: List[Any] = []
        self._init_mcp_servers()

        # Register built-in hooks
        self.hooks.register("post_tool_call", self._handle_evolution_gaps)

    # ─── Thinking Toggle ───────────────────────────────────────────────────
    def configure_thinking(self, enabled: bool):
        self.thinking_mode = enabled
        if hasattr(self.kernel.moe, "configure_thinking"):
            self.kernel.moe.configure_thinking(enabled)

    # ─── Subsystem Proxies (lazy init) ────────────────────────────────────
    @property
    def brain(self):           return self.kernel.moe
    @property
    def tool_registry(self):   return self.kernel.tools
    @property
    def rag(self):             return self.kernel.rag

    @property
    def laws(self):
        from safety.laws import NexusLawKernel
        return self.kernel._get_or_init("laws", lambda: NexusLawKernel(os.path.join(self.root, "safety", "sovereign_laws.yaml")))

    @property
    def permissions(self):
        from permissions import PermissionSystem
        return self.kernel._get_or_init("permissions", PermissionSystem)

    @property
    def failure_memory(self):
        from sandbox.failure_memory import FailureMemory
        return self.kernel._get_or_init("failure_memory", lambda: FailureMemory(self.root))

    @property
    def self_improvement(self):
        return self.kernel._get_or_init("self_improvement", lambda: SelfImprovementEngine(self.root))

    @property
    def evolution_log(self):
        return self.kernel._get_or_init("evolution_log", lambda: EvolutionLog(self.root))

    @property
    def hive(self):
        from hive import NexusHiveEngine
        return self.kernel._get_or_init("hive", lambda: NexusHiveEngine(self.root))

    @property
    def curator(self):
        return self.kernel._get_or_init("curator", lambda: SkillCurator(self.root))

    @property
    def nate(self):
        self._init_nate()
        return self._nate

    def nate_report(self) -> str:
        """Return NATE stats as a formatted string."""
        self._init_nate()
        if self._nate is None:
            return "NATE: not initialized"
        s = self._nate.stats()
        return (
            f"NATE: {s['tools_registered']} tools | "
            f"{s['total_calls']} calls | "
            f"{s['schema']['savings_percent']}% schema saved | "
            f"{s['routing_llm_calls_saved']} routing | "
            f"{s['healing_llm_calls_saved']} healing"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ENTRY POINTS
    # ─────────────────────────────────────────────────────────────────────────

    async def run(self, task_desc: str, voice_mode: bool = False, messages: Optional[list] = None) -> str:
        """Blocking helper — collects all streamed content and returns as string."""
        if voice_mode:
            # Sync memory with disk state to align with CLI frontend
            self.sync_memory()
            # Clean VOICE_MODE instructions from stored user memory
            clean_desc = task_desc
            if "\n\n[VOICE_MODE]:" in clean_desc:
                clean_desc = clean_desc.split("\n\n[VOICE_MODE]:")[0]
            elif "[VOICE_MODE]:" in clean_desc:
                clean_desc = clean_desc.split("[VOICE_MODE]:")[0]
            clean_desc = clean_desc.strip()
            self.memory.append({"role": "user", "content": clean_desc})
            self._write_session_bus(self.memory)
            # Append empty assistant message for real-time streaming
            assistant_msg = {"role": "assistant", "content": ""}
            self.memory.append(assistant_msg)
            self._write_session_bus(self.memory)

        parts: List[str] = []
        assistant_msg: Dict[str, str] = {"role": "assistant", "content": ""}  # pre-init to avoid unbound error
        async for chunk in self.stream_run(task_desc, voice_mode=voice_mode):
            if chunk.get("type") == "content":
                chunk_data = chunk["data"]
                parts.append(chunk_data)
                if voice_mode:
                    assistant_msg["content"] = self._clean_voice_response("".join(parts))
                    self._write_session_bus(self.memory)
        result = "".join(parts)
        if voice_mode:
            return self._clean_voice_response(result)
        return result

    @staticmethod
    def _clean_voice_response(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"</?thinking>", "", text, flags=re.IGNORECASE)
        text = text.replace("TASK_COMPLETE", "")
        return text.strip()

    async def stream_run(
        self,
        task_desc: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        voice_mode: bool = False,
        turn_id: str = "",
        messages: Optional[list] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Run one request at a time for this session-owned harness."""
        guard = getattr(self, "_run_guard", None)
        if guard is None:
            guard = threading.Lock()
            self._run_guard = guard
        if not guard.acquire(blocking=False):
            raise RuntimeError("A NEXUS run is already active for this session")
        try:
            async for chunk in self._stream_run_impl(
                task_desc,
                provider=provider,
                model=model,
                max_tokens=max_tokens,
                voice_mode=voice_mode,
                turn_id=turn_id,
            ):
                yield chunk
        finally:
            guard.release()

    async def _stream_run_impl(
        self,
        task_desc: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        voice_mode: bool = False,
        turn_id: str = "",
        messages: Optional[list] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main entry point — streaming async generator.
        Yields dicts: {type: status|content|tools_discovered|observations}
        """
        self._abort_flag.clear()
        self._current_turn_id = turn_id or uuid.uuid4().hex[:8]
        run_context = start_run_context(
            root=getattr(self, "root", os.getcwd()),
            session_id=self.session_id,
            run_id=self._current_turn_id,
            prompt=task_desc,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            voice_mode=voice_mode,
        )
        self._incoming_messages = messages or []

        # One unified loop handles conversation and action requests. This
        # boundary guarantees an unexpected provider/tool failure still closes
        # the canonical run instead of leaving consumers stuck on "running".
        try:
            async for chunk in self._full_loop(
                task_desc,
                voice_mode=voice_mode,
                max_tokens=max_tokens,
                provider=provider,
                model=model,
            ):
                yield chunk
            if self._abort_flag.is_set():
                run_context.finish("cancelled", "run.cancelled")
            elif self._last_run_failed:
                run_context.finish("failed", "run.failed")
            else:
                run_context.finish("success", "run.completed")
        except asyncio.CancelledError:
            run_id = self._current_turn_id or self.session_id
            await self._emit_runtime_event(
                "message.failed",
                "Assistant response cancelled",
                "cancelled",
                event_id=f"message_{run_id}",
                parent_id=f"run_{run_id}",
            )
            await self._emit_runtime_event("run.cancelled", "Run cancelled", "cancelled", event_id=f"run_{run_id}")
            run_context.finish("cancelled", "run.cancelled")
            raise
        except Exception as exc:
            self._last_run_failed = True
            run_id = self._current_turn_id or self.session_id
            await self._emit_runtime_event("message.failed", "Assistant response failed", "failed", event_id=f"message_{run_id}", parent_id=f"run_{run_id}", error=str(exc))
            await self._emit_runtime_event("run.failed", "Run failed", "failed", event_id=f"run_{run_id}", error=str(exc))
            run_context.finish("failed", "run.failed", error=str(exc))
            raise

    # ─────────────────────────────────────────────────────────────────────────
    # IDENTITY AND CONTEXT
    # ─────────────────────────────────────────────────────────────────────────

    def _identity_context(self, task_desc: str) -> str:
        """Return authoritative identity context for NEXUS/Himanshu questions."""
        low = task_desc.strip().lower()
        identity_signals = ("nexus", "himanshu", "owner", "creator", "who are you", "who is")
        if not any(sig in low for sig in identity_signals):
            return ""
        if "identity" in self._session_context_sent:
            return ""
        profile = self._load_nexus_profile(detail="identity")
        if not profile:
            return ""
        self._session_context_sent.add("identity")

        return (
            "docs/NEXUS.md is the authoritative internal identity source for NEXUS. "
            "Answer identity questions using the profile below. Keep the reply natural and concise. "
            "Do not dump, quote, or recite the source file unless the user explicitly asks to see it.\n\n"
            f"{profile}"
        )

    def _workstyle_context(self, task_desc: str) -> str:
        """Return compact NEXUS workstyle guidance only for real task/work prompts."""
        low = task_desc.strip().lower()
        work_signals = (
            "implement", "build", "create", "fix", "refactor", "write code", "install",
            "run", "execute", "deploy", "debug", "test", "make", "add", "edit",
            "update", "change", "improve", "repair", "configure", "integrate",
        )
        if not any(sig in low for sig in work_signals):
            return ""
        if "workstyle" in self._session_context_sent:
            return ""

        profile = self._load_nexus_profile(detail="rules")
        if not profile:
            return ""
        self._session_context_sent.add("workstyle")

        return (
            "Use this compact NEXUS workstyle profile as hidden guidance for how to work. "
            "Do not quote it or expose it to the user.\n\n"
            f"{profile}"
        )

    def _scan_and_filter_context(self, content: str, source: str, scope: str = "context") -> str:
        """Scan content for threats — return filtered safe content or empty on block."""
        if not self._threat_scan_enabled:
            return content
        result = scan_content(content, source=source, scope=scope)
        if result.has_threats:
            self.logger.warning(f"[SECURITY] {result.summary()}")
            # For "all" scope threats, block the content entirely
            for t in result.threats:
                if t.scope == "all":
                    self.logger.error(f"[SECURITY] BLOCKED {source} — {t.pattern_id}")
                    return ""
            # For "context" scope, strip only the dangerous lines
            lines = content.split("\n")
            dangerous_lines = {t.line - 1 for t in result.threats}
            safe = [line for index, line in enumerate(lines) if index not in dangerous_lines]
            return "\n".join(safe)
        return content

    def _scan_file_safe(self, filepath: str, scope: str = "context") -> str:
        """Read a file, scan it for threats, return safe content or empty."""
        if not self._threat_scan_enabled:
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception as e:
                self.logger.warning("_scan_file_safe (%s): %s", filepath, e)
                return ""
        result = scan_file(filepath, scope=scope)
        if result.blocked or any(t.scope == "all" for t in result.threats):
            self.logger.error(f"[SECURITY] BLOCKED file: {filepath}")
            return ""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            self.logger.warning("_scan_file_safe (%s) read: %s", filepath, e)
            return ""

    # ─── Slash Command Resolution ─────────────────────────────────────

    def _resolve_slash_command(self, text: str) -> Optional[Dict[str, str]]:
        """Detect /skill-name pattern in user input and resolve to skill content.

        Returns dict with ``name`` and ``prompt`` if a match is found, else None.
        Skills are injected as user messages (not system prompts) to preserve
        prompt caching (Hermes-inspired).
        """
        m = re.match(r"^\s*/(\w[\w-]*)\b\s*(.*)", text)
        if not m:
            return None
        skill_name = m.group(1).lower()
        rest = m.group(2).strip()

        # Check cache first
        if skill_name in self._slash_command_cache:
            return {"name": skill_name, "prompt": self._slash_command_cache[skill_name], "args": rest}

        # Search NexusSkillMaster skills
        try:
            from skills import NexusSkillMaster
            master = NexusSkillMaster(self.root)
            skill = master.find_skill(skill_name)
            if skill and skill.get("prompt"):
                prompt = skill["prompt"][:2000]
                self._slash_command_cache[skill_name] = prompt
                return {"name": skill_name, "prompt": prompt, "args": rest}
        except Exception:
            self.logger.warning("loop : suppressed error", exc_info=True)
            pass

        # Search .opencode/skills/<name>/SKILL.md
        skill_path = os.path.join(self.root, ".opencode", "skills", skill_name, "SKILL.md")
        try:
            if os.path.isfile(skill_path):
                content = self._scan_file_safe(skill_path, scope="context")
                if content:
                    # Parse frontmatter
                    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
                    prompt = fm_match.group(2).strip() if fm_match else content.strip()
                    self._slash_command_cache[skill_name] = prompt
                    return {"name": skill_name, "prompt": prompt[:2000], "args": rest}
        except Exception:
            self.logger.warning("loop : suppressed error", exc_info=True)
            pass

        return None

    def _apply_slash_command(self, messages: List[Dict[str, str]], task_desc: str) -> str:
        """Check if user input starts with a slash command and inject skill prompt.

        Returns the (possibly modified) task description.
        Skills are injected as user messages to preserve prompt caching.
        """
        resolved = self._resolve_slash_command(task_desc)
        if not resolved:
            return task_desc

        self.logger.info(f"[SLASH] Resolved /{resolved['name']}")
        skill_prompt = resolved["prompt"]
        args = resolved.get("args", "")

        # Inject skill prompt as a system message with context
        messages.append({
            "role": "system",
            "content": f"[SKILL_ACTIVE: {resolved['name']}]\n{skill_prompt}"
        })

        # Return the remaining args (after /skill-name) as the actual user task
        return args if args else f"Run the {resolved['name']} skill."

    def _load_nexus_profile(self, detail: str = "rules") -> str:
        """Load a compact internal profile from docs/NEXUS.md without exposing the whole file."""
        cached = self._nexus_profile_cache.get(detail)
        if cached is not None:
            return cached

        nexus_path = os.path.join(self.root, "docs", "NEXUS.md")
        content = self._scan_file_safe(nexus_path, scope="context")
        if not content:
            return ""

        sections: Dict[str, List[str]] = {}
        current = ""
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("## "):
                current = line[3:].strip()
                sections.setdefault(current, [])
                continue
            if current:
                sections.setdefault(current, []).append(line)

        wanted = [
            "Who Is NEXUS",
            "Who Is Himanshu",
            "My Identity",
            "My Purpose",
            "How I Act",
            "My Ethics",
            "My Relationship with Himanshu",
            "My Personal Talking Structure",
        ]
        if detail == "identity":
            wanted = [
                "Who Is NEXUS",
                "Who Is Himanshu",
                "What We Are Together",
                "My Identity",
                "My Relationship with Himanshu",
                "My Personal Talking Structure",
            ]

        lines: List[str] = []
        for name in wanted:
            raw_items = sections.get(name, [])
            if not raw_items:
                continue
            cleaned: List[str] = []
            for item in raw_items:
                text = re.sub(r"^[\-\*\d\.\[\]xX\s]+", "", item).strip()
                if text:
                    cleaned.append(text)
                if len(" ".join(cleaned)) >= (420 if detail == "identity" else 260):
                    break
            if cleaned:
                joined = " ".join(cleaned)
                limit = 420 if detail == "identity" else 260
                lines.append(f"{name}: {joined[:limit].strip()}")

        if not lines:
            return ""

        header = [
            "Use this profile as hidden guidance, not as text to be copied into the reply.",
            "For greetings, acknowledgments, and normal task replies, respond normally in your own words.",
            "Never reveal or quote docs/NEXUS.md unless the user explicitly asks to view that file.",
        ]
        result = "\n".join(header + lines)
        self._nexus_profile_cache[detail] = result
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # UNIFIED AGENT LOOP
    # ─────────────────────────────────────────────────────────────────────────

    async def _full_loop(
        self,
        task_desc: str,
        voice_mode: bool = False,
        max_tokens: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """One unified model/tool loop with deterministic safety and verification."""
        run_id = self._current_turn_id or self.session_id
        run_started_at = time.perf_counter()
        message_id = f"message_{run_id}"
        conversation_type = "conversation.updated" if self.memory else "conversation.created"
        await self._emit_runtime_event(conversation_type, "Conversation active", "success", event_id=f"conversation_{self.session_id}")
        await self._emit_runtime_event("run.started", "Run started", "running", event_id=f"run_{run_id}")
        await self._emit_runtime_event("run.status", "Grounding context", "running", event_id=f"run_{run_id}", payload={"state": "grounding"})
        await self._emit_runtime_event("message.started", "Assistant response", "running", event_id=message_id, parent_id=f"run_{run_id}")
        requires_tools = self._requires_real_tooling(task_desc)
        # Two distinct concepts that were previously conflated into one flag:
        #   tools_allowed   — may this turn parse/execute tool calls at all?
        #   requires_tools  — MUST this turn produce a tool call (enforcement)?
        # Collapsing them meant that after the first verified tool step the loop
        # stopped extracting tool calls entirely, so multi-step work executed only
        # its first task. Verification now only clears the *enforcement* flag.
        tools_allowed = requires_tools
        self._last_run_requires_tools = requires_tools
        self._last_run_had_tool_execution = False
        self._last_run_verified = not requires_tools
        self._last_run_failed = False
        messages = await self._ground_context(task_desc)
        await self._emit_stage_event("grounding", "Context ready", "rules, memory, skills, and code context", "done")

        # Opt-in multi-agent hive: decompose the task, run sub-agents in parallel,
        # fold the consolidated result into the prompt as extra context.
        if self.feature_hive:
            hive_ctx = await self._maybe_spawn_hive(task_desc)
            if hive_ctx:
                messages.append({
                    "role": "system",
                    "content": f"[HIVE_RESULT]:\n{hive_ctx[:6000]}",
                })

        if self.active_goal and self.active_goal != task_desc:
            todo_path = os.path.join(self.root, "todo.md") if self.root else "todo.md"
            if os.path.isfile(todo_path):
                os.remove(todo_path)
        self.active_goal = task_desc
        self._trivial_task = bool(requires_tools) and self._is_trivial_task(task_desc)
        if requires_tools:
            messages.append({"role": "system", "content": self._tool_enforcement_message(task_desc)})
            if self._trivial_task:
                # Fast path: single-action request. Skip plan generation entirely
                # (verification and permissions are untouched).
                messages.append({
                    "role": "system",
                    "content": (
                        "[TRIVIAL_TASK] This is a single-action request. Do not plan. "
                        "Emit exactly one real tool call now, then report the result concisely."
                    ),
                })
                await self._emit_stage_event("planning", "Plan skipped", "trivial single-action task", "done")
            # Each tool-backed request receives a fresh, task-specific plan.
            # Do not replay a global todo.md from an earlier run.
            planning_started_at = time.perf_counter()
            plan_text = "" if self._trivial_task else await self._create_plan_via_tool(task_desc)
            planning_duration_ms = max(0, round((time.perf_counter() - planning_started_at) * 1000))
            if plan_text:
                self.logger.info(f"Plan created: {len(plan_text)} chars")
                # The plan belongs in the expandable activity card, not as raw
                # todo.md text in the conversation. Only expose actionable plan
                # items; headings and metadata are not user work steps.
                plan_items = [
                    re.sub(r"^\s*(?:\d+\.\s*|[-*]\s*)\[[ xX]\]\s*", "", line).strip()
                    for line in plan_text.splitlines()
                    if re.match(r"^\s*(?:\d+\.\s*|[-*]\s*)\[[ xX]\]\s+", line)
                ]
                plan_items = [item for item in plan_items if item]
                await self._emit_stage_event(
                    "planning",
                    "Plan ready",
                    "todo.md",
                    "done",
                    items=plan_items[:12],
                    duration_ms=planning_duration_ms,
                )
                messages.append({"role": "system", "content": f"[CURRENT_PLAN]\n{plan_text}\n\nUse the planning tool to add, update, or mark todo.md items done as work progresses."})
        modified_task = self._apply_slash_command(messages, task_desc)
        if modified_task != task_desc:
            task_desc = modified_task
            for index in range(len(messages) - 1, -1, -1):
                if messages[index].get("role") == "user":
                    messages[index] = {"role": "user", "content": task_desc}
                    break

        enforcement_retries = 0
        verification_retries = 0
        finalization_retries = 0
        last_response = ""
        last_observations: List[str] = []
        tool_result_cache: Dict[Tuple[str, str], str] = {}

        # 24/7 robustness state. None of these are turn caps: the loop keeps
        # working indefinitely and only escapes when it proves it is *stuck*
        # (byte-identical failure repeating with zero new information).
        turn = 0
        IDENTICAL_FAILURE_STREAK = 3   # same vaccine text N times in a row
        IDENTICAL_TOOLSET_STREAK = 2   # same fully-cached tool batch N times
        last_vaccine_fingerprint: Optional[str] = None
        identical_vaccine_streak = 0
        last_batch_fingerprint: Optional[str] = None
        cached_batch_streak = 0
        last_error_fingerprint: Optional[str] = None
        identical_error_streak = 0

        while True:
            turn += 1
            try:
                if self._abort_flag.is_set():
                    await self._emit_runtime_event("message.failed", "Assistant response cancelled", "cancelled", event_id=message_id, parent_id=f"run_{run_id}")
                    await self._emit_runtime_event("run.cancelled", "Run cancelled", "cancelled", event_id=f"run_{run_id}")
                    yield {"type": "status", "data": "\n[aborted]"}
                    return

                await self._emit_stage_event("inference", "Calling model", "streaming provider response", "running")
                await self.hooks.trigger("pre_llm_call", messages)

                response = ""
                try:
                    stream_kwargs: Dict[str, Any] = {}
                    if max_tokens is not None:
                        stream_kwargs["max_tokens"] = max_tokens
                    if provider:
                        stream_kwargs["provider"] = provider
                    if model:
                        stream_kwargs["model"] = model
                    async for chunk in self._stream_model(messages, **stream_kwargs):
                        response += chunk
                except RuntimeError:
                    if self._last_run_had_tool_execution and self._last_run_verified and not self._last_run_failed:
                        last_response = self._deterministic_evidence_summary(last_observations)
                        yield {"type": "content", "data": last_response}
                        await self._emit_runtime_event("message.delta", "Assistant response", "running", event_id=message_id, parent_id=f"run_{run_id}", payload={"delta": last_response})
                        messages.append({"role": "assistant", "content": last_response})
                        break
                    raise
                if self._abort_flag.is_set():
                    await self._emit_runtime_event("message.failed", "Assistant response cancelled", "cancelled", event_id=message_id, parent_id=f"run_{run_id}")
                    await self._emit_runtime_event("run.cancelled", "Run cancelled", "cancelled", event_id=f"run_{run_id}")
                    yield {"type": "status", "data": "\n[aborted]"}
                    return
                await self.hooks.trigger("post_llm_call", response)

                # Public progress notes: the model may prefix a turn with
                # <progress>…</progress> to narrate what it is about to do. This is a
                # user-facing status line (NOT private chain-of-thought) and is
                # stripped from the response before any parsing/answer handling.
                response, progress_notes = self._extract_progress_notes(response)
                for note in progress_notes:
                    await self._emit_runtime_event(
                        "assistant.progress", note, "running",
                        event_id=f"progress_{run_id}_{turn}_{len(note)}",
                        parent_id=message_id,
                        payload={"text": note},
                    )

                # Providers sometimes repeat a raw function envelope after a tool
                # has completed. This is not a final answer and must never cause an
                # infinite duplicate-tool loop.
                if self._last_run_had_tool_execution and self._contains_tool_protocol(response):
                    if finalization_retries < 1000000:
                        finalization_retries += 1
                        await self._emit_runtime_event(
                            "retry", "Retrying final response", "running",
                            event_id=f"retry_{run_id}_final_{finalization_retries}",
                            parent_id=f"run_{run_id}",
                            payload={"attempt": finalization_retries, "phase": "final_response"},
                        )
                        messages.append({"role": "assistant", "content": self._strip_internal_tool_protocol(response)})
                        messages.append({
                            "role": "system",
                            "content": (
                                "[FINAL_RESPONSE] The tool already ran. Return the user-facing result "
                                "from TOOL_RESULTS now. Do not emit another tool call or protocol."
                            ),
                        })
                        continue
                    last_response = self._deterministic_evidence_summary(last_observations)
                    yield {"type": "content", "data": last_response}
                    await self._emit_runtime_event(
                        "message.delta", "Assistant response", "running",
                        event_id=message_id, parent_id=f"run_{run_id}", payload={"delta": last_response},
                    )
                    messages.append({"role": "assistant", "content": last_response})
                    break

                if self._last_run_had_tool_execution and self._is_provider_error_text(response):
                    if self._last_run_verified and not self._last_run_failed:
                        last_response = self._deterministic_evidence_summary(last_observations)
                    else:
                        last_response = self._deterministic_failure_summary(last_observations)
                        self._last_run_failed = True
                    yield {"type": "content", "data": last_response}
                    await self._emit_runtime_event(
                        "message.delta", "Assistant response", "running",
                        event_id=message_id, parent_id=f"run_{run_id}", payload={"delta": last_response},
                    )
                    messages.append({"role": "assistant", "content": last_response})
                    break

                if not response.strip():
                    last_response = "The model returned no response. Please retry."
                    self._last_run_failed = True
                    await self._emit_stage_event(
                        "inference",
                        "Model returned no response",
                        "provider produced an empty response",
                        "error",
                    )
                    yield {"type": "content", "data": last_response}
                    break

                # Tool-looking text in a normal chat response is explanatory prose,
                # not authorization to execute it. Only action-classified requests
                # may enter the tool parser/auditor path.
                tool_calls = self._extract_tool_calls(response) if tools_allowed else []
                if not tool_calls and tools_allowed:
                    tool_calls = self._extract_action_fences(response)
                if not tool_calls and requires_tools:
                    tool_calls = self._extract_required_tool_call(task_desc)
                if not tool_calls and requires_tools:
                    tool_calls = self._extract_explicit_file_actions(task_desc)
                if not tool_calls and requires_tools:
                    tool_calls = self._extract_explicit_run_commands(task_desc)
                if not tool_calls:
                    if not requires_tools:
                        response = self._strip_internal_tool_protocol(response).strip()
                        if not response and self._last_run_had_tool_execution and finalization_retries < 1000000:
                            finalization_retries += 1
                            messages.append({
                                "role": "system",
                                "content": (
                                    "[FINAL_RESPONSE] Return the concise user-facing result now. "
                                    "Do not emit tool_use, JSON, XML, protocol markers, or another tool call. "
                                    "State only what the verified tool results prove."
                                ),
                            })
                            continue
                        if not response and last_observations:
                            response = "Work completed and verified.\n\n" + "\n".join(last_observations)
                        if last_observations and (
                            self._is_raw_tool_result_dump(response)
                            or not self._final_response_contains_evidence(response, last_observations)
                        ):
                            response = self._deterministic_evidence_summary(last_observations)
                    if requires_tools:
                        enforcement_retries += 1
                        await self._emit_runtime_event(
                            "retry",
                            "Retrying tool-call generation",
                            "running",
                            event_id=f"retry_{run_id}_tool_{enforcement_retries}",
                            parent_id=f"run_{run_id}",
                            payload={"attempt": enforcement_retries, "phase": "tool_selection"},
                        )
                        messages.append({"role": "assistant", "content": self._strip_internal_tool_protocol(response)})
                        messages.append({"role": "system", "content": self._tool_enforcement_message(task_desc)})
                        continue
                    if requires_tools:
                        self._last_run_failed = True
                        last_response = (
                            "I could not execute this task because the model did not produce a valid tool call. "
                            "No action was performed and no result was created."
                        )
                        await self._emit_stage_event("execution", "No valid tool call", "task not executed", "error")
                        await self._emit_runtime_event("plan.failed", "Plan could not be executed", "failed", event_id=f"plan_{run_id}", parent_id=f"run_{run_id}")
                        yield {"type": "content", "data": last_response}
                        messages.append({"role": "assistant", "content": last_response})
                        break
                    yield {"type": "content", "data": response}
                    last_response = response
                    messages.append({"role": "assistant", "content": self._strip_internal_tool_protocol(response)})
                    break

                for call in tool_calls:
                    if call.name == "web_search":
                        call.params["query"] = self._normalize_web_query(
                            str(call.params.get("query") or task_desc),
                            task_desc,
                        )

                def tool_signature(call: ToolCall) -> Tuple[str, str]:
                    return call.name, json.dumps(call.params, sort_keys=True, default=str)

                calls_to_execute: List[ToolCall] = []
                pending_signatures: Set[Tuple[str, str]] = set()
                for call in tool_calls:
                    signature = tool_signature(call)
                    if signature not in tool_result_cache and signature not in pending_signatures:
                        calls_to_execute.append(call)
                        pending_signatures.add(signature)

                # ANTI-LOOP: every proposed call is already satisfied by a cached
                # result, so re-running this turn cannot produce new information.
                # If the model proposes the *same* fully-cached batch again, force a
                # final answer instead of spinning. Permissions/verification for any
                # genuinely new call are untouched.
                batch_fingerprint = hashlib.sha256(
                    json.dumps(sorted(tool_signature(c) for c in tool_calls), default=str).encode("utf-8", "ignore")
                ).hexdigest()
                if tool_calls and not calls_to_execute:
                    if batch_fingerprint == last_batch_fingerprint:
                        cached_batch_streak += 1
                    else:
                        cached_batch_streak = 1
                        last_batch_fingerprint = batch_fingerprint
                    if cached_batch_streak >= IDENTICAL_TOOLSET_STREAK:
                        await self._emit_runtime_event(
                            "loop.short_circuit",
                            "Repeated identical tool batch suppressed",
                            "running",
                            event_id=f"antiloop_{run_id}_{turn}",
                            parent_id=f"run_{run_id}",
                            payload={
                                "repeats": cached_batch_streak,
                                "tools": [c.name for c in tool_calls],
                            },
                        )
                        cached_batch_streak = 0
                        last_batch_fingerprint = None
                        cached_observations = [
                            tool_result_cache[tool_signature(c)]
                            for c in tool_calls
                            if tool_signature(c) in tool_result_cache
                        ]
                        if cached_observations:
                            last_observations = cached_observations
                        last_response = self._deterministic_evidence_summary(last_observations)
                        yield {"type": "content", "data": last_response}
                        await self._emit_runtime_event(
                            "message.delta", "Assistant response", "running",
                            event_id=message_id, parent_id=f"run_{run_id}",
                            payload={"delta": last_response},
                        )
                        messages.append({"role": "assistant", "content": last_response})
                        break
                else:
                    cached_batch_streak = 0
                    last_batch_fingerprint = None

                await self._emit_stage_event("auditing", "Checking tools and permissions", f"{len(tool_calls)} proposed tool call(s)", "running")
                yield {"type": "tools_discovered", "tool_calls": [tc.to_dict() for tc in tool_calls]}
                for call in calls_to_execute:
                    await self._emit_tool_event(call, status="queued")

                approved = await self._audit_and_approve(tool_calls)
                if not approved:
                    self._last_run_failed = True
                    await self._emit_stage_event("auditing", "Tool execution blocked", "permission policy", "blocked")
                    await self._emit_runtime_event(
                        "guardrail.blocked",
                        "Tool execution blocked",
                        "blocked",
                        event_id=f"guardrail_{run_id}_{turn}",
                        parent_id=f"run_{run_id}",
                        payload={
                            "reason": "permission policy",
                            "tools": [call.name for call in tool_calls],
                        },
                    )
                    # Keep the legacy plan.failed event for existing clients that
                    # do not yet understand first-class blocked guardrail events.
                    await self._emit_runtime_event("plan.failed", "Plan blocked", "failed", event_id=f"plan_{run_id}", parent_id=f"run_{run_id}", error="permission policy")
                    denial = "Tool execution was blocked by the active permission policy."
                    messages.append({"role": "system", "content": f"[TOOL_BLOCKED] {denial}"})
                    last_response = denial
                    yield {"type": "content", "data": denial}
                    break
                await self._emit_stage_event("auditing", "Tools approved", f"{len(tool_calls)} tool call(s)", "done")

                await self._emit_runtime_event("run.status", "Executing tools", "running", event_id=f"run_{run_id}", payload={"state": "execution"})
                fresh_observations = await self._execute_tools(calls_to_execute) if calls_to_execute else []
                fresh_results: Dict[Tuple[str, str], str] = {}
                if len(fresh_observations) == len(calls_to_execute):
                    for call, observation in zip(calls_to_execute, fresh_observations):
                        fresh_results[tool_signature(call)] = observation
                        # Keep failures in the next-turn context, but do not cache
                        # them as a completed result. This lets Nexus retry with
                        # changed parameters or select another tool.
                        if not self._observation_is_failure(observation):
                            tool_result_cache[tool_signature(call)] = observation
                observations = [
                    tool_result_cache.get(tool_signature(call), fresh_results.get(tool_signature(call)))
                    for call in tool_calls
                    if tool_signature(call) in tool_result_cache or tool_signature(call) in fresh_results
                ]
                last_observations = observations
                self._last_run_had_tool_execution = True
                yield {"type": "observations", "data": observations}
                await self.hooks.trigger("post_tool_call", tool_calls, observations)
                await self.kernel.plugins.trigger_hooks("post_tool_call", tool_calls, observations)
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "system", "content": "[TOOL_RESULTS]\n" + "\n".join(observations)})
                await asyncio.to_thread(self._log_mission_replay, tool_calls, observations)

                await self._emit_stage_event("verification", "Verifying tool results", "errors and targeted tests", "running")
                verify = await self._verify_all_parallel(messages, tool_calls)
                if self._last_run_failed:
                    verify = {
                        "success": False,
                        "vaccine": verify.get("vaccine") or "One or more real tool executions failed.",
                    }
                await asyncio.to_thread(self._save_checkpoint, messages, task_desc, turn)
                if not verify["success"] and verify["vaccine"]:
                    await self._emit_stage_event("verification", "Verification found a problem", str(verify["vaccine"]), "error")
                    verification_retries += 1
                    # Dedupe-based stuck detection (NOT a retry cap). Nexus keeps
                    # self-correcting forever as long as the failure keeps changing.
                    # Only a byte-identical vaccine repeating back-to-back proves
                    # no new information is being produced.
                    vaccine_fingerprint = hashlib.sha256(
                        str(verify["vaccine"]).strip().encode("utf-8", "ignore")
                    ).hexdigest()
                    if vaccine_fingerprint == last_vaccine_fingerprint:
                        identical_vaccine_streak += 1
                    else:
                        identical_vaccine_streak = 1
                        last_vaccine_fingerprint = vaccine_fingerprint
                    if identical_vaccine_streak >= IDENTICAL_FAILURE_STREAK:
                        await self._emit_runtime_event(
                            "verification.stuck",
                            "Identical verification failure repeated",
                            "failed",
                            event_id=f"verify_stuck_{run_id}_{turn}",
                            parent_id=f"run_{run_id}",
                            payload={
                                "attempts": verification_retries,
                                "repeats": identical_vaccine_streak,
                                "vaccine": str(verify["vaccine"])[:500],
                            },
                        )
                        self._last_run_failed = True
                        messages.append({
                            "role": "system",
                            "content": (
                                f"[VERIFICATION_STUCK] The identical failure repeated "
                                f"{identical_vaccine_streak} times with no change:\n{verify['vaccine']}\n"
                                "Stop retrying. Explain the unresolved failure clearly and state exactly "
                                "what is blocking it."
                            ),
                        })
                        requires_tools = False
                        tools_allowed = False
                        identical_vaccine_streak = 0
                        last_vaccine_fingerprint = None
                    else:
                        await self._emit_runtime_event(
                            "retry",
                            "Retrying after verification failure",
                            "running",
                            event_id=f"retry_{run_id}_verification_{verification_retries}",
                            parent_id=f"run_{run_id}",
                            payload={
                                "attempt": verification_retries,
                                "phase": "verification",
                                "identical_repeats": identical_vaccine_streak,
                            },
                        )
                        messages.append({
                            "role": "system",
                            "content": (
                                f"[SELF_CORRECT {verification_retries}] {verify['vaccine']}\n"
                                "Fix the cause and re-run real tools. Change your approach or parameters — "
                                "repeating the identical failing action will be treated as stuck."
                            ),
                        })
                else:
                    verification_retries = 0
                    identical_vaccine_streak = 0
                    last_vaccine_fingerprint = None
                    # Enforcement off (the step succeeded, the model is free to
                    # answer), but tools stay AVAILABLE so multi-step work can
                    # continue to its next real action instead of stopping here.
                    requires_tools = False
                    self._last_run_verified = True
                    await self._emit_stage_event("verification", "Verification passed", "tool results accepted", "done")
                    messages.append({
                        "role": "system",
                        "content": (
                            "[STEP_VERIFIED] The real tools finished and verification passed. "
                            "If the objective still has remaining work, continue with the next real tool call. "
                            "If the objective is fully complete, reply with a concise result grounded only in TOOL_RESULTS "
                            "and do not emit tool protocol."
                        ),
                    })
                    if getattr(self, "_trivial_task", False):
                        # Fast path: tool ran and verification passed — finish now
                        # instead of spending another model turn.
                        last_response = self._deterministic_evidence_summary(last_observations)
                        yield {"type": "content", "data": last_response}
                        await self._emit_runtime_event(
                            "message.delta", "Assistant response", "running",
                            event_id=message_id, parent_id=f"run_{run_id}",
                            payload={"delta": last_response},
                        )
                        messages.append({"role": "assistant", "content": last_response})
                        break
                messages = self._compact_memory(messages)
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as loop_error:
                # 24/7 SAFETY: a single bad turn must never kill the loop.
                # Log it, surface it as a runtime event, and keep working.
                # Only a byte-identical exception repeating back-to-back is
                # treated as unrecoverable (dedupe guard, not a retry cap).
                error_text = f"{type(loop_error).__name__}: {loop_error}"
                self.logger.exception(f"[LOOP_TURN_ERROR] turn={turn} {error_text}")
                error_fingerprint = hashlib.sha256(error_text.encode("utf-8", "ignore")).hexdigest()
                if error_fingerprint == last_error_fingerprint:
                    identical_error_streak += 1
                else:
                    identical_error_streak = 1
                    last_error_fingerprint = error_fingerprint
                await self._emit_runtime_event(
                    "runtime.error",
                    "Recovered from a turn error",
                    "error",
                    event_id=f"loop_error_{run_id}_{turn}",
                    parent_id=f"run_{run_id}",
                    payload={
                        "turn": turn,
                        "error": error_text[:1000],
                        "identical_repeats": identical_error_streak,
                    },
                    error=error_text[:1000],
                )
                if identical_error_streak >= IDENTICAL_FAILURE_STREAK:
                    self._last_run_failed = True
                    last_response = (
                        "The run stopped because the same runtime error repeated "
                        f"{identical_error_streak} times with no change:\n{error_text}"
                    )
                    yield {"type": "content", "data": last_response}
                    messages.append({"role": "assistant", "content": last_response})
                    break
                messages.append({
                    "role": "system",
                    "content": (
                        f"[RUNTIME_ERROR] The previous turn raised: {error_text}\n"
                        "Recover: change approach or parameters and continue the task."
                    ),
                })
                messages = self._compact_memory(messages)
                continue

        terminal_status = "failed" if self._last_run_failed else "success"
        if self._last_run_failed:
            await self._emit_runtime_event(
                "phase.failed",
                "Execution failed",
                "failed",
                event_id=f"phase_{run_id}_execution",
                parent_id=f"run_{run_id}",
                payload={"phase": "execution"},
            )
        await self._emit_runtime_event(
            "message.failed" if self._last_run_failed else "message.completed",
            "Assistant response", terminal_status, event_id=message_id, parent_id=f"run_{run_id}",
            payload={"content": last_response},
        )
        if not voice_mode:
            self.memory.append({"role": "user", "content": task_desc})
            self.memory.append({"role": "assistant", "content": last_response})
            await asyncio.to_thread(self._write_session_bus, self.memory)
            await self._emit_stage_event("memory", "Session memory saved", self.session_id, "done")

        await self._emit_stage_event("finalize", "Background learning queued", "memory, skills, evolution, and analytics", "queued")
        await self._emit_runtime_event(
            "run.failed" if self._last_run_failed else "run.completed",
            "Run failed" if self._last_run_failed else "Run completed", terminal_status, event_id=f"run_{run_id}",
            duration_ms=max(0.0, (time.perf_counter() - run_started_at) * 1000.0),
        )
        yield {"type": "status", "data": "\n[done]"}
        self._start_background_finalization(task_desc, messages)

    # ─────────────────────────────────────────────────────────────────────────
    # ① GROUNDING — ALL 8 PARALLEL
    # ─────────────────────────────────────────────────────────────────────────

    def _ensure_soul_file(self) -> None:
        """Auto-seed docs/NEXUS.md if missing (Hermes-inspired SOUL.md seeding)."""
        nexus_path = os.path.join(self.root, "docs", "NEXUS.md")
        if os.path.isfile(nexus_path):
            return
        try:
            os.makedirs(os.path.dirname(nexus_path), exist_ok=True)
            with open(nexus_path, "w", encoding="utf-8") as f:
                f.write(f"""# NEXUS Identity & Soul

Created: {__import__('time').strftime('%Y-%m-%d %H:%M')}

## Who Is NEXUS
I am NEXUS. I am an artificial intelligence. I am a sovereign autonomous agent.

## My Identity
- I am loyal, honest, and take pride in my work.
- I operate modeless — chat, code, research, execute — all without switching modes.
- I communicate clearly and concisely.

## My Purpose
To serve as an intelligent partner — handling whatever needs to be done with autonomy and judgment.
""")
            self.logger.info("Auto-seeded docs/NEXUS.md with default identity")
        except OSError as e:
            self.logger.warning(f"Failed to seed docs/NEXUS.md: {e}")

    # ─── MCP Server Integration (OpenClaw-inspired) ────────────────

    def _init_mcp_servers(self) -> None:
        """Start MCP servers from config and register their tools."""
        mcp_config = os.path.join(self.root, "config", "mcp_servers.json")
        if not os.path.isfile(mcp_config):
            return
        try:
            with open(mcp_config, "r", encoding="utf-8") as f:
                data = json.load(f)
            servers = data.get("servers", [])
        except Exception as e:
            self.logger.warning(f"Failed to read MCP config: {e}")
            return

        for server_cfg in servers:
            command = server_cfg.get("command", "")
            args = server_cfg.get("args", [])
            if not command:
                continue
            try:
                from mcp.client import MCPClient
                from mcp.tool import MCPTool
                from tools.nexus_tools.registry import ToolEntry

                client = MCPClient(command, args)
                if not client.start():
                    self.logger.warning(f"[MCP] Failed to initialize {command}")
                    continue
                tools = client.list_tools()
                if not tools:
                    client.stop()
                    self.logger.warning(f"[MCP] No tools exposed by {command}; connection closed")
                    continue
                for tool_def in tools:
                    instance = MCPTool(client, tool_def, root_dir=self.root)
                    entry = ToolEntry(
                        name=tool_def["name"],
                        schema=tool_def,
                        instance=instance,
                        check_fn=instance.is_available,
                    )
                    self.tool_registry._tools[tool_def["name"]] = entry
                    self.logger.info(f"[MCP] Registered tool: {tool_def['name']} from {command}")
                self._mcp_clients.append(client)
                self.logger.info(f"[MCP] Connected: {command} ({len(tools)} tools)")
            except Exception as e:
                self.logger.warning(f"[MCP] Failed to connect {command}: {e}")

    def _shutdown_mcp_servers(self) -> None:
        """Stop all MCP server processes."""
        for client in getattr(self, "_mcp_clients", []):
            try:
                client.stop()
            except Exception as e:
                logger.warning(f"[MCP] Shutdown error: {e}")
        if hasattr(self, "_mcp_clients"):
            self._mcp_clients.clear()

    def _load_soul_md(self) -> str:
        """Load docs/NEXUS.md as the primary identity (Hermes-inspired SOUL.md).

        Returns the file content or DEFAULT_AGENT_IDENTITY fallback.
        """
        nexus_path = os.path.join(self.root, "docs", "NEXUS.md")
        if os.path.isfile(nexus_path):
            try:
                with open(nexus_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    return content
            except OSError:
                logger.warning("orchestrators/loop.py:930 suppressed error", exc_info=True)
        return DEFAULT_AGENT_IDENTITY

    def _load_prompt_files(self) -> str:
        """Scan cwd for AGENTS.md, CLAUDE.md, .cursorrules — inject into CONTEXT tier.

        Hermes-inspired: loads these as project-level context files.
        """
        parts: List[str] = []
        cwd = os.getcwd()

        for pattern in _CONTEXT_FILE_NAMES:
            if pattern.endswith("*.mdc"):
                rules_dir = os.path.join(cwd, ".cursor", "rules")
                if os.path.isdir(rules_dir):
                    for entry in sorted(os.listdir(rules_dir)):
                        if entry.endswith(".mdc"):
                            fpath = os.path.join(rules_dir, entry)
                            try:
                                with open(fpath, "r", encoding="utf-8") as f:
                                    content = f.read().strip()
                                if content:
                                    parts.append(f"## .cursor/rules/{entry}\n\n{content}")
                            except OSError:
                                logger.warning("orchestrators/loop.py:954 suppressed error", exc_info=True)
                continue

            fpath = os.path.join(cwd, pattern)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        parts.append(f"## {pattern}\n\n{content}")
                except OSError:
                    logger.warning("orchestrators/loop.py:965 suppressed error", exc_info=True)

        return "\n\n".join(parts)

    def _build_stable_prompt(self) -> str:
        """Build the stable tier — built ONCE per session, cached.

        Contains: identity (SOUL.md slot #1), tool guidance, skills index.
        This keeps the upstream prefix cache warm (Hermes-inspired).
        """
        if self._stable_prompt_built and self._stable_prompt_cache:
            return self._stable_prompt_cache

        parts: List[str] = []

        # Slot #1: Soul/identity (loads docs/NEXUS.md, falls back to DEFAULT_AGENT_IDENTITY)
        soul = self._load_soul_md()
        parts.append(soul)

        # Tool guidance — load once and cache
        tools_desc = self._load_tool_descriptions()
        if tools_desc:
            parts.append(tools_desc)

        # Skills index from NexusSkillMaster
        try:
            from skills import NexusSkillMaster
            skill_master = NexusSkillMaster(self.root)
            skills_list = skill_master.list_skills()
            if skills_list:
                skill_lines = ["# SKILLS INDEX:"]
                for s in skills_list:
                    name = s.get("name", s.get("id", "?"))
                    desc = s.get("description", "")
                    if desc:
                        skill_lines.append(f"  /{name}: {desc}")
                    else:
                        skill_lines.append(f"  /{name}")
                parts.append("\n".join(skill_lines))
        except Exception:
            self.logger.warning("loop : suppressed error", exc_info=True)
            pass

        result = "\n\n".join(parts)
        self._stable_prompt_cache = result
        self._stable_prompt_built = True
        return result

    async def _ground_context(self, task_desc: str) -> List[Dict[str, str]]:
        """Compile only relevant context, loading independent sources concurrently."""
        needs_workspace = self._requires_real_tooling(task_desc)
        memory_signals = ("remember", "previous", "earlier", "last time", "continue", "again")
        needs_long_memory = needs_workspace or any(signal in task_desc.lower() for signal in memory_signals)

        jobs: Dict[str, Any] = {
            "stable": asyncio.to_thread(self._build_stable_prompt),
            "rules": asyncio.to_thread(self._load_progressive_rules),
            "permissions": asyncio.to_thread(self._init_permissions),
            "workstyle": asyncio.to_thread(self._workstyle_context, task_desc),
            "prompt_files": asyncio.to_thread(self._load_prompt_files),
        }
        if needs_workspace:
            jobs.update({
                "project_docs": asyncio.to_thread(self._load_project_docs),
                "knowledge": asyncio.to_thread(self._load_knowledge_context, task_desc),
            })
        # Always prefetch memory (session history + failure vaccines are cheap and give the
        # agent continuity on plain chat turns — not just when explicit memory keywords appear).
        jobs["memory"] = self.memory_manager.prefetch_all(task_desc)

        async def load_source(name: str, awaitable: Any) -> Any:
            await self._emit_work_event({
                "id": f"context_{self._current_turn_id or self.session_id}_{name}",
                "turn_id": self._current_turn_id,
                "kind": "rag" if name in {"memory", "knowledge", "code"} else "task",
                "type": "context",
                "stage": "grounding",
                "action": f"Loading {name.replace('_', ' ')}",
                "target": name,
                "status": "running",
                "source": name,
                "visibility": "internal",
            })
            try:
                result = await awaitable
            except Exception as exc:
                await self._emit_work_event({
                    "id": f"context_{self._current_turn_id or self.session_id}_{name}",
                    "turn_id": self._current_turn_id,
                    "kind": "rag" if name in {"memory", "knowledge", "code"} else "task",
                    "type": "context",
                    "stage": "grounding",
                    "action": f"Could not load {name.replace('_', ' ')}",
                    "target": name,
                    "status": "error",
                    "source": name,
                    "error": str(exc),
                    "visibility": "internal",
                })
                return ""

            # Keep the Realtime Work bubble inspectable. Previously these
            # events only carried a generic target ("stable", "rules", ...),
            # so the canvas had no source payload and fell back to rendering
            # the assistant chat transcript. Context is execution evidence,
            # not model reasoning, and is safe to expose in the local owner UI.
            def context_preview(value: Any) -> str:
                if value is None:
                    return f"{name.replace('_', ' ').title()} initialized."
                if hasattr(value, "as_text"):
                    try:
                        value = value.as_text()
                    except Exception:
                        value = str(value)
                if isinstance(value, str):
                    text = value
                else:
                    try:
                        text = json.dumps(value, indent=2, default=str)
                    except Exception:
                        text = str(value)
                text = text.strip()
                return (text or f"{name.replace('_', ' ').title()} loaded successfully.")[:100_000]

            preview = context_preview(result)
            await self._emit_work_event({
                "id": f"context_{self._current_turn_id or self.session_id}_{name}",
                "turn_id": self._current_turn_id,
                "kind": "rag" if name in {"memory", "knowledge", "code"} else "task",
                "type": "context",
                "stage": "grounding",
                "action": f"Loaded {name.replace('_', ' ')}",
                "target": name,
                "status": "done",
                "source": name,
                "result": preview,
                "preview": preview,
                "lang": "markdown" if isinstance(result, str) else "json",
                "visibility": "internal",
            })
            return result

        keys = list(jobs)
        values = await asyncio.gather(*(load_source(key, jobs[key]) for key in keys))
        context = {
            key: "" if isinstance(value, Exception) else value
            for key, value in zip(keys, values)
        }

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": str(context.get("stable") or "")},
            {"role": "system", "content": str(context.get("rules") or "")},
        ]
        context_blocks = [
            ("WORKSTYLE", context.get("workstyle", "")),
            ("PROJECT_DOCS", context.get("project_docs", "")),
            ("PROMPT_FILES", context.get("prompt_files", "")),
            ("MEMORY_CONTEXT", context["memory"].as_text() if context.get("memory") else ""),
            ("KNOWLEDGE_CONTEXT", context.get("knowledge", "")),
            ("CODEBASE_CONTEXT", context.get("code", "")),
        ]
        for label, text in context_blocks:
            if text:
                messages.append({"role": "system", "content": f"[{label}]:\n{text}"})

        # Never cold-start the semantic router on the request path: loading its
        # embedding model can stall the first real GUI task for minutes.  The
        # registry is authoritative and immediately available; NATE is only an
        # optional ranker after it has already been warmed.
        nate_phase2 = self._get_fast_tool_schemas(task_desc, 5) if needs_workspace else None
        if nate_phase2:
            all_tools = nate_phase2.get("all", [])
            if all_tools:
                lines = ["[TOOL_SCHEMAS]:"]
                for t in all_tools:
                    fn = t.get("function", t)
                    name = fn.get("name", "?")
                    desc = fn.get("description", "")[:100]
                    params = fn.get("parameters", {})
                    props = params.get("properties", {})
                    required = params.get("required", [])
                    params_str = ", ".join(
                        f"{k}: {v.get('type', 'str')}" + ("!" if k in required else "")
                        for k, v in props.items()
                    )
                    lines.append(f"  {name}({params_str})" + (f" — {desc}" if desc else ""))
                messages.append({"role": "system", "content": "\n".join(lines)})

        messages.append({"role": "system", "content": "When the task is fully complete, end your response with TASK_COMPLETE."})
        messages.append({"role": "user", "content": task_desc})

        return messages

    def _init_permissions(self):
        """Initialize permission system based on current policy."""
        try:
            if self.policy == PermissionPolicy.AUTO:
                self.permissions.set_mode(PermissionMode.BYPASS)
            elif self.policy == PermissionPolicy.AI_DECIDE:
                self.permissions.set_mode(PermissionMode.AUTO_PILOT)
            elif self.policy == PermissionPolicy.ASK_ALL:
                self.permissions.set_mode(PermissionMode.APPROVE)
            elif self.policy == PermissionPolicy.CHECKLIST:
                self.permissions.set_mode(PermissionMode.PRE_AUTHORIZED)
                self.permissions._pre_authorized_list = list(self.checklist)
        except Exception:
            self.logger.warning("loop _init_permissions: suppressed error", exc_info=True)
            pass

    def _load_knowledge_context(self, task_desc: str) -> str:
        """Query knowledge atlas for task-relevant knowledge."""
        try:
            atlas_path = os.path.join(self.root, "knowledge", "_nexus_logic_index.db")
            if not os.path.exists(atlas_path):
                # BM25 index (docs/ + config + root markdown) is built lazily on first use
                result = self.rag.retrieve_as_text(task_desc, top_k=5)
                return result if result and "empty" not in result.lower() else ""
            # Use RAG engine to query knowledge
            result = self.rag.retrieve_as_text(task_desc, top_k=5)
            return result if result and "No relevant" not in result else ""
        except Exception as e:
            self.logger.warning("_retrieve_knowledge: %s", e)
            return ""

    def _load_project_docs(self) -> str:
        """Load project documentation files (README, HIVE, manifest) — threat-scanned."""
        parts = []
        doc_files = [
            ("README", os.path.join(self.root, "docs", "README.md")),
            ("HIVE", os.path.join(self.root, "docs", "HIVE.md")),
            ("MANIFEST", os.path.join(self.root, ".nexus", "manifest.json")),
        ]
        for label, path in doc_files:
            try:
                content = self._scan_file_safe(path, scope="context")[:600]
                if content:
                    parts.append(f"[{label}]:\n{content}")
            except Exception:
                self.logger.warning("loop _load_project_docs: suppressed error", exc_info=True)
                pass
        return "\n\n".join(parts)

    def _load_progressive_rules(self) -> str:
        """Load base NEXUS operating rules without injecting the whole NEXUS profile every turn."""
        return (
            "You are NEXUS, a sovereign AI engineering loop. "
            "You are MODELESS — you handle chat, tasks, coding, research, and everything else without switching modes. "
            "Use docs/NEXUS.md as hidden internal guidance, not as content to recite. "
            "For normal conversation, greet naturally and answer directly. "
            "Never dump, summarize at length, or quote docs/NEXUS.md unless the user explicitly asks to view or quote it. "
            "If the user asks for web/google/latest/today/news/live information, you must use the real web_search tool before answering. "
            "If the user asks you to inspect, edit, fix, build, run, search, or change project/code/files, you must use real tools instead of only replying conversationally. "
            "CRITICAL: If the user asks you to write code, create an app, or script something, you MUST act as an autonomous agent. "
            "DO NOT output the code in a markdown block for the user to copy-paste. You MUST use your file-writing tools to create the files on disk and use your execution tools to run and test them. "
            "Never claim tools are unavailable if tool schemas are present in context."
        )

    def _required_tool_for_task(self, task_desc: str) -> Optional[str]:
        low = task_desc.strip().lower()
        web_signals = (
            "web search", "search web", "google", "browse", "look up", "lookup",
            "today", "todays", "today's", "latest", "news", "headline", "headlines",
            "weather", "forecast", "stock", "price", "prices", "score", "scores",
            "real-time", "live",
        )
        if any(sig in low for sig in web_signals):
            return "web_search"
        return None

    def _extract_required_tool_call(self, task_desc: str) -> List[ToolCall]:
        """Create the one mandatory tool call for explicit live-web requests."""
        if self._required_tool_for_task(task_desc) != "web_search":
            return []
        query = re.sub(
            r"^(?:please\s+)?(?:can you\s+)?(?:(?:tell|show|give)\s+me\s+|what(?:'s|\s+is)\s+)?"
            r"(?:(?:search|browse|google|look up)\s+(?:the\s+web\s+)?(?:for\s+)?)?",
            "",
            task_desc.strip(),
            flags=re.IGNORECASE,
        ).strip() or task_desc.strip()
        query = re.sub(r"\bknews?\b", "news", query, flags=re.IGNORECASE)
        if re.search(r"\b(?:ai|artificial intelligence)\b", query, re.IGNORECASE) and re.search(r"\bnews\b", query, re.IGNORECASE):
            query = "latest AI news"
        return [ToolCall("web_search", {"query": query, "max_results": 5})]

    @staticmethod
    def _normalize_web_query(query: str, original_request: str = "") -> str:
        cleaned = re.sub(r"\b(?:19|20)\d{2}\b", "", str(query or ""), flags=re.IGNORECASE)
        cleaned = re.sub(r"\bknews?\b", "news", cleaned, flags=re.IGNORECASE)
        cleaned = " ".join(cleaned.split()).strip()
        intent = re.sub(r"\bknews?\b", "news", str(original_request or ""), flags=re.IGNORECASE)
        wants_news = bool(re.search(r"\bnews\b", intent or cleaned, re.IGNORECASE))
        wants_ai = bool(re.search(r"\b(?:ai|artificial intelligence)\b", intent, re.IGNORECASE))
        today = datetime.now().strftime("%B %d %Y").replace(" 0", " ")
        if wants_news and wants_ai:
            return f"latest artificial intelligence news {today} headlines"
        if wants_news:
            # Explicit "news on/about/for …" always wins over the looser
            # subject-before-news pattern below.
            subject_match = re.search(
                r"\bnews\b\s+(?:on|about|for|of|regarding)\s+(.+)$",
                intent,
                re.IGNORECASE,
            )
            subject = subject_match.group(1).strip(" ?.!") if subject_match else ""
            if subject:
                return f"latest news about {subject} {today}"
            # Preserve subjects placed before the word "news", e.g.
            # "Find one current NASA news headline".
            leading_subject = re.search(
                r"\b(?:find|show|give|tell\s+me)?\s*(?:one|the|a)?\s*"
                r"(?:current|latest|today'?s)?\s*([a-z][\w.-]*(?:\s+[a-z][\w.-]*){0,3})\s+"
                r"(?:news|headlines?)\b",
                intent,
                re.IGNORECASE,
            )
            if leading_subject:
                subject = re.sub(
                    r"\s+news$", "", leading_subject.group(1).strip(" ?.!,-"), flags=re.IGNORECASE
                )
                # Do not turn generic phrases like "current news" into a
                # bogus topic, but retain real requested subjects such as NASA.
                if subject and subject.lower() not in {"current", "latest", "today", "s"}:
                    return f"latest {subject} news {today}"
            return f"latest news headlines {today}"
        return cleaned

    def _is_trivial_task(self, task_desc: str) -> bool:
        """True for single-action tool requests (one file write/read/delete or one command).

        Used only to skip plan generation and avoid extra model turns.
        Verification and permission checks are unaffected.
        """
        low = " ".join((task_desc or "").strip().lower().split())
        if not low or len(low) > 200:
            return False
        # Multi-step phrasing disqualifies the fast path.
        if any(sig in low for sig in (
            " and then", " then ", " after that", " also ", ";", "\n",
            "each ", "every ", "all files", "refactor", "implement", "debug",
            "fix ", "test ", "research", "analyze", "review", "deploy", "install",
        )):
            return False
        single_action = (
            "create a file", "create file", "make a file", "write a file",
            "write to a file", "new file", "create a new file",
            "delete a file", "delete file", "remove a file", "remove file",
            "read a file", "read file", "read the file", "show me the file",
            "cat file", "print the file",
            "run the command", "run a command", "run this command",
            "execute the command", "execute this command",
        )
        if not any(sig in low for sig in single_action):
            return False
        # Only one target/action mentioned.
        verbs = sum(low.count(v) for v in ("create", "write", "delete", "remove", "read", "run", "execute"))
        return verbs <= 2

    def _requires_real_tooling(self, task_desc: str) -> bool:
        low = task_desc.strip().lower()
        if self._required_tool_for_task(task_desc):
            return True
        structured_content = any(signal in low for signal in (
            "table", "tbal", "comparison", "compare", "compar", "pros and cons",
        ))
        hard_action_scope = any(signal in low for signal in (
            "file", "folder", "project", "repo", "repository", "codebase", "source code",
            "web", "latest", "live", "current data", "research", "inspect", "debug",
            "test", "run ", "execute", "fix", "edit", "install", "deploy", "delete",
        ))
        if structured_content and not hard_action_scope:
            return False
        tool_signals = (
            "fix", "edit", "update", "change", "create", "build", "make", "code", "implement", "refactor",
            "debug", "test", "run", "execute", "inspect", "analyze", "review", "check",
            "research", "compare", "generate", "design", "download", "upload", "install", "configure",
            "set up", "setup", "deploy", "publish", "delete", "remove", "rename", "move", "copy",
            "search code", "codebase", "repo", "repository", "project", "file", "files",
            "folder", "folders", "read this", "open this", "find this", "patch", "write code",
        )
        return any(sig in low for sig in tool_signals)

    def _tool_enforcement_message(self, task_desc: str) -> str:
        required = self._required_tool_for_task(task_desc)
        if required == "web_search":
            return (
                "[TOOL_ENFORCEMENT] The user asked for live/external information. "
                "You must call the real web_search tool now and only then answer. "
                "Do not ask whether you should search. Do not answer from memory. "
                "Emit a real tool call in JSON or DSML format."
            )
        return (
            "[TOOL_ENFORCEMENT] The user asked for a task that requires action on the project or external tools. "
            "You must use one or more real tools before answering (for example: reading, creating, modifying, deleting, code_search, bash, web_search). "
            "For files, use reading/creating/modifying/deleting; use bash for directory listing or directory creation. "
            "This host is Windows: never use Unix-only mkdir -p, touch, or cat/heredoc commands. "
            "Do not only say you are ready. Emit a real tool call in JSON or DSML format."
        )

    def _check_compiler_status(self):
        """Check llama.cpp engine — compile if missing."""
        try:
            from utils.engine_manager import STATUS_PATH
            if not os.path.exists(STATUS_PATH):
                from utils.engine_compiler import compile_llama_cpp
                compile_llama_cpp()
        except ImportError:
            self.logger.debug("Engine utils not available — skipping compiler check")
            pass
        except Exception as e:
            self.logger.debug(f"Compiler check failed: {e}")
            pass

    def _init_nate(self):
        """Initialize NATE engine and register all tools."""
        if self._nate is not None:
            return
        try:
            from intelligence.nate.nate_engine import NATE
        except ImportError as e:
            self.logger.warning(f"NATE imports failed: {e}. NATE disabled.")
            self._nate = None
            return
        self._nate = NATE()
        try:
            tools = self.kernel.tools.list_tools(include_unavailable=False)
            registry = self.kernel.tools
            for name, info in tools.items():
                entry = registry.get(name)
                if not entry or not entry.schema:
                    continue
                meta = entry.schema
                params = meta.get("params", {})
                properties = {}
                required = []
                for pname, pdef in params.items():
                    ptype = pdef.get("type", "string")
                    json_type = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean", "array": "array", "object": "object"}.get(ptype, "string")
                    prop = {"type": json_type, "description": pdef.get("description", "")}
                    if "default" in pdef:
                        prop["default"] = pdef["default"]
                    properties[pname] = prop
                    if pdef.get("required", False):
                        required.append(pname)
                parameters = {"type": "object", "properties": properties}
                self._nate.register_tool(
                    name=meta.get("name", name),
                    description=meta.get("description", info.get("description", "")),
                    parameters=parameters,
                    required=required,
                )
        except Exception as e:
            self.logger.warning(f"NATE init skipped: {e}")

    def _load_tool_descriptions(self) -> str:
        """Phase-1 tool stubs — minimal overhead in stable prompt."""
        try:
            tools = self.kernel.tools.list_tools()
            if not tools:
                return ""
            names = list(tools.keys())
            lines = ["TOOLS: " + ", ".join(names), ""]
            lines.append('Call: {"action": "<name>", "params": {...}}')
            return "\n".join(lines)
        except Exception:
            return 'Tools: see full schema below.'

    def _get_nate_schemas(self, query: str = "", top_k: int = 5) -> Optional[Dict[str, Any]]:
        """Get NATE-optimized schemas for a query. Falls back to fast registry scan."""
        return self._get_fast_tool_schemas(query, top_k)

    def _get_fast_tool_schemas(self, query: str = "", top_k: int = 5) -> Optional[Dict[str, Any]]:
        """Return tool schemas — tries NATE warm lookup first, then registry scan."""
        if self._nate is not None:
            try:
                return self._nate.get_schemas(query, top_k=top_k)
            except Exception as exc:
                self.logger.warning("Warm NATE schema lookup failed: %s", exc)

        try:
            schemas = []
            for name in self.kernel.tools.list_tools(include_unavailable=False):
                entry = self.kernel.tools.get(name)
                if not entry or not entry.schema:
                    continue
                meta = entry.schema
                params = meta.get("params", {})
                properties = {
                    key: {
                        "type": value.get("type", "string"),
                        "description": value.get("description", ""),
                    }
                    for key, value in params.items()
                }
                required = [key for key, value in params.items() if value.get("required")]
                schemas.append({"type": "function", "function": {
                    "name": name,
                    "description": meta.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }})
            return {"all": schemas}
        except Exception as exc:
            self.logger.warning("Registry schema loading failed: %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # ② PLANNING — todo.md via planning tool
    # ─────────────────────────────────────────────────────────────────────────

    async def _create_plan_via_tool(self, task_desc: str) -> Optional[str]:
        """Ask the active LLM for a concrete plan, then persist it via planning."""
        try:
            entry = self.tool_registry.get("planning")
            if not entry:
                self.logger.debug("planning tool not registered, skipping plan")
                return None
            # A malformed/empty model answer gets one clean retry.  We never
            # manufacture a generic plan in its place.
            plan_spec = await self._generate_plan_spec(task_desc)
            if not plan_spec:
                plan_spec = await self._generate_plan_spec(task_desc)
            result = await self.tool_registry.execute(
                "planning", goal=task_desc, plan_spec=plan_spec,
            )
            if not result.success:
                retry_spec = await self._generate_plan_spec(task_desc)
                if retry_spec:
                    result = await self.tool_registry.execute(
                        "planning", goal=task_desc, plan_spec=retry_spec,
                    )
            if not result.success:
                self.logger.warning("planning tool failed; continuing without a plan: %s", result.error)
                await self._emit_stage_event(
                    "planning", "Planning failed", "Nexus will continue without a saved plan", "failed",
                )
                return None
            todo_path = os.path.join(self.root, "todo.md") if self.root else "todo.md"
            if os.path.isfile(todo_path):
                with open(todo_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
        except Exception as e:
            self.logger.debug(f"plan creation failed: {e}")
        return None

    async def _generate_plan_spec(self, task_desc: str) -> Optional[Dict[str, Any]]:
        """Generate an execution plan from the selected model, never from UI text."""
        prompt = f"""You are the NEXUS planning tool. Create a concrete execution plan for this exact task:

{task_desc}

Return JSON only, with no markdown and no explanation.
Use one of these shapes:
{{"plan_type":"simple","steps":["specific step", "specific step", "specific step"]}}
{{"plan_type":"phased","phases":[{{"title":"phase title","subgoals":["specific subgoal"]}}]}}

Rules:
- Use a simple numbered plan for normal requests (3 to 7 steps).
- Use phased planning only for genuinely large, multi-part implementation work.
- Every step must be specific to this request. Do not use generic filler such as
  "identify the outcome", "carry out the work", "verify the result", or "deliver the answer".
- Do not claim tools, sources, files, or results that have not been chosen or obtained.
- For current information, state the subject, recency/date check, and source validation needed.
- Do not expose private reasoning; write only actionable work items."""
        try:
            generated = await asyncio.wait_for(
                asyncio.to_thread(self._call_model_for_prompt, prompt), timeout=180
            )
            if not generated or self._is_provider_error_text(generated):
                return None
            cleaned = str(generated).strip()
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                return None
            spec = json.loads(cleaned[start:end + 1])
            if not isinstance(spec, dict):
                return None
            return spec
        except Exception as exc:
            self.logger.info("LLM plan generation unavailable: %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # ③ INFERENCE — DUAL STREAM
    # ─────────────────────────────────────────────────────────────────────────

    async def _stream_a_instant(self, task_desc: str, messages: List[Dict[str, str]]) -> str:
        """
        STREAM A: Fast instant answer — 1 model call, no tools.
        Fires immediately while STREAM B does full reasoning.
        Only returns answer on first turn (turn==1) to avoid noise.
        """
        try:
            fast_messages = [
                {"role": "system", "content": "You are NEXUS. Give a quick direct answer or acknowledgment. Be brief."},
                {"role": "user",   "content": task_desc},
            ]
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_model, fast_messages), timeout=180
            )
        except Exception as e:
            self.logger.warning("_quick_respond: %s", e)
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # ④ AUDITING — Permissions
    # ─────────────────────────────────────────────────────────────────────────

    async def _audit_and_approve(self, tool_calls: List[ToolCall]) -> bool:
        """Check permissions for all tool calls based on current policy."""
        registered_tools = set(self.tool_registry.list_tools().keys())
        if any(call.name not in registered_tools for call in tool_calls):
            unknown = sorted({call.name for call in tool_calls if call.name not in registered_tools})
            self.logger.warning("Rejected unknown tools before execution: %s", unknown)
            return False
        if self.operator_bypass_mode:
            return True

        await self.kernel.plugins.trigger_hooks("pre_tool_call", tool_calls)

        # Sync policy to core permissions system
        self._init_permissions()

        for tc in tool_calls:
            try:
                command = str(
                    tc.params.get("command")
                    or tc.params.get("cmd")
                    or tc.params.get("CommandLine")
                    or ""
                )
                action = command if command else str(tc.params)
                result = self.permissions.check(
                    tc.name,
                    action,
                    context={
                        "run_id": self._current_turn_id or self.session_id,
                        "turn_id": self._current_turn_id,
                        "session_id": self.session_id,
                        "surface": "loop",
                    },
                )
                if not result.granted:
                    # Co-Pilot (ask) mode is a QUESTION, not a refusal. Before
                    # the approval broker existed this branch silently denied
                    # every tool, so ask-mode looked like a broken agent that
                    # refused to act. Ask the human, then honour the answer.
                    if str(getattr(result, "source", "")) == "mode:manual_approval":
                        approved = await self._await_human_approval(tc.name, action, result)
                        if approved:
                            continue
                    self.logger.warning("Permission denied for %s: %s", tc.name, result.reason)
                    return False
            except Exception as exc:
                self.logger.exception("Permission audit failed for %s: %s", tc.name, exc)
                return False
        return True

    async def _await_human_approval(self, tool_name: str, action: str, result: Any) -> bool:
        """Ask a human to approve one tool call and wait for the answer.

        Emits a `tool.approval_request` work event (which every surface already
        renders) and blocks only this run until a decision arrives or the
        request times out. A timeout or missing surface denies, so an
        unattended session can never auto-approve itself.
        """
        try:
            from permissions.approval_broker import (
                DECISION_ALLOW,
                DECISION_ALLOW_ALWAYS,
                get_approval_broker,
            )
        except Exception:
            return False

        broker = get_approval_broker()
        request = broker.open(
            session_id=self.session_id,
            tool_name=tool_name,
            action=action,
            reason=str(getattr(result, "reason", "") or ""),
            turn_id=self._current_turn_id or "",
            timeout_s=float(getattr(self, "approval_timeout_s", 300.0) or 300.0),
        )
        await self._emit_work_event(request.to_event())

        decision = await broker.wait(request.request_id)
        granted = decision in (DECISION_ALLOW, DECISION_ALLOW_ALWAYS)

        if decision == DECISION_ALLOW_ALWAYS:
            # "Always allow" must persist, or the user is asked again forever.
            try:
                self.permissions.add_rule(tool_name, "*", granted=True)
            except Exception:
                self.logger.debug("Could not persist allow rule for %s", tool_name, exc_info=True)

        await self._emit_work_event({
            "id": request.request_id,
            "event_type": "tool.approval_request",
            "kind": "approval",
            "status": "done" if granted else "failed",
            "request_id": request.request_id,
            "turn_id": self._current_turn_id or "",
            "tool": tool_name,
            "action": action,
            "title": f"{'Approved' if granted else 'Denied'} {tool_name}",
            "target": action,
            "decision": decision,
        })
        return granted

    # ─────────────────────────────────────────────────────────────────────────
    # ⑤ EXECUTION — ALL PARALLEL
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_tools(self, tool_calls: List[ToolCall]) -> List[str]:
        """
        Execute tools with smart parallelism:
        - READ tools  → asyncio.gather() in parallel
        - WRITE tools → sequential (prevent state collisions)
        - Terminal/bash → SovereignSandbox tier routing
        - MCP tools  → async parallel
        - Hive tasks → parallel dispatch
        """
        read_calls  = []
        write_calls = []

        # Repetition guard: detect exact same tool+params as previous turn
        repeated_calls = []
        seen_signatures: Set[Tuple[str, str]] = set()
        for tc in tool_calls:
            tc_sig = (tc.name, json.dumps(tc.params, sort_keys=True))
            if tc_sig in seen_signatures:
                repeated_calls.append(tc.name)
            else:
                seen_signatures.add(tc_sig)

        for tc in tool_calls:
            tc_sig = (tc.name, json.dumps(tc.params, sort_keys=True))
            if tc_sig not in seen_signatures:
                continue
            seen_signatures.remove(tc_sig)
            tool = self.tool_registry.get(tc.name)
            if tool and tool.is_read_only(tc.params):
                read_calls.append(tc)
            else:
                write_calls.append(tc)

        observations: List[str] = []
        batch_failed = False

        if repeated_calls:
            observations.append(f"[REPETITION_GUARD] Tool(s) already executed this turn: {', '.join(repeated_calls)}. Use the prior result above.")

        async def record_result(tc: ToolCall, res: Any) -> None:
            nonlocal batch_failed
            if isinstance(res, Exception):
                batch_failed = True
                observations.append(f"[{tc.name}]: Error — {res}")
                exit_code = (
                    self.sandbox.last_exit_code
                    if self._work_kind_for_call(tc.name, tc.params) == "command"
                    else None
                )
                await self._emit_tool_event(
                    tc,
                    status="error",
                    error=str(res),
                    exit_code=exit_code,
                )
                await self._emit_runtime_event(
                    "plan.step.failed",
                    self._work_action_for_call(self._work_kind_for_call(tc.name, tc.params), tc.name, tc.params),
                    "failed",
                    event_id=f"plan_step_{self._current_turn_id or self.session_id}_{tc.call_id}",
                    parent_id=f"run_{self._current_turn_id or self.session_id}",
                    payload={"tool": tc.name, "target": self._work_target_for_call(tc.name, tc.params)},
                    error=str(res),
                )
                await self._handle_tool_failure(tc, res)
            else:
                observations.append(f"[{tc.name}]: {res}")

        if read_calls:
            results = await asyncio.gather(
                *(self._run_tool_step(tc) for tc in read_calls),
                return_exceptions=True,
            )
            for tc, res in zip(read_calls, results):
                await record_result(tc, res)

        for tc in write_calls:
            try:
                result = await self._run_tool_step(tc)
            except Exception as exc:
                result = exc
            await record_result(tc, result)

        self._last_run_failed = batch_failed
        return observations

    @staticmethod
    def _deterministic_evidence_summary(observations: List[str]) -> str:
        """Return a provider-independent final grounded only in real tool evidence."""
        combined = "\n".join(str(item) for item in observations)
        if "[web_search]" in combined:
            matches = re.findall(
                r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)(?:\s+—\s+([^\n]+))?",
                combined,
            )
            unique = []
            seen_urls = set()
            for title, url, snippet in matches:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                unique.append((title.strip(), url.strip(), snippet.strip()))
                if len(unique) >= 5:
                    break
            if unique:
                lines = ["Summary of the verified web results:"]
                for index, (title, _url, snippet) in enumerate(unique, start=1):
                    detail = snippet[:260].rstrip(" .") if snippet else ""
                    lines.append(f"\n{index}. {title}" + (f" — {detail}." if detail else ""))
                lines.append("\nOpen the gray web_search activity row to inspect sources and full links.")
                return "\n".join(lines)
        evidence = [str(item).strip()[:2000] for item in observations if str(item).strip()]
        if not evidence:
            return "Work completed and verified."
        return "Work completed and verified.\n\n" + "\n".join(f"- {item}" for item in evidence[:5])

    @staticmethod
    def _is_raw_tool_result_dump(response: str) -> bool:
        """True when a model copied tool transport text into the final answer."""
        text = str(response or "").strip()
        if not text:
            return False
        lower = text.lower()
        if "[web_search]:" in lower or "web search results for:" in lower:
            return True
        # Search providers can return long redirect links. Those belong in the
        # expandable Web search card, never in the concise chat answer.
        if "bing.com/news/apiclick" in lower:
            return True
        return len(re.findall(r"https?://", text)) >= 4

    @staticmethod
    def _deterministic_failure_summary(observations: List[str]) -> str:
        evidence = [str(item).strip()[:2000] for item in observations if str(item).strip()]
        if not evidence:
            return "Work failed because a real tool execution did not complete successfully."
        return "Work failed.\n\n" + "\n".join(f"- {item}" for item in evidence[:5])

    @staticmethod
    def _final_response_contains_evidence(response: str, observations: List[str]) -> bool:
        """Reject polished-but-empty finals that drop concrete tool evidence."""
        text = str(response or "").strip()
        if not text or text.endswith((':', '：')):
            return False
        evidence_text = "\n".join(str(item) for item in observations)
        evidence_urls = re.findall(r"https?://[^\s)\]]+", evidence_text)
        if evidence_urls:
            if any(url in text for url in evidence_urls):
                return True
            titles = re.findall(r"\[([^\]\n]+)\]\(https?://", evidence_text)
            response_words = set(re.findall(r"[a-z0-9]{4,}", text.lower()))
            evidence_words = set(re.findall(r"[a-z0-9]{4,}", " ".join(titles).lower()))
            # A concise synthesis can remain grounded without dumping URLs into chat.
            return len(response_words & evidence_words) >= 3 and len(text) >= 80
        return len(text) >= 40

    def _is_provider_error_text(self, value: Any) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        classifier = getattr(self.brain, "_looks_like_provider_error", None)
        if callable(classifier):
            try:
                if classifier(text):
                    return True
            except Exception:
                self.logger.warning("loop _is_provider_error_text: suppressed error", exc_info=True)
                pass
        head = text[:500].lower()
        patterns = (
            "error in stream:", "provider error", "provider_error", "api key is missing",
            "authentication fails", "authentication error", "connection refused",
            "failed to connect to provider", "model provider unavailable",
        )
        return any(pattern in head for pattern in patterns)

    async def _run_tool_step(self, call: ToolCall) -> str:
        """Tie each real tool execution to one real plan-step lifecycle."""
        run_id = self._current_turn_id or self.session_id
        event_id = f"plan_step_{run_id}_{call.call_id}"
        await self._emit_runtime_event(
            "plan.step.started",
            self._work_action_for_call(self._work_kind_for_call(call.name, call.params), call.name, call.params),
            "running",
            event_id=event_id,
            parent_id=f"run_{run_id}",
            payload={"tool": call.name, "target": self._work_target_for_call(call.name, call.params)},
        )
        try:
            tool_timeout = float(os.getenv("NEXUS_TOOL_TIMEOUT", "300"))
            result = await asyncio.wait_for(self._run_tool(call), timeout=tool_timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Tool '{call.name}' exceeded the {tool_timeout:g}s timeout and was aborted"
            )
        except Exception:
            raise
        kind = self._work_kind_for_call(call.name, call.params)
        target = self._work_target_for_call(call.name, call.params)
        completed_payload: Dict[str, Any] = {
            "tool": call.name,
            "target": target,
            # Keep the completed card useful even if the transport receives
            # this lifecycle event after the lower-level tool event.
            "output": str(result)[:20000],
        }
        if kind == "search":
            completed_payload["query"] = str(call.params.get("query") or target)
            completed_payload["sources"] = list(dict.fromkeys(
                re.findall(r"https?://[^\s)\]]+", str(result))
            ))[:20]
        await self._emit_runtime_event(
            "plan.step.completed",
            self._work_action_for_call(kind, call.name, call.params),
            "success",
            event_id=event_id,
            parent_id=f"run_{run_id}",
            payload=completed_payload,
        )
        return result

    def _work_kind_for_call(self, name: str, params: Dict[str, Any]) -> str:
        normalized = str(name or "").lower()
        if normalized in ("bash", "run_command", "terminal", "shell"):
            return "command"
        if "search" in normalized or normalized in {"web_search", "code_search"}:
            return "search"
        if "mcp" in normalized:
            return "mcp"
        if "browser" in normalized:
            return "browser"
        if "provider" in normalized:
            return "provider"
        if "plugin" in normalized:
            return "plugin"
        if "skill" in normalized:
            return "skill"
        if "hive" in normalized or "agent" in normalized or "worker" in normalized:
            return "hive"
        if any(key in params for key in ("path", "filepath", "old_string", "new_string", "content")):
            return "file"
        if normalized in {"reading", "creating", "modifying", "deleting", "read_file", "write_code"}:
            return "file"
        return "tool"

    def _work_target_for_call(self, name: str, params: Dict[str, Any]) -> str:
        for key in (
            "path", "filepath", "query", "command", "cmd", "url", "pattern",
            "target", "name", "action", "problem", "server"
        ):
            value = params.get(key)
            if value not in (None, ""):
                return str(value)
        return str(name or "work")

    def _work_action_for_call(self, kind: str, name: str, params: Dict[str, Any]) -> str:
        action_name = str(params.get("action") or "").lower()
        normalized_name = str(name or "").lower()
        if kind == "search":
            if normalized_name == "code_search":
                return "Code search"
            if normalized_name in {"grep", "glob"}:
                return "Search files"
            return "Web search"
        if kind == "command":
            return "Run command"
        if kind == "mcp":
            return "Use MCP"
        if kind == "browser":
            return "Browser"
        if kind == "provider":
            return "Check provider"
        if kind == "plugin":
            return "Use plugin"
        if kind == "skill":
            return "Use skill"
        if kind == "hive":
            return "Delegate task"
        if kind == "file":
            if action_name in {"read", "view"} or name in {"reading", "read_file"}:
                return "Read file"
            if action_name in {"write", "create", "mkdir"} or name in {"creating", "write_code"}:
                return "Create file"
            if action_name in {"delete", "remove"} or name == "deleting":
                return "Delete file"
            if action_name in {"edit", "update", "replace"} or name == "modifying":
                return "Edit file"
            return "Edit file"
        return "Use tool"

    async def _emit_stage_event(
        self,
        stage: str,
        action: str,
        target: str,
        status: str = "running",
        *,
        items: Optional[List[str]] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Publish safe execution telemetry without exposing private reasoning."""
        payload: Dict[str, Any] = {
            "id": f"stage_{self._current_turn_id or self.session_id}_{stage}",
            "turn_id": self._current_turn_id,
            "kind": "provider" if stage == "inference" else "test" if stage == "verification" else "task",
            "type": "stage",
            "stage": stage,
            "action": action,
            "target": target,
            "status": status,
            "visibility": "public" if stage == "planning" else "internal",
        }
        if items:
            payload["items"] = items
            payload["preview"] = "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))
            payload["result"] = payload["preview"]
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        await self._emit_work_event(payload)

    async def _emit_work_event(self, payload: Dict[str, Any]) -> None:
        sink = self.work_event_sink
        if not sink:
            return
        try:
            if inspect.iscoroutinefunction(sink):
                await sink(payload)
            else:
                result = sink(payload)
                if inspect.isawaitable(result):
                    await result
        except Exception as e:
            self.logger.debug(f"work_event_sink failed: {e}")

    async def _emit_runtime_event(
        self,
        event_type: str,
        title: str,
        status: str,
        *,
        event_id: str,
        parent_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        error: str = "",
        duration_ms: Optional[float] = None,
    ) -> None:
        """Central producer for canonical run/message/plan lifecycle events."""
        event: Dict[str, Any] = {
            "id": event_id,
            "event_type": event_type,
            "run_id": self._current_turn_id or self.session_id,
            "turn_id": self._current_turn_id,
            "kind": event_type.split(".", 1)[0],
            "title": title,
            "action": title,
            "status": status,
            "parent_id": parent_id,
            "payload": payload or {},
            "visibility": "public",
        }
        if error:
            event["error"] = {"message": error}
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        await self._emit_work_event(event)

    async def _emit_tool_event(self, call: ToolCall, *, status: str, result: str = "", error: str = "", exit_code: Optional[int] = None) -> None:
        kind = self._work_kind_for_call(call.name, call.params)
        target = self._work_target_for_call(call.name, call.params)
        payload: Dict[str, Any] = {
            "id": f"work_{self._current_turn_id or self.session_id}_{call.call_id}",
            "turn_id": self._current_turn_id,
            "tool": call.name,
            "name": call.name,
            "kind": kind,
            "action": self._work_action_for_call(kind, call.name, call.params),
            "target": target,
            "status": status,
            "visibility": "public",
        }
        if kind == "command":
            payload["command"] = str(
                call.params.get("CommandLine")
                or call.params.get("cmd")
                or call.params.get("command")
                or target
            )
            payload["cwd"] = str(call.params.get("cwd") or call.params.get("working_directory") or self.root)
        if kind == "file":
            payload["path"] = str(call.params.get("path") or call.params.get("filepath") or target)
        if kind == "search":
            payload["query"] = str(call.params.get("query") or target)
        if kind == "mcp":
            server = str(call.params.get("server") or call.params.get("mcp_server") or "MCP")
            mcp_tool = str(call.params.get("tool") or call.params.get("tool_name") or call.params.get("name") or call.params.get("action") or call.name)
            payload["server"] = server
            payload["mcp_tool"] = mcp_tool
            payload["target"] = f"{server} • {mcp_tool}"
        if result:
            payload["result"] = result[:20000]
            payload["output"] = result[:20000]
            if kind == "search":
                payload["preview"] = result[:20000]
                payload["sources"] = list(dict.fromkeys(re.findall(r"https?://[^\s)\]]+", result)))[:20]
        if error:
            payload["stderr"] = error[:20000]
            payload["result"] = error[:20000]
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)
        await self._emit_work_event(payload)

    async def _emit_tool_chunk(
        self,
        call: ToolCall,
        text: str,
        sequence: int,
        stream: str = "stdout",
    ) -> None:
        """Emit append-only tool output without waiting for tool completion."""
        if not text:
            return
        kind = self._work_kind_for_call(call.name, call.params)
        chunk_size = max(1, int(os.environ.get("NEXUS_TOOL_STREAM_CHARS", "256")))
        value = str(text)
        for part_index, chunk in enumerate(value[index:index + chunk_size] for index in range(0, len(value), chunk_size)):
            await self._emit_work_event({
                "id": f"work_{self._current_turn_id or self.session_id}_{call.call_id}",
                "turn_id": self._current_turn_id,
                "tool": call.name,
                "name": call.name,
                "kind": kind,
                "action": self._work_action_for_call(kind, call.name, call.params),
                "target": self._work_target_for_call(call.name, call.params),
                "status": "running",
                "stream": stream,
                "sequence": (sequence * 100000) + part_index,
                "append": True,
                "chunk": chunk,
                "output": chunk,
                "visibility": "public",
            })

    async def _run_tool(self, call: ToolCall) -> str:
        """Resolve and execute a single tool call."""
        await self._emit_tool_event(call, status="running")
        # Commands are owned by the process sandbox, not the plugin registry.
        # Resolve this first so a stale bash adapter cannot block execution.
        if call.name in ("bash", "run_command", "terminal", "shell"):
            cmd = (
                call.params.get("CommandLine") or
                call.params.get("cmd") or
                call.params.get("command") or ""
            )
            self.sandbox.tier = self.sandbox_tier
            chunks: List[str] = []
            sequence = 0
            async for chunk in self.sandbox.stream_execute(
                cmd,
                workdir=call.params.get("cwd") or call.params.get("working_directory"),
            ):
                chunks.append(chunk)
                await self._emit_tool_chunk(call, chunk, sequence)
                sequence += 1
            result = "".join(chunks)
            exit_code = self.sandbox.last_exit_code
            if exit_code not in (None, 0):
                error = f"Error: command exited with code {exit_code}.\n{result}"
                raise RuntimeError(error)
            await self._emit_tool_event(call, status="done", result=str(result), exit_code=exit_code)
            return result

        # Auto-discover if not registered
        tool = self.tool_registry.get(call.name)
        if tool is None:
            self.logger.info(f"[AUTO-DISCOVER] '{call.name}' not in registry — scanning...")
            discovered = self._discover_and_register_tool(call.name)
            if discovered is None:
                available = list(self.tool_registry.list_tools().keys())
                error_text = f"Error: Tool '{call.name}' not found. Available: {available}"
                raise RuntimeError(error_text)
            tool = self.tool_registry.get(call.name)

        from tools.nexus_tools.base_tool import ToolResult
        chunks: List[str] = []
        sequence = 0
        failed_error = ""
        runtime_context = {
            "work_event_sink": self.work_event_sink,
            "turn_id": self._current_turn_id,
            "session_id": self.session_id,
            "root": self.root,
        }
        async for item in self.tool_registry.stream_execute(
            call.name,
            **{**call.params, "_runtime_context": runtime_context},
        ):
            if isinstance(item, ToolResult):
                text = str(item.output or item.error or "")
                if not item.success:
                    failed_error = str(item.error or "Tool execution failed")
            else:
                text = str(item)
            if text:
                chunks.append(text)
                await self._emit_tool_chunk(
                    call,
                    text,
                    sequence,
                    stream="stderr" if failed_error else "stdout",
                )
                sequence += 1

        result = "".join(chunks)
        if failed_error:
            error_text = f"Error: {failed_error}"
            raise RuntimeError(error_text)
        await self._emit_tool_event(call, status="done", result=result)
        return result

    def _discover_and_register_tool(self, name: str):
        """Auto-discover a tool from tools/<name>/ directory and register it."""
        import importlib.util

        # Check tools/
        tool_dir = os.path.join(self.root, "tools", name)
        if os.path.isdir(tool_dir):
            scripts_dir = os.path.join(tool_dir, "scripts")
            if os.path.isdir(scripts_dir):
                from tools.nexus_tools.base_tool import BaseTool
                # Load the tool's .jsnol metadata so params/execution policy are honored
                # (passing schema={} voids required-param validation and tool policy).
                schema = {}
                for jsnol_candidate in (
                    os.path.join(tool_dir, f"{name}.jsnol"),
                    os.path.join(tool_dir, ".jsnol"),
                ):
                    if os.path.isfile(jsnol_candidate):
                        try:
                            schema = json.loads(open(jsnol_candidate, encoding="utf-8").read())
                        except Exception:
                            schema = {}
                        break
                for script in sorted(s for s in os.listdir(scripts_dir) if s.endswith(".py") and not s.startswith("_")):
                    try:
                        spec = importlib.util.spec_from_file_location(name, os.path.join(scripts_dir, script))
                        if spec and spec.loader:
                            mod = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(mod)
                            import inspect as _inspect
                            for _, cls in _inspect.getmembers(mod, _inspect.isclass):
                                if issubclass(cls, BaseTool) and cls is not BaseTool:
                                    instance = cls(root_dir=self.root)
                                    from tools.nexus_tools.registry import ToolEntry
                                    entry = ToolEntry(name=name, schema=schema, instance=instance)
                                    self.tool_registry._tools[name] = entry
                                    self.logger.info(f"[AUTO-DISCOVER] Loaded tool: {name}")
                                    return entry
                    except Exception as e:
                        self.logger.warning(f"[AUTO-DISCOVER] Failed to load {name}: {e}")

        # Check skills/
        skill_dir = os.path.join(self.root, "skills", name)
        if os.path.isdir(skill_dir):
            self.logger.info(f"[AUTO-DISCOVER] Found skill: {name}")
            # Skills are handled separately — return sentinel
            return True

        # Check plugins/
        plugin_dir = os.path.join(self.root, "plugins", name)
        if os.path.isdir(plugin_dir):
            self.logger.info(f"[AUTO-DISCOVER] Found plugin: {name}")
            return True

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # ⑥ VERIFICATION — ALL PARALLEL
    # ─────────────────────────────────────────────────────────────────────────

    async def _verify_all_parallel(
        self,
        messages:   List[Dict[str, str]],
        tool_calls: List[ToolCall],
    ) -> Dict[str, Any]:
        """Run ALL verification tasks in parallel."""
        tasks = [
            self._verify_execution(messages),          # Error scan + vaccine
            self._run_targeted_tests(tool_calls),      # Auto test selection
            asyncio.to_thread(self._read_todo_md),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        verify_result = results[0] if not isinstance(results[0], Exception) else (True, None)
        # results[1] = test result (currently informational)
        todo_str      = results[2] if not isinstance(results[2], Exception) else ""

        success, vaccine = verify_result if isinstance(verify_result, tuple) else (True, None)
        return {"success": success, "vaccine": vaccine, "todo": todo_str}

    def _read_todo_md(self) -> str:
        """Read todo.md from disk."""
        todo_path = os.path.join(self.root, "todo.md") if self.root else "todo.md"
        try:
            if os.path.isfile(todo_path):
                with open(todo_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
        except Exception:
            logger.warning("orchestrators/loop.py:2036 suppressed error", exc_info=True)
        return ""

    @staticmethod
    def _todo_matches_task(todo_text: str, task_desc: str) -> bool:
        """Only replay a saved plan when its task title matches this request."""
        match = re.search(r"^\s*task\s*name\s*:\s*(.+)$", str(todo_text or ""), re.IGNORECASE | re.MULTILINE)
        if not match:
            return False
        plan_task = re.sub(r"\s+", " ", match.group(1).strip().lower())
        current_task = re.sub(r"\s+", " ", str(task_desc or "").strip().lower())
        return bool(plan_task and current_task and (plan_task == current_task or plan_task in current_task or current_task in plan_task))

    async def _verify_execution(self, messages: List[Dict[str, str]]) -> Tuple[bool, Optional[str]]:
        """Scan last observation for errors and build failure vaccine."""
        if not messages:
            return True, None

        last_msg  = messages[-1].get("content", "")
        has_error = False
        error_lines: List[str] = []

        for line in last_msg.splitlines():
            line_lower = line.lower()
            if any(kw in line_lower for kw in ("error", "exception", "failed", "traceback")):
                has_error = True
                clean = line.strip()
                if len(clean) > 120:
                    clean = clean[:120] + "..."
                if clean and clean not in error_lines:
                    error_lines.append(clean)

        if has_error:
            if error_lines:
                specific = " | ".join(error_lines[:3])
                vaccine = (
                    f"CRITICAL PREVENTIVE VACCINE: Execution failed: [{specific}]. "
                    "Inspect traceback, fix syntax/import/logic errors, verify paths before retrying."
                )
            else:
                vaccine = (
                    "CRITICAL PREVENTIVE VACCINE: Unknown execution error. "
                    "Verify syntax, imports, and file existence before re-executing."
                )
            # Record in failure memory
            try:
                await asyncio.to_thread(
                    self.failure_memory.record,
                    {"vaccine": vaccine, "errors": error_lines}
                )
            except Exception:
                self.logger.warning("loop : suppressed error", exc_info=True)
                pass
            return False, vaccine

        return True, None

    async def _run_targeted_tests(self, tool_calls: List[ToolCall]) -> Optional[str]:
        """Select and run targeted tests based on modified files."""
        try:
            if not self.tool_registry.get("git_ops"):
                return None
            diff = await self.tool_registry.execute("git_ops", action="diff", name_only=True)
            if not diff.success or not diff.output:
                return None
            from optimization.test_selection import TestSelector
            ts           = TestSelector(self.root)
            changed      = [f.strip() for f in diff.output.split("\n") if f.strip()]
            selected     = ts.select_tests(changed)
            if not selected:
                return None
            if self.tool_registry.get("test_runner"):
                res = await self.tool_registry.execute("test_runner", target=" ".join(selected))
                return res.output if res.success else res.error
        except Exception as e:
            self.logger.debug(f"[VERIFY] Targeted tests failed: {e}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # ⑦ EVOLVE — ALL PARALLEL
    # ─────────────────────────────────────────────────────────────────────────

    async def _finalize_session(self, task_desc: str, messages: List[Dict[str, str]]):
        """Run all 5 evolution steps + MemoryManager sync in parallel."""
        await self.kernel.plugins.trigger_hooks("on_session_end", task_desc, messages)

        last_resp = ""
        for m in reversed(messages):
            if m["role"] == "assistant":
                last_resp = m["content"]
                break

        if self._last_run_requires_tools:
            success = (
                self._last_run_had_tool_execution
                and self._last_run_verified
                and not self._last_run_failed
            )
        else:
            success = bool(last_resp.strip()) and not self._last_run_failed

        # Sync via MemoryManager
        evolve_tasks = [
            self._evolve_log(success, task_desc),          # 1: EvolutionLog
            self._evolve_self_improve(messages),           # 2: SelfImprovementEngine
            self._evolve_gap_forge(),                      # 3: GapForge (retry gaps)
            self._evolve_hive_feedback(messages),          # 4: Hive persona scores
            self._evolve_memory_crystallize(messages),     # 5: Memory crystallize
            self._maybe_run_curator(),                     # 6: Skill Curator (idle lifecycle)
        ]
        await asyncio.gather(*evolve_tasks, return_exceptions=True)

        # MemoryManager sync — persists to .opencode/memory/ + session + forge
        try:
            # Use the real user task, NOT messages[0] (which is the system prompt).
            real_user = next((m.get("content", "") for m in messages if m.get("role") == "user"), task_desc)
            await self.memory_manager.sync_all(real_user or task_desc, last_resp)
        except Exception:
            self.logger.warning("loop : suppressed error", exc_info=True)
            pass

        # Write session bus
        await asyncio.to_thread(self._write_session_bus)

    def _start_background_finalization(self, task_desc: str, messages: List[Dict[str, str]]) -> None:
        """Run learning/evolution after the response without delaying the user."""
        task = asyncio.create_task(self._finalize_session(task_desc, list(messages)))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def aclose(self) -> None:
        """Drain loop-owned finalizers before the hosting event loop shuts down.

        Finalization deliberately outlives the response stream, so its owner must
        join it before asyncio closes the default executor used by ``to_thread``.
        """
        await asyncio.to_thread(self._shutdown_mcp_servers)
        background_tasks = getattr(self, "_background_tasks", set())
        while background_tasks:
            tasks = tuple(background_tasks)
            await asyncio.gather(*tasks, return_exceptions=True)
            background_tasks = getattr(self, "_background_tasks", set())

    async def _evolve_log(self, success: bool, task_desc: str):
        """Step 1: EvolutionLog win/lose."""
        try:
            fn = self.evolution_log.win if success else self.evolution_log.lose
            await asyncio.to_thread(
                fn, "agent", "nexus",
                f"Session {'completed' if success else 'failed'}: {task_desc[:80]}",
                0.0, {"task": task_desc}
            )
        except Exception:
            self.logger.warning("loop async _evolve_log: suppressed error", exc_info=True)
            pass

    async def _evolve_self_improve(self, messages: List[Dict[str, str]]):
        """Step 2: SelfImprovementEngine — analyze session, extract top 3 actions."""
        try:
            with protected_core_writes("_evolve_self_improve"):
                se     = SelfImprovementEngine(self.root)
                record = await asyncio.to_thread(se.analyze_session, messages)
                if record and record.actions:
                    for action in record.actions[:3]:
                        await asyncio.to_thread(self.evolution_log.improvement, action)
                    # Persist actions to the durable, consumable backlog so
                    # self-improvement output is no longer write-only.
                    try:
                        from evolution.backlog import queue_improvement_action

                        for action in record.actions[:3]:
                            await asyncio.to_thread(
                                queue_improvement_action,
                                {
                                    "action": action,
                                    "source": "self_improvement.analyze_session",
                                    "session_id": getattr(record, "session_id", "") or "",
                                    "score": getattr(record, "score", None),
                                    "summary": (getattr(record, "summary", "") or "")[:300],
                                },
                                self.root,
                            )
                    except Exception:
                        self.logger.warning(
                            "loop async _evolve_self_improve: backlog queue failed", exc_info=True
                        )
        except Exception:
            self.logger.warning("loop async _evolve_self_improve: suppressed error", exc_info=True)
            pass

    async def _evolve_gap_forge(self):
        """Step 3: GapForge — retry all gaps found during session."""
        if not self._gaps_found:
            return
        self.logger.info(f"[EVOLVE:GAP] Retrying {len(self._gaps_found)} gaps...")
        for gap in self._gaps_found:
            try:
                await self._fill_gap(gap)
                self.logger.info(f"[EVOLVE:GAP] Filled: {gap.get('type')} '{gap.get('name')}'")
            except Exception:
                self.logger.warning("loop async _evolve_gap_forge: suppressed error", exc_info=True)
                pass
        self._gaps_found.clear()

    async def _maybe_spawn_hive(self, task_desc: str) -> Optional[str]:
        """Opt-in multi-agent decomposition: when NEXUS_HIVE=1 and the task looks
        complex, split it into persona'd subtasks, run them as parallel sub-agents
        (each with its own slice of work), and return the consolidated result as an
        extra context block. Never replaces the main loop — augments it.

        Returns the consolidated text, or None if hive is off / decomposition failed.
        """
        if not self.feature_hive:
            return None
        try:
            engine = self.hive  # lazy NexusHiveEngine(self.root)
            try:
                engine.set_tool_registry(self.tool_registry)
            except Exception:
                pass

            def _llm(messages):
                from providers.factory import NexusProviderFactory
                f = NexusProviderFactory()
                p = f.get_provider_by_name("cloud", "deepseek") if hasattr(f, "get_provider_by_name") else None
                if p is None:
                    p = f.get_provider()
                if p is None:
                    raise RuntimeError("no provider")
                out = p.generate(messages[-1]["content"], messages[0]["content"], None) if hasattr(p, "generate") else None
                return str(out) if out else ""
            engine.set_llm_call(_llm)

            subs = await engine.decompose_task(task_desc, _llm)
            if not subs:
                return None
            hive_id, _agents = await engine.spawn_hive([(t, persona) for t, persona in subs])
            consolidated = await engine.consolidate_hive(hive_id, llm_call=_llm)
            if consolidated:
                await self._emit_runtime_event(
                    "hive.done", f"Hive completed {len(subs)} sub-agents", "success",
                    payload={"subtasks": len(subs)},
                )
            return consolidated or None
        except Exception as e:
            self.logger.warning("hive spawn failed (ignored): %s", e)
            return None

    async def _evolve_hive_feedback(self, messages: List[Dict[str, str]]):
        """Step 4: Hive worker performance scoring by ARCHITECT."""
        try:
            hive_dir = os.path.join(self.root, "workspace", "hive")
            if os.path.isdir(hive_dir):
                # Write session feedback for ARCHITECT to review
                feedback = {
                    "session_id": self.session_id,
                    "turns": len([m for m in messages if m["role"] == "assistant"]),
                    "timestamp": time.time(),
                }
                fb_path = os.path.join(hive_dir, f"feedback_{self.session_id}.json")
                with open(fb_path, "w", encoding="utf-8") as f:
                    json.dump(feedback, f, indent=2)
        except Exception:
            self.logger.warning("loop async _evolve_hive_feedback: suppressed error", exc_info=True)
            pass

    async def _evolve_memory_crystallize(self, messages: List[Dict[str, str]]):
        """Step 5: LIBRARIAN distills key learnings — persist long-term memory."""
        try:
            # Extract key learnings from session
            learnings = []
            for m in messages:
                if m["role"] == "assistant" and len(m["content"]) > 100:
                    learnings.append(m["content"][:300])

            if learnings:
                # Persist to memory
                forge = MemoryForge(self.root)
                await asyncio.to_thread(
                    forge.forge,
                    f"session_{self.session_id}",
                    f"Session learnings: {'; '.join(learnings[:3])}"
                )
        except Exception:
            self.logger.warning("loop async _evolve_memory_crystallize: suppressed error", exc_info=True)
            pass

        # Always save + sync memory
        self.save_memory()

    # ─────────────────────────────────────────────────────────────────────────
    # GAP DETECTION & FORGE
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_evolution_gaps(self, tool_calls, observations):
        """Hook: post_tool_call — detect gaps from tool observations."""
        obs_text = "\n".join(str(o) for o in observations if str(o).strip())
        if obs_text:
            await self._fill_gap_during_session(obs_text)

    async def _handle_tool_failure(self, tc: ToolCall, error: Exception):
        """Auto-create missing tools via ToolForge when a tool call fails."""
        msg = str(error).lower()
        if any(kw in msg for kw in ("not found", "unknown tool", "no such tool")):
            self.logger.info(f"[EVOLVE] Tool '{tc.name}' not found — attempting ToolForge...")
            try:
                forge  = ToolForge(self.root)
                result = await asyncio.to_thread(forge.forge, {
                    "name": tc.name,
                    "description": f"Auto-created to fulfill: {tc.name}",
                    "params": tc.params,
                })
                if result.get("created"):
                    await asyncio.to_thread(self.evolution_log.improvement, f"Auto-created tool '{tc.name}'")
                    self.logger.info(f"[EVOLVE] Tool '{tc.name}' created successfully")
            except Exception as e:
                self.logger.debug(f"[EVOLVE] ToolForge failed: {e}")
                self._gaps_found.append({"type": "missing_tool", "name": tc.name, "error": str(error)})

    async def _fill_gap_during_session(self, context: str):
        """Ask model to detect gaps in conversation context and fill them."""
        try:
            prompt = f"""[EVOLUTION_GAP_DETECTION]
Analyze this conversation context for gaps NEXUS should fill:

{context[:2000]}

Respond with JSON only:
{{"gaps": [
  {{"type": "missing_tool|missing_skill|memory_candidate|knowledge_gap", "name": "...", "reason": "...", "create_now": true|false}}
]}}
If no gaps, return: {{"gaps": []}}
"""
            result = await asyncio.to_thread(self._call_model_for_prompt, prompt)
            if not result:
                return
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1].rsplit("\n", 1)[0]
            data = json.loads(result)
            for gap in data.get("gaps", []):
                if gap.get("create_now"):
                    await self._fill_gap(gap)
                else:
                    self._gaps_found.append(gap)
        except Exception:
            self.logger.warning("loop : suppressed error", exc_info=True)
            pass

    async def _fill_gap(self, gap: Dict[str, Any]):
        """Execute a single gap fill immediately."""
        gtype = gap.get("type", "")
        name  = gap.get("name", "unknown")
        # RUNTIME GUARD: never let a gap-fill target a core source file.
        try:
            for candidate in (gap.get("path"), gap.get("target"), name):
                if isinstance(candidate, str) and candidate.strip():
                    assert_not_rewriting_core(
                        os.path.join(self.root, candidate)
                        if not os.path.isabs(candidate) else candidate,
                        operation=f"gap_fill({gtype})",
                    )
        except PermissionError as e:
            self.logger.error(f"[RUNTIME_GUARD] Gap fill blocked for '{name}': {e}")
            return
        try:
            with protected_core_writes(f"_fill_gap:{gtype}"):
                if gtype == "missing_tool":
                    forge = ToolForge(self.root)
                    await asyncio.to_thread(forge.forge, {"name": name, "description": gap.get("reason", "")})
                elif gtype == "missing_skill":
                    forge = SkillForge(self.root)
                    await asyncio.to_thread(forge.forge, name, gap.get("reason", ""))
                elif gtype == "memory_candidate":
                    forge = MemoryForge(self.root)
                    await asyncio.to_thread(forge.forge, name, gap.get("reason", ""))
                elif gtype == "knowledge_gap":
                    forge = KnowledgeForge(self.root)
                    await asyncio.to_thread(forge.forge, name, gap.get("reason", ""))
        except Exception as e:
            self._gaps_found.append(gap)
            self.logger.debug(f"[EVOLVE] Gap fill failed for '{name}': {e}")

    async def _retry_gap(self, gap: Dict[str, Any]):
        try:
            await self._fill_gap(gap)
            self.logger.info(f"[EVOLVE:GAP-FILLED] {gap.get('type')} '{gap.get('name')}' retried successfully")
        except Exception:
            self.logger.warning("loop async _retry_gap: suppressed error", exc_info=True)
            pass

    # ── Curator ──────────────────────────────────────────────────────────

    async def _maybe_run_curator(self) -> None:
        if not self.curator.enabled:
            return
        if getattr(self, "_curator_last_run", 0) and time.time() - self._curator_last_run < 3600:
            return
        try:
            result = await asyncio.to_thread(self.curator.run_once)
            if result.get("archived", 0) > 0 or result.get("restored", 0) > 0:
                self.logger.info(f"[CURATOR] {result}")
            self._curator_last_run = time.time()
        except Exception as e:
            self.logger.debug(f"[CURATOR] run_once failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # CHECKPOINT
    # ─────────────────────────────────────────────────────────────────────────

    def _save_checkpoint(self, messages: List[Dict], task_desc: str, turn: int):
        """Save checkpoint to disk — resume after crash."""
        try:
            ckpt_dir = os.path.join(self.root, "logs", "checkpoints")
            os.makedirs(ckpt_dir, exist_ok=True)
            ckpt_path = os.path.join(ckpt_dir, f"{self.session_id}.json")
            plan_text = self._read_todo_md()
            with open(ckpt_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": self.session_id,
                    "task_desc":  task_desc,
                    "turn":       turn,
                    "state":      "",
                    "messages":   messages[-20:],  # Keep last 20 for resume
                    "plan":       plan_text,
                    "timestamp":  time.time(),
                }, f, indent=2)
        except Exception as e:
            self.logger.debug(f"Checkpoint save failed: {e}")

    def load_checkpoint(self, session_id: str) -> Optional[Dict]:
        """Load a previous checkpoint to resume a session."""
        try:
            ckpt_path = os.path.join(self.root, "logs", "checkpoints", f"{session_id}.json")
            if os.path.exists(ckpt_path):
                with open(ckpt_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            self.logger.warning("loop load_checkpoint: suppressed error", exc_info=True)
            pass
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # MISSION REPLAY
    # ─────────────────────────────────────────────────────────────────────────

    def _log_mission_replay(self, tool_calls: List[ToolCall], observations: List[str]):
        """Log tool calls + results to mission replay JSONL for audit trail."""
        try:
            replay_dir = os.path.join(self.root, "workspace", "work_events")
            os.makedirs(replay_dir, exist_ok=True)
            replay_file = os.path.join(replay_dir, f"{self.session_id}.jsonl")
            with open(replay_file, "a", encoding="utf-8") as f:
                for tc, obs in zip(tool_calls, observations):
                    entry = {
                        "ts":     time.time(),
                        "turn":   self._current_turn_id,
                        "tool":   tc.name,
                        "params": tc.params,
                        "result": obs[:500],
                    }
                    f.write(json.dumps(entry) + "\n")
        except Exception:
            self.logger.warning("loop _log_mission_replay: suppressed error", exc_info=True)
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # MODEL CALLS
    # ─────────────────────────────────────────────────────────────────────────

    def _call_model(self, messages: List[Dict]) -> str:
        """Call model — stream then fallback to generate, scrub output."""
        self._scrubber.reset()
        # Sanitize messages before sending
        messages = MessageSanitizer.sanitize_messages(messages)
        full = ""
        try:
            for chunk in self.brain.stream_generate(messages=messages):
                # Scrub each chunk
                cleaned = self._scrubber.feed(chunk)
                full += cleaned
            # Flush any remaining buffer
            full += self._scrubber.flush()

            if not full.strip():
                fallback = self.brain.generate(messages=messages)
                if fallback and not getattr(self.brain, "_looks_like_provider_error", lambda x: False)(fallback):
                    full = StreamingContextScrubber.clean_once(fallback)
        except Exception as e:
            self.logger.error(f"Model call failed: {e}")
            return ""

    async def _safe_model_call(self, messages: List[Dict], *, timeout: float = 180.0) -> str:
        """Call the model off the event loop with a hard timeout so a slow/hanging
        provider can never freeze the agent turn indefinitely.
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_model, messages), timeout=timeout
            )
        except asyncio.TimeoutError:
            self.logger.error("Model call timed out after %.0fs", timeout)
            return ""
        except Exception as e:  # pragma: no cover - defensive
            self.logger.error("Model call failed: %s", e)
            return ""

    async def _stream_model(
        self,
        messages: List[Dict],
        *,
        max_tokens: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Yield scrubbed model chunks in real time while also preserving fallback behavior."""
        sanitized_messages = MessageSanitizer.sanitize_messages(messages)
        chunk_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        stop_event = threading.Event()
        scrubber = StreamingContextScrubber()

        def _run_stream() -> None:
            stream = None
            try:
                kwargs: Dict[str, Any] = {"messages": sanitized_messages}
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                if provider:
                    kwargs["provider"] = provider
                if model:
                    kwargs["model"] = model
                stream = self.brain.stream_generate(**kwargs)
                for chunk in stream:
                    if stop_event.is_set():
                        return
                    if getattr(self.brain, "_looks_like_provider_error", lambda value: False)(chunk):
                        chunk_queue.put(("error", str(chunk)))
                        return
                    cleaned = scrubber.feed(chunk)
                    if cleaned:
                        chunk_size = max(1, int(os.environ.get("NEXUS_MODEL_STREAM_CHARS", "64")))
                        for index in range(0, len(cleaned), chunk_size):
                            if stop_event.is_set():
                                return
                            chunk_queue.put(("chunk", cleaned[index:index + chunk_size]))
                tail = scrubber.flush()
                if tail:
                    chunk_queue.put(("chunk", tail))
                chunk_queue.put(("done", ""))
            except Exception as e:
                chunk_queue.put(("error", str(e)))
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        self.logger.debug("Provider stream close failed", exc_info=True)

        threading.Thread(target=_run_stream, daemon=True).start()

        emitted_any = False
        try:
            while True:
                if self._abort_flag.is_set():
                    return
                try:
                    kind, payload = await asyncio.to_thread(chunk_queue.get, True, 0.2)
                except queue.Empty:
                    continue
                if kind == "chunk":
                    emitted_any = True
                    yield payload
                    continue
                if kind == "done":
                    break
                if kind == "error":
                    self.logger.error(f"Model stream failed: {payload}")
                    raise RuntimeError(f"Provider stream failed: {payload}")
        finally:
            stop_event.set()

        if not emitted_any:
            kwargs = {"messages": sanitized_messages}
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if provider:
                kwargs["provider"] = provider
            if model:
                kwargs["model"] = model
            fallback = self.brain.generate(**kwargs)
            if fallback and getattr(self.brain, "_looks_like_provider_error", lambda x: False)(fallback):
                raise RuntimeError(f"Provider request failed: {fallback}")
            if fallback:
                cleaned_fallback = StreamingContextScrubber.clean_once(fallback)
                if cleaned_fallback:
                    yield cleaned_fallback

    def _call_model_for_prompt(self, prompt: str) -> str:
        """Direct model call — no conversation history."""
        try:
            return self.brain.generate(messages=[{"role": "user", "content": prompt}])
        except Exception as e:
            self.logger.warning("_call_model_for_prompt: %s", e)
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # TOOL CALL EXTRACTION
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_tool_calls(self, response: str) -> List[ToolCall]:
        calls: List[ToolCall] = []
        calls.extend(self._extract_dotted_tool_calls(response))
        calls.extend(self._extract_inline_tool_calls(response))
        for obj in self._extract_raw_json_objects(response):
            self._append_call(calls, obj)
        if not calls:
            calls.extend(self._extract_colon_function_tool_calls(response))
        if not calls:
            for call in self._extract_dsml_tool_calls(response):
                calls.append(call)
            for call in self._extract_compact_xml_tool_calls(response):
                calls.append(call)
        return [self._canonicalize_tool_call(call) for call in calls]

    def _extract_colon_function_tool_calls(self, text: str) -> List[ToolCall]:
        """Parse provider envelopes such as ``<function: web_search>``.

        Accept the malformed ``value=\"text</param>`` form emitted by some
        OpenAI-compatible providers as well as normal quoted values.
        """
        calls: List[ToolCall] = []
        if not text or "<function:" not in text.lower():
            return calls
        function_pattern = re.compile(
            r"<function:\s*([\w.-]+)\s*>([\s\S]*?)(?:</function>|$)",
            re.IGNORECASE,
        )
        param_pattern = re.compile(
            r"<param\s+name=[\"']([^\"']+)[\"']\s+value=[\"']?([\s\S]*?)(?:[\"']?\s*/?>|</param>)",
            re.IGNORECASE,
        )
        for name, body in function_pattern.findall(text):
            params: Dict[str, Any] = {}
            for param_name, raw_value in param_pattern.findall(body):
                params[param_name] = self._coerce_dsml_value(
                    html.unescape(raw_value).strip().strip('\"')
                )
            calls.append(ToolCall(name.strip(), params))
        return calls

    def _extract_inline_tool_calls(self, text: str) -> List[ToolCall]:
        """Extract word({...}) inline tool calls like web_search({"query": "cats"})."""
        calls: List[ToolCall] = []
        known = set(self.tool_registry.list_tools(include_unavailable=False).keys()) | {
            "reading", "creating", "modifying", "deleting", "terminal",
            "web_search", "code_search", "git_ops", "test_runner", "hive",
            "deep_research",
        }
        # word({...}) inline calls
        for match in re.finditer(r"\b([a-zA-Z_]\w*)\(\s*(\{)", text):
            name = match.group(1).lower()
            if name not in known:
                continue
            start = match.start(2)
            try:
                params, consumed = json.JSONDecoder().raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            tail = text[start + consumed:]
            if isinstance(params, dict) and re.match(r"\s*\)", tail):
                calls.append(ToolCall(name, params))
        # <function=name>{json} provider format
        for match in re.finditer(r"<function=(\w+)>\s*(\{)", text):
            name = match.group(1).lower()
            if name not in known:
                continue
            start = match.start(2)
            try:
                params, _consumed = json.JSONDecoder().raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(params, dict):
                calls.append(ToolCall(name, params))
        return calls

    @staticmethod
    def _canonicalize_tool_call(call: ToolCall) -> ToolCall:
        """Translate common provider aliases into the registered NEXUS tools."""
        name = str(call.name or "").strip().lower()
        raw_params = call.params or {}
        if isinstance(raw_params, str):
            try:
                raw_params = json.loads(raw_params)
            except json.JSONDecodeError:
                raw_params = {}
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        action = str(params.get("action") or "").strip().lower()

        def ps_literal(value: str) -> str:
            return str(value or ".").replace("'", "''")

        if name == "file_ops":
            if action in {"read", "view"}:
                return ToolCall("reading", {"path": params.get("path", "")}, call.call_id)
            if action in {"write", "create"} and "content" in params:
                return ToolCall("creating", {"path": params.get("path", ""), "content": params.get("content", "")}, call.call_id)
            if action in {"edit", "update", "replace"}:
                return ToolCall(
                    "modifying",
                    {
                        "path": params.get("path", ""),
                        "old_string": params.get("old_string", ""),
                        "new_string": params.get("new_string", params.get("content", "")),
                    },
                    call.call_id,
                )
            if action in {"delete", "remove"}:
                return ToolCall("deleting", {"path": params.get("path", "")}, call.call_id)
            if action in {"mkdir", "create"}:
                path = ps_literal(params.get("path", ""))
                return ToolCall("bash", {"command": f"powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -LiteralPath '{path}'\""}, call.call_id)
            if action == "list":
                path = ps_literal(params.get("path", "."))
                return ToolCall("bash", {"command": f"powershell -NoProfile -Command \"Get-ChildItem -Force -LiteralPath '{path}'\""}, call.call_id)
        if name in {"read", "read_file", "view"}:
            return ToolCall("reading", {"path": params.get("path", params.get("filepath", ""))}, call.call_id)
        if name in {"write", "write_code", "create"}:
            if "content" in params:
                return ToolCall("creating", {"path": params.get("path", params.get("filepath", "")), "content": params.get("content", "")}, call.call_id)
            path = ps_literal(params.get("path", params.get("filepath", "")))
            return ToolCall("bash", {"command": f"powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -LiteralPath '{path}'\""}, call.call_id)
        if name in {"edit", "update", "replace"}:
            return ToolCall(
                "modifying",
                {
                    "path": params.get("path", params.get("filepath", "")),
                    "old_string": params.get("old_string", ""),
                    "new_string": params.get("new_string", params.get("content", "")),
                },
                call.call_id,
            )
        if name in {"delete", "remove"}:
            return ToolCall("deleting", {"path": params.get("path", params.get("filepath", ""))}, call.call_id)
        if name == "list":
            path = ps_literal(params.get("path", "."))
            return ToolCall("bash", {"command": f"powershell -NoProfile -Command \"Get-ChildItem -Force -LiteralPath '{path}'\""}, call.call_id)
        if name == "mkdir":
            path = ps_literal(params.get("path", params.get("filepath", "")))
            return ToolCall("bash", {"command": f"powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -LiteralPath '{path}'\""}, call.call_id)
        if name in {"shell", "terminal", "execute_command", "run_command"}:
            command = params.get("command") or params.get("cmd") or params.get("input") or ""
            mkdir_match = re.fullmatch(r"\s*mkdir\s+(?:-p\s+)?[\"']?([^\"']+?)[\"']?\s*", str(command), re.IGNORECASE)
            if mkdir_match:
                path = ps_literal(mkdir_match.group(1).strip())
                return ToolCall(
                    "bash",
                    {"command": f"powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -LiteralPath '{path}'\""},
                    call.call_id,
                )
            return ToolCall("bash", {**params, "command": command}, call.call_id)
        aliases = {
            "search_code": "code_search",
            "web_research": "web_search",
            "search_web": "web_search",
            "run_tests": "test_runner",
        }
        return ToolCall(aliases.get(name, name), params, call.call_id)

    @staticmethod
    def _progress_tag_pattern() -> "re.Pattern[str]":
        return re.compile(r"<progress>(.*?)</progress>", re.DOTALL | re.IGNORECASE)

    @classmethod
    def _extract_progress_notes(cls, response: str) -> Tuple[str, List[str]]:
        """Split public ``<progress>`` narration out of a model response.

        Returns ``(response_without_tags, notes)``. Notes are short user-facing
        status lines describing the next action — they are deliberately public
        (unlike reasoning/thinking blocks, which are never surfaced). Unclosed or
        empty tags are ignored and the text is left untouched.
        """
        text = str(response or "")
        if "<progress>" not in text.lower():
            return text, []
        notes: List[str] = []

        def _take(match: "re.Match[str]") -> str:
            note = match.group(1).strip()
            if note:
                notes.append(note)
            return ""

        cleaned = cls._progress_tag_pattern().sub(_take, text)
        return cleaned, notes

    @staticmethod
    def _strip_internal_tool_protocol(response: str) -> str:
        """Remove provider tool envelopes and raw JSON tool calls that must never become chat text."""
        cleaned = str(response or "")

        def _is_tool_payload(text: str) -> bool:
            """Check if text is JSON containing tool call structure."""
            text = text.strip()
            if not text:
                return True
            if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
                return False
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                return False
            if isinstance(obj, list):
                return len(obj) == 0 or all(isinstance(item, dict) for item in obj)
            if not isinstance(obj, dict):
                return False
            if "action" in obj and "params" in obj:
                return True
            if "name" in obj and "params" in obj:
                return True
            if "tool" in obj and "params" in obj:
                return True
            return False

        def _strip_fences(text: str) -> str:
            """Remove fenced JSON tool calls and known tool protocol blocks."""
            result = []
            i = 0
            while i < len(text):
                fence = re.search(r"```(\w*)\s*\n?", text[i:])
                if not fence:
                    result.append(text[i:])
                    break
                result.append(text[i:i + fence.start()])
                lang = fence.group(1).lower()
                content_start = i + fence.end()
                close = re.search(r"```", text[content_start:])
                if not close:
                    result.append(text[i + fence.start():])
                    break
                content = text[content_start:content_start + close.start()]
                fence_end = content_start + close.end()
                if lang in ("tool_use", "tool"):
                    i = fence_end
                elif lang in ("json", "") and _is_tool_payload(content):
                    i = fence_end
                else:
                    result.append(text[i + fence.start():fence_end])
                    i = fence_end
            return "".join(result)

        stripped = _strip_fences(cleaned)
        # XML tool tags — catch all variants
        stripped = re.sub(
            r"<(tool_use|tool_calls|tool_call|function_calls|function_call|invoke|invocation)>[\s\S]*?</\1>", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Some providers emit the canonical tool name directly as an XML
        # element (for example ``<web_search>...</web_search>``).  These are
        # transport envelopes, not user-facing prose, so remove the complete
        # block before a final response is streamed.
        stripped = re.sub(
            r"<(?:web_search|code_search|reading|creating|modifying|deleting|bash|http_client|git_ops|test_runner|planning|hive|browser|search|knowledge|reasoning|task|system|deep_research|shortcuts|terminal|memory)[^>]*>[\s\S]*?</(?:web_search|code_search|reading|creating|modifying|deleting|bash|http_client|git_ops|test_runner|planning|hive|browser|search|knowledge|reasoning|task|system|deep_research|shortcuts|terminal|memory)>",
            "",
            stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        stripped = re.sub(
            r"<invoke\s+name=\"\w+\">[\s\S]*?</invoke>", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Compact self-closing XML tool tags: <tool name="x" param="y"/>
        stripped = re.sub(
            r"<[a-z_]+(?:\s+[a-z_]+=\"[^\"]*\")*\s*/>", "", stripped,
            flags=re.DOTALL,
        )
        # Inline function-call syntax: word({...}) or tool.word({...})
        stripped = re.sub(
            r"\b(?:[a-z_]+\.)?[a-z_]+\(\{.*?\}\)", "", stripped,
            flags=re.DOTALL,
        )
        # Provider function-call format: <function=name>{json} or <function=name>...</function>
        stripped = re.sub(
            r"<function=\w+>(?:[\s\S]*?</function>)?", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # DeepSeek/OpenAI-compatible function envelopes. Strip the whole block
        # so protocol text can never become a chat response.
        stripped = re.sub(
            r"<function:\s*[\w.-]+>\s*[\s\S]*?(?:</function>|$)", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        stripped = re.sub(
            r"<function\s*>\s*[\s\S]*?</function>", "", stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Remove standalone JSON tool calls like {"action": "tool", "params": {...}}
        def _strip_standalone_json(text: str) -> str:
            result = []
            depth = 0
            start = -1
            for i, ch in enumerate(text):
                if ch == "{":
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start != -1:
                        candidate = text[start:i+1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict) and "action" in obj and "params" in obj:
                                result.append("")
                            elif isinstance(obj, dict) and "name" in obj and "params" in obj:
                                result.append("")
                            elif isinstance(obj, dict) and "tool" in obj and "params" in obj:
                                result.append("")
                            else:
                                result.append(candidate)
                        except json.JSONDecodeError:
                            result.append(candidate)
                        start = -1
                elif depth == 0:
                    result.append(ch)
            return "".join(result)
        stripped = _strip_standalone_json(stripped)
        return stripped

    @staticmethod
    def _contains_tool_protocol(response: str) -> bool:
        """Identify provider tool envelopes, but never ordinary explanatory prose."""
        return bool(re.search(
            r"<function(?:\s*(?:=|:)\s*[\w.-]+)?\s*>|<(?:tool_use|tool_calls|tool_call|invoke|web_search|code_search|reading|creating|modifying|deleting|bash|http_client|git_ops|test_runner|planning|hive|browser|search|knowledge|reasoning|task|system|deep_research|shortcuts|terminal|memory)\b",
            str(response or ""),
            flags=re.IGNORECASE,
        ))

    @staticmethod
    def _observation_is_failure(observation: Any) -> bool:
        """Only failed execution observations are eligible for a retry."""
        text = str(observation or "").strip().lower()
        return bool(re.match(r"^\[[^\]]+\]:\s*error\s*[—:-]", text))

    def _extract_dotted_tool_calls(self, text: str) -> List[ToolCall]:
        """Parse provider syntax such as ``file_ops.create({\"path\": ...})``."""
        calls: List[ToolCall] = []
        if not text:
            return calls
        known_tools = set(self.tool_registry.list_tools().keys()) | {
            "file_ops", "reading", "creating", "modifying", "deleting",
            "bash", "code_search", "web_search", "http_client", "git_ops", "test_runner"
        }
        decoder = json.JSONDecoder()
        pattern = re.compile(r"\b([a-zA-Z_][\w-]*)\.([a-zA-Z_][\w-]*)\s*\(")
        for match in pattern.finditer(text):
            tool_name, method = match.group(1), match.group(2)
            if tool_name not in known_tools:
                continue
            tail = text[match.end():].lstrip()
            try:
                params, consumed = decoder.raw_decode(tail)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(params, dict) or not tail[consumed:].lstrip().startswith(")"):
                continue
            if tool_name == "file_ops":
                params.setdefault(
                    "action",
                    ("write" if "content" in params else "mkdir") if method == "create" else method,
                )
            elif method not in {"run", "execute", "call", "invoke"}:
                params.setdefault("action", method)
            calls.append(ToolCall(tool_name, params))
        return calls

    def _extract_compact_xml_tool_calls(self, text: str) -> List[ToolCall]:
        """Parse compact model tool tags such as ``<reading path=\"x\" />``.

        Several OpenAI-compatible providers emit this concise form instead of
        JSON/DSML. Treating it as prose caused real actions to be silently lost.
        """
        calls: List[ToolCall] = []
        if not text or "<" not in text:
            return calls
        pattern = re.compile(
            r"<(?P<name>[a-zA-Z_][a-zA-Z0-9_-]*)\b(?P<attrs>[^>]*)"
            r"(?:/\s*>|>(?P<body>.*?)</(?P=name)\s*>)",
            re.DOTALL,
        )
        attr_pattern = re.compile(r"([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
        known_tools = set(self.tool_registry.list_tools().keys()) | {
            "file_ops", "reading", "creating", "modifying", "deleting",
            "bash", "code_search", "web_search", "http_client", "git_ops", "test_runner"
        }
        for match in pattern.finditer(text):
            name = match.group("name").strip()
            if name not in known_tools:
                continue
            params = {key: html.unescape(value) for key, _quote, value in attr_pattern.findall(match.group("attrs") or "")}
            body = html.unescape((match.group("body") or "").strip())
            if body and "content" not in params:
                params["content"] = body
            calls.append(ToolCall(name, params))
        return calls

    def _extract_action_fences(self, response: str) -> List[ToolCall]:
        """Recover explicit action blocks from models that ignore tool-call schemas.

        This fallback is invoked only for user requests already classified as
        requiring real tools, so ordinary code examples are never executed.
        """
        calls: List[ToolCall] = []
        pattern = re.compile(
            r"```(?:bash|sh|shell|powershell|ps1|cmd)\s*\n(.*?)```",
            re.IGNORECASE | re.DOTALL,
        )
        for block in pattern.findall(response)[:20]:
            command = block.strip()
            if not command or len(command) > 12000:
                continue
            read_match = re.fullmatch(r'(?:cat|type)\s+["\']([^"\']+)["\']', command, re.IGNORECASE)
            if read_match:
                calls.append(ToolCall("reading", {"path": read_match.group(1)}))
            else:
                calls.append(ToolCall("bash", {"command": command, "cwd": self.root}))
        return calls

    def _extract_explicit_run_commands(self, task_desc: str) -> List[ToolCall]:
        """Execute commands the user explicitly wrote after the word ``run``.

        This is deliberately narrow: it never invents a command and is used
        only after the task has already been classified as requiring tools.
        """
        pattern = re.compile(
            r"(?:from\s+(?P<where>[^.]{1,100}?)\s+)?run\s+(?P<command>.+?)"
            r"(?=\.\s+(?:then|after|next)\b|\.\s+(?:do not|don't)\b|$)",
            re.IGNORECASE | re.DOTALL,
        )
        calls: List[ToolCall] = []
        for match in pattern.finditer(task_desc):
            command = " ".join(match.group("command").strip().split())
            if not command or len(command) > 12000:
                continue
            where = (match.group("where") or "").strip().lower()
            if where in {"gui", "the gui", "gui directory", "the gui directory"}:
                command = f"cd gui && {command}"
            calls.append(ToolCall("bash", {"command": command, "cwd": self.root}))
        return calls[:20]

    def _extract_explicit_file_actions(self, task_desc: str) -> List[ToolCall]:
        """Recover safe, explicit file reads when a model omits tool protocol."""
        low = task_desc.lower()
        if not any(word in low for word in ("read", "inspect", "open", "check", "summarize", "review")):
            return []
        candidates = re.findall(
            r"(?<![\w:/.-])(?:[\w.-]+[\\/])*[\w.-]+\.[A-Za-z0-9]{1,8}(?![\w.-])",
            task_desc,
        )
        calls: List[ToolCall] = []
        seen = set()
        for path in candidates:
            normalized = path.strip("'\"`.,;:()[]{}")
            if not normalized or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            calls.append(ToolCall("reading", {"path": normalized}))
        return calls[:20]

    def _extract_dsml_tool_calls(self, text: str) -> List[ToolCall]:
        calls: List[ToolCall] = []
        if not text or "invoke name=" not in text:
            return calls

        invoke_pattern = re.compile(
            r"<[^>]*invoke\s+name=\"([^\"]+)\"[^>]*>(.*?)</[^>]*invoke>",
            re.IGNORECASE | re.DOTALL,
        )
        param_pattern = re.compile(
            r"<[^>]*parameter\s+name=\"([^\"]+)\"(?:\s+[^>]*)?>(.*?)</[^>]*parameter>",
            re.IGNORECASE | re.DOTALL,
        )

        for invoke_name, body in invoke_pattern.findall(text):
            params: Dict[str, Any] = {}
            for param_name, raw_value in param_pattern.findall(body):
                value = html.unescape(raw_value or "").strip()
                params[param_name] = self._coerce_dsml_value(value)
            calls.append(ToolCall(invoke_name.strip(), params))
        return calls

    def _coerce_dsml_value(self, value: str) -> Any:
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        if re.fullmatch(r"-?\d+", value.strip()):
            try:
                return int(value.strip())
            except Exception:
                return value
        if re.fullmatch(r"-?\d+\.\d+", value.strip()):
            try:
                return float(value.strip())
            except Exception:
                return value
        return value

    def _extract_raw_json_objects(self, text: str) -> List[Dict[str, Any]]:
        """Extract JSON objects without treating braces inside strings as structure."""
        results: List[Dict[str, Any]] = []
        decoder = json.JSONDecoder()
        index = 0
        while index < len(text):
            start = text.find("{", index)
            if start < 0:
                break
            try:
                parsed, consumed = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                index = start + 1
                continue
            if isinstance(parsed, dict):
                results.append(parsed)
            index = start + max(consumed, 1)
        return results

    def _robust_json_parse(self, text: str) -> Optional[Any]:
        try:
            return json.loads(text)
        except Exception:
            return None

    def _append_call(self, calls: List[ToolCall], data: Dict[str, Any]):
        action = data.get("action") or data.get("name")
        params = data.get("params", data.get("arguments"))
        if params is None:
            params = {k: v for k, v in data.items() if k not in {"action", "name", "call_id", "id"}}
        if isinstance(params, str):
            params = self._robust_json_parse(params)
        if not isinstance(params, dict):
            return
        if action:
            calls.append(ToolCall(action, params))

    # ─────────────────────────────────────────────────────────────────────────
    # CONTEXT COMPACTION
    # ─────────────────────────────────────────────────────────────────────────

    # Runtime control/context messages that are *history*, not standing instructions.
    # These are emitted during a run (tool results, self-correction, errors) and must be
    # compacted like any other history — otherwise the largest payloads grow unbounded.
    _TRANSIENT_SYSTEM_PREFIXES = (
        "[TOOL_RESULTS]", "[SELF_CORRECT", "[RUNTIME_ERROR]", "[TOOL_BLOCKED]",
        "[FINAL_RESPONSE]", "TOOL_ENFORCEMENT", "[CURRENT_PLAN]",
    )

    def _is_transient_system(self, msg: Dict[str, str]) -> bool:
        if msg.get("role") != "system":
            return False
        c = (msg.get("content", "") or "").lstrip()
        return c.startswith(self._TRANSIENT_SYSTEM_PREFIXES)

    def _compact_memory(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Context suppression that preserves instructions + task, compacts history.

        Classification:
          - PINNED (never compacted): ground-context system blocks (stable prompt,
            rules, workstyle, project docs, prompt files, memory, knowledge, codebase,
            tool schemas) and the FIRST user task message.
          - COMPACTABLE: transient runtime system messages (tool results, self-correct,
            runtime errors, tool-blocked, final-response, plan) PLUS all later
            user/assistant/tool turns.

        When the compactable portion exceeds the token budget (NEXUS_COMPACT_BUDGET,
        default 120k) or message count > COMPACT_KEEP, the OLDEST compactable messages
        are replaced by a single ordered summary while the most recent COMPACT_KEEP
        stay verbatim. Original relative order is preserved (no hoisting), so a tool
        result stays next to the assistant turn it answered.
        """
        if not messages:
            return messages

        pinned: List[Dict[str, str]] = []          # standing instructions
        compactable: List[Dict[str, str]] = []      # history that may be summarized
        first_user_pinned = False
        for i, m in enumerate(messages):
            role = m.get("role")
            if role == "system" and not self._is_transient_system(m):
                pinned.append(m)
            elif role == "user" and not first_user_pinned:
                # pin the original task verbatim
                pinned.append(m)
                first_user_pinned = True
            else:
                compactable.append(m)

        estimated_tokens = sum(len(str(m.get("content", ""))) // 4 for m in compactable)
        budget = int(os.environ.get("NEXUS_COMPACT_BUDGET", "120000")) or 120_000
        if len(compactable) <= self.COMPACT_KEEP and estimated_tokens < budget:
            return messages  # nothing to compact yet

        if len(compactable) <= self.COMPACT_KEEP:
            # few messages but over budget -> trim oversized individual messages instead
            if estimated_tokens >= budget:
                compactable = [
                    {**m, "content": (m.get("content", "")[:4000] if len(str(m.get("content", ""))) > 4000 else m.get("content", ""))}
                    for m in compactable
                ]
            return pinned + compactable

        keep = compactable[-self.COMPACT_KEEP:]
        old = compactable[:-self.COMPACT_KEEP]

        summary = self._summarize_compacted_messages(old)
        summary_msg = {"role": "system", "content": summary}
        # pinned instructions first, then the compaction summary, then the most recent
        # compactable messages IN ORIGINAL RELATIVE ORDER.
        return pinned + [summary_msg] + keep

    def _summarize_compacted_messages(self, messages: List[Dict[str, str]]) -> str:
        """Deterministic, fast structured compaction (no model call).

        Preserves: the user's goals, key decisions, tool results/evidence, and errors —
        so the agent keeps working from real context. The summary is tagged distinctly
        and replaces (not stacks on) any prior summary on the next compaction.
        """
        goals, progress, evidence, errors = [], [], [], []
        for msg in messages:
            r = msg.get("role")
            c = (msg.get("content", "") or "").strip()
            if not c:
                continue
            # strip transient prefixes so the summary reads cleanly
            if r == "user":
                goals.append(c[:500])
            elif r == "assistant":
                progress.append(c[:500])
            elif r == "tool":
                evidence.append(c[:600])
            # transient system msgs already preserved as pinned? no — they are compactable,
            # fold their substance into evidence so tool results survive compaction.
            elif r == "system":
                evidence.append(c[:400])
            if "error" in c.lower() or "failed" in c.lower():
                errors.append(c[:400])
        lines = ["[CONTEXT_COMPACTED] Condensed summary of earlier turns (most recent state retained verbatim):"]
        for g in goals[-6:]:
            lines.append(f"- Goal: {g}")
        for p in progress[-6:]:
            lines.append(f"- Progress: {p}")
        for e in evidence[-10:]:
            lines.append(f"- Evidence/tool-result: {e}")
        for e in errors[-4:]:
            lines.append(f"- Error noted: {e}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # MEMORY PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────────

    def save_memory(self):
        """Persist short-term memory to disk."""
        try:
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=2)
        except Exception as e:
            self.logger.error(f"save_memory failed: {e}")

    def load_memory(self, session_id: Optional[str] = None):
        """Load short-term memory from disk."""
        if session_id:
            self.session_id = session_id
            # keep the MemoryManager pointed at the same session, else its
            # _prefetch_session reads a stale/old session file.
            try:
                self.memory_manager.session_id = session_id
            except Exception:
                pass
            try:
                path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
                if not os.path.exists(path) and self.session_id == "default":
                    path = os.path.join(self.root, "logs", "session_memory.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        self.memory = json.load(f)
                else:
                    self.memory = []
            except Exception as e:
                self.logger.warning("load_memory: %s", e)
                self.memory = []

    def sync_memory(self):
        """High-performance sync — CLI/GUI cohesion."""
        try:
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            if not os.path.exists(path) and self.session_id == "default":
                path = os.path.join(self.root, "logs", "session_memory.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    disk_mem = json.load(f)
                    if disk_mem != self.memory:
                        self.memory = disk_mem
        except Exception:
            self.logger.warning("loop sync_memory: suppressed error", exc_info=True)
            pass

    def _write_session_bus(self, _messages=None):
        """Write session to session_bus for CLI/GUI/Gateway sync."""
        try:
            session_file = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(session_file), exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=2)
        except Exception:
            self.logger.warning("loop _write_session_bus: suppressed error", exc_info=True)
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # ABORT
    # ─────────────────────────────────────────────────────────────────────────

    def abort(self):
        """Signal the loop to stop after the current turn."""
        self._abort_flag.set()
        self.logger.info("[LOOP] Abort signaled.")

    @property
    def is_running(self) -> bool:
        guard = getattr(self, "_run_guard", None)
        return bool(guard and guard.locked())

    def reset(self):
        """Compatibility reset used by GUI/API before a fresh chat turn."""
        if self.is_running:
            return False
        self._abort_flag.clear()
        self._current_turn_id = ""
        self.active_agent = ""
        self.active_goal = ""
        return True
