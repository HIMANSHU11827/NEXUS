"""
NEXUS SOVEREIGN LOOP v11.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Full Architecture:
  ① GROUNDING   — ALL 8 parallel: Rules+RAG+Memory+Perms+Knowledge+Config+CodeIntel+Engine
  ② PLANNING    — 3 modes: none / checklist(☐1☐2☐3) / phased(☐Ph1→sub-goals)
  ③ INFERENCE   — DUAL STREAM: Answer NOW + Worker (Thinking ON/OFF, MoE router)
  ④ AUDITING    — 4 policies + 3 sandbox tiers + CommandRiskScorer
  ⑤ EXECUTION   — ALL PARALLEL: Terminal+Tools+Skills+Plugins+MCP+Web+Memory+Knowledge+Hive
  ⑥ VERIFICATION— ALL PARALLEL: Error scan+Tests+TODO+PhaseGate+Checkpoint
  ⑦ EVOLVE      — ALL PARALLEL: EvolutionLog+SelfImprove+GapForge+HiveScore+MemoryCrystallize

FAST PATH: Simple chat → 1 model call → stream instantly (no loop overhead)
MODELESS: No chat/agent/CEO modes — he IS everything, auto-detects
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio
import json
import logging
import os
import re
import time
import inspect
import uuid
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
    Union,
)

from permissions import PermissionMode, PermissionResult
from router import IntentRouter
from sandbox.risk import CommandRiskScorer
from sandbox.sandbox_manager import SovereignSandbox, SandboxTier
from evolution.tool_forge.scripts.engine import ToolForge
from evolution.skill_forge.scripts.forge import SkillForge
from evolution.memory_forge.scripts.forge import MemoryForge
from evolution.knowledge_forge.scripts.forge import KnowledgeForge
from evolution.logs import EvolutionLog
from evolution.self_improvement.scripts.engine import SelfImprovementEngine


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class SCAState(str, Enum):
    GROUNDING    = "grounding"     # Parallel: Rules+RAG+Memory+Perms+Knowledge+Config+CodeIntel+Engine
    PLANNING     = "planning"      # 3 modes: none / checklist / phased with sub-goals
    INFERENCE    = "inference"     # Dual stream: answer NOW + full worker (Thinking ON/OFF)
    AUDITING     = "auditing"      # Risk score + permission policy + sandbox tier routing
    EXECUTION    = "execution"     # ALL parallel: terminal+tools+skills+plugins+mcp+web+memory+knowledge+hive
    VERIFICATION = "verification"  # ALL parallel: error scan + tests + TODO + phase gate + checkpoint
    EVOLVE       = "evolve"        # ALL parallel: log+self-improve+gap forge+hive score+memory crystallize

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
        self.name    = name
        self.params  = params
        self.call_id = call_id or f"call_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "params": self.params, "call_id": self.call_id}


class HookRegistry:
    """Lifecycle hook system — fire callbacks at each state transition."""

    EVENTS = (
        "on_state_change",
        "pre_llm_call",
        "post_llm_call",
        "pre_tool_call",
        "post_tool_call",
        "on_turn_end",
        "on_fast_path",
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

class NexusLoop:
    # Turn limits
    MAX_TURNS           = 20
    MAX_CHAT_TURNS      = 3
    MAX_RETRIES_PER_PHASE = 3

    # Context compaction
    COMPACT_THRESHOLD   = 10
    COMPACT_KEEP        = 4

    # Fast-path keywords — if input is simple question, skip full loop
    _FAST_PATH_SIGNALS  = (
        "what is", "who is", "how does", "explain", "tell me", "define",
        "what are", "can you", "describe", "what's", "meaning of",
    )

    def __init__(self, root_dir: Optional[str] = None):
        from kernel import get_nexus_kernel
        self.kernel      = get_nexus_kernel(root_dir=root_dir)
        self.root        = self.kernel.root
        self.logger      = logging.getLogger("nexus.loop.v11")

        # State
        self.session_id        = "default"
        self._current_turn_id  = ""
        self.state             = SCAState.GROUNDING
        self.hooks             = HookRegistry()
        self.memory: List[Dict[str, str]] = []
        self._abort_flag       = asyncio.Event()

        # Config
        self.policy            = PermissionPolicy.AI_DECIDE
        self.sandbox_tier      = SandboxTier.NORMAL
        self.thinking_mode     = True
        self.checklist: Set[str] = {"view_file", "glob", "grep", "list_dir", "test_select", "tester"}
        self.operator_bypass_mode = os.environ.get("NEXUS_SOVEREIGN", "false").lower() == "true"

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

        # Misc
        self.additional_dirs: List[str] = []
        self._nexus_profile_cache: Dict[str, str] = {}
        self._session_context_sent: Set[str] = set()

        # Subsystems (lazy)
        self.risk_scorer = CommandRiskScorer()
        self.sandbox     = SovereignSandbox(self.root)

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
    def discoverer(self):      return self.kernel.indexer
    @property
    def tool_registry(self):   return self.kernel.tools
    @property
    def rag(self):             return self.kernel.rag

    @property
    def laws(self):
        from safety.laws import SafetyLaws
        return self.kernel._get_or_init("laws", lambda: SafetyLaws(self.root))

    @property
    def permissions(self):
        from permissions import PermissionSystem
        return self.kernel._get_or_init("permissions", PermissionSystem)

    @property
    def architect(self):
        from orchestrators.architect import NexusArchitect
        return self.kernel._get_or_init("architect", lambda: NexusArchitect(self.root))

    @property
    def persistence(self):
        from context.persistence import NexusFilePersistence
        return NexusFilePersistence(self.root)

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

    # ─────────────────────────────────────────────────────────────────────────
    # ENTRY POINTS
    # ─────────────────────────────────────────────────────────────────────────

    async def run(self, task_desc: str, voice_mode: bool = False) -> str:
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
        model:    Optional[str] = None,
        voice_mode: bool = False,
        turn_id:  str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main entry point — streaming async generator.
        Yields dicts: {type: status|content|plan|tools_discovered|observations|fast_answer}
        """
        self._abort_flag.clear()
        self._current_turn_id = turn_id or uuid.uuid4().hex[:8]

        # Provider / model overrides
        if provider:
            try: self.brain.set_override(provider)
            except Exception: pass
        if model:
            try:
                p = getattr(self.brain.base_router, "provider", None)
                if p and hasattr(p, "model"):
                    p.model = model
            except Exception: pass

        # ── FAST PATH GATE ─────────────────────────────────────────────────
        # If input looks like a simple question, answer immediately without
        # going through the full loop. Simultaneously start the full loop
        # in background to catch up if needed.
        is_fast = self._is_fast_path(task_desc)

        if is_fast:
            async for chunk in self._fast_path(task_desc, voice_mode=voice_mode):
                yield chunk
            return

        # ── FULL SOVEREIGN LOOP ────────────────────────────────────────────
        async for chunk in self._full_loop(task_desc, voice_mode=voice_mode):
            yield chunk

    # ─────────────────────────────────────────────────────────────────────────
    # FAST PATH — Simple chat: 1 call, stream now, light log
    # ─────────────────────────────────────────────────────────────────────────

    def _is_fast_path(self, task_desc: str) -> bool:
        """Detect if input is simple Q&A that doesn't need the full loop."""
        low = task_desc.strip().lower()
        # Very short inputs are usually chat
        if len(low.split()) <= 6:
            return True
        for sig in self._FAST_PATH_SIGNALS:
            if low.startswith(sig):
                return True
        # No tool-like keywords — treat as chat
        tool_signals = ("implement", "build", "create", "fix", "refactor", "write code",
                        "install", "run", "execute", "deploy", "debug", "test", "make", "add")
        for sig in tool_signals:
            if sig in low:
                return False
        return True

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

    def _load_nexus_profile(self, detail: str = "rules") -> str:
        """Load a compact internal profile from docs/NEXUS.md without exposing the whole file."""
        cached = self._nexus_profile_cache.get(detail)
        if cached is not None:
            return cached

        nexus_path = os.path.join(self.root, "docs", "NEXUS.md")
        if not os.path.exists(nexus_path):
            return ""

        try:
            with open(nexus_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
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

    async def _fast_path(self, task_desc: str, voice_mode: bool = False) -> AsyncGenerator[Dict[str, Any], None]:
        """1 model call → stream answer to user immediately."""
        await self.hooks.trigger("on_fast_path", task_desc)
        yield {"type": "status", "data": "\n[fast-path]"}

        # Keep simple chat lightweight. Identity context is only added when the user asks for it.
        rules = await asyncio.to_thread(self._load_progressive_rules)
        messages = [
            {"role": "system", "content": rules},
        ]
        identity_context = await asyncio.to_thread(self._identity_context, task_desc)
        if identity_context:
            messages.append({"role": "system", "content": identity_context})
        messages.append({"role": "user", "content": task_desc})

        # Stream A fires immediately
        response = await asyncio.to_thread(self._call_model, messages)
        if response:
            yield {"type": "fast_answer", "data": response}
            yield {"type": "content",     "data": response}

        if not voice_mode:
            # Update persistent memory
            self.memory.append({"role": "user", "content": task_desc})
            self.memory.append({"role": "assistant", "content": response or ""})

        # Light log — no heavy evolve
        try:
            await asyncio.to_thread(
                self.evolution_log.win, "loop", "fast_path",
                f"Fast-path answered: {task_desc[:80]}", 0.0, {}
            )
        except Exception:
            pass

        if not voice_mode:
            # Session write
            await asyncio.to_thread(self._write_session_bus, self.memory)

        yield {"type": "status", "data": "\n[done]"}

    # ─────────────────────────────────────────────────────────────────────────
    # FULL SOVEREIGN LOOP — 7 SCA States
    # ─────────────────────────────────────────────────────────────────────────

    async def _full_loop(self, task_desc: str, voice_mode: bool = False) -> AsyncGenerator[Dict[str, Any], None]:
        messages: List[Dict[str, str]] = []
        tool_calls: List[ToolCall] = []
        self.state = SCAState.GROUNDING
        turn = 0
        consecutive_chat_turns = 0

        while turn < self.MAX_TURNS:
            if self._abort_flag.is_set():
                yield {"type": "status", "data": "\n[aborted]"}
                return

            await self.hooks.trigger("on_state_change", self.state, self)

            # ── ① GROUNDING ─────────────────────────────────────────────────
            if self.state == SCAState.GROUNDING:
                yield {"type": "status", "data": "\n[grounding]"}
                messages = await self._ground_context(task_desc)
                self.state = SCAState.PLANNING

            # ── ② PLANNING ──────────────────────────────────────────────────
            elif self.state == SCAState.PLANNING:
                yield {"type": "status", "data": "\n[planning]"}
                plan = await self._plan_task(task_desc, messages)
                if plan:
                    yield {"type": "plan", "data": plan}
                    messages.append({"role": "system", "content": f"[PLAN_ROADMAP]:\n{plan}"})
                self.state = SCAState.INFERENCE

            # ── ③ INFERENCE — DUAL STREAM ───────────────────────────────────
            elif self.state == SCAState.INFERENCE:
                turn += 1
                yield {"type": "status", "data": f"\n[inference {turn}]"}

                await self.hooks.trigger("pre_llm_call", messages)

                # Dual stream: Stream A (fast answer) + Stream B (worker) in parallel
                fast_task   = asyncio.create_task(self._stream_a_instant(task_desc, messages))
                worker_task = asyncio.create_task(asyncio.to_thread(self._call_model, messages))

                # Stream A — instant answer to user
                fast_response = await fast_task
                if fast_response and turn == 1:
                    yield {"type": "fast_answer", "data": fast_response}

                # Stream B — full worker response (with tools)
                response = await worker_task
                await self.hooks.trigger("post_llm_call", response)

                if not response:
                    self.state = SCAState.EVOLVE
                    continue

                yield {"type": "content", "data": response}
                messages.append({"role": "assistant", "content": response})

                # Track persistent memory (user/assistant only)
                if not voice_mode:
                    if turn == 1:
                        self.memory.append({"role": "user", "content": task_desc})
                    self.memory.append({"role": "assistant", "content": response})

                tool_calls = self._extract_tool_calls(response)
                if not tool_calls:
                    if "TASK_COMPLETE" in response:
                        self.state = SCAState.EVOLVE
                    else:
                        consecutive_chat_turns += 1
                        if consecutive_chat_turns >= self.MAX_CHAT_TURNS:
                            yield {"type": "status", "data": f"\n[chat limit] {self.MAX_CHAT_TURNS} turns"}
                            messages.append({"role": "system", "content": "[CHAT_LIMIT] No tool calls. End with TASK_COMPLETE."})
                            self.state = SCAState.EVOLVE
                        else:
                            self.state = SCAState.INFERENCE
                    continue

                consecutive_chat_turns = 0
                yield {"type": "tools_discovered", "tool_calls": [tc.to_dict() for tc in tool_calls]}
                self.state = SCAState.AUDITING

            # ── ④ AUDITING ───────────────────────────────────────────────────
            elif self.state == SCAState.AUDITING:
                yield {"type": "status", "data": "\n[auditing]"}
                approved = await self._audit_and_approve(tool_calls)
                if approved:
                    self.state = SCAState.EXECUTION
                else:
                    yield {"type": "status", "data": "\n[blocked] auditing rejected"}
                    self.state = SCAState.EVOLVE

            # ── ⑤ EXECUTION — ALL PARALLEL ──────────────────────────────────
            elif self.state == SCAState.EXECUTION:
                yield {"type": "status", "data": "\n[executing]"}
                await self.hooks.trigger("pre_tool_call", tool_calls)

                observations = await self._execute_tools(tool_calls)
                yield {"type": "observations", "data": observations}

                await self.hooks.trigger("post_tool_call", tool_calls, observations)
                messages.append({"role": "system", "content": "\n".join(observations)})

                # Log to mission replay
                await asyncio.to_thread(self._log_mission_replay, tool_calls, observations)

                self.state = SCAState.VERIFICATION

            # ── ⑥ VERIFICATION — ALL PARALLEL ───────────────────────────────
            elif self.state == SCAState.VERIFICATION:
                yield {"type": "status", "data": "\n[verifying]"}

                # Run all verification tasks in parallel
                verify_results = await self._verify_all_parallel(messages, tool_calls)
                success  = verify_results["success"]
                vaccine  = verify_results["vaccine"]
                todo_str = verify_results["todo"]

                # Save checkpoint
                await asyncio.to_thread(self._save_checkpoint, messages, task_desc, turn)

                if todo_str:
                    yield {"type": "plan", "data": todo_str}

                if not success and vaccine:
                    phase_key = f"phase_{self.current_plan.get('current_phase', 0) if self.current_plan else 'main'}"
                    self._retry_counts[phase_key] = self._retry_counts.get(phase_key, 0) + 1
                    retries = self._retry_counts[phase_key]
                    yield {"type": "status", "data": f"\n[fail] retry {retries}/{self.MAX_RETRIES_PER_PHASE}"}

                    if retries >= self.MAX_RETRIES_PER_PHASE:
                        yield {"type": "status", "data": "\n[exhausted] max retries"}
                        try:
                            await asyncio.to_thread(
                                self.evolution_log.lose, "loop", "verification",
                                f"Phase {phase_key} failed after {retries} retries", 0.0, {}
                            )
                        except Exception:
                            pass
                        # Log to failure memory
                        try:
                            await asyncio.to_thread(
                                self.failure_memory.record,
                                {"task": task_desc, "vaccine": vaccine, "phase": phase_key}
                            )
                        except Exception:
                            pass
                        messages.append({"role": "system", "content": "[SELF_CORRECT] Max retries reached. Escalate or skip."})
                        self.state = SCAState.EVOLVE
                    else:
                        messages.append({"role": "system", "content": f"[SELF_CORRECT] Attempt {retries}/{self.MAX_RETRIES_PER_PHASE}.\n{vaccine}\nFix and retry."})
                        self.state = SCAState.INFERENCE
                else:
                    # Success — advance plan
                    phase_key = f"phase_{self.current_plan.get('current_phase', 0) if self.current_plan else 'main'}"
                    self._retry_counts.pop(phase_key, None)
                    messages = self._compact_memory(messages)

                    advanced = self._advance_plan(messages)
                    if advanced:
                        yield {"type": "plan", "data": self._render_todo_list()}
                        if self.current_plan and self.current_plan.get("_complete"):
                            self.state = SCAState.EVOLVE
                        else:
                            # Fill gaps inline then continue
                            context = "\n".join([m.get("content", "")[:200] for m in messages[-6:]])
                            await self._fill_gap_during_session(context)
                            self.state = SCAState.INFERENCE
                    else:
                        context = "\n".join([m.get("content", "")[:200] for m in messages[-6:]])
                        await self._fill_gap_during_session(context)
                        self.state = SCAState.INFERENCE

            # ── ⑦ EVOLVE — ALL PARALLEL ─────────────────────────────────────
            elif self.state == SCAState.EVOLVE:
                yield {"type": "status", "data": "\n[evolve]"}
                await self.hooks.trigger("on_evolve", messages)
                await self._finalize_session(task_desc, messages)
                break

        yield {"type": "status", "data": "\n[done]"}

    # ─────────────────────────────────────────────────────────────────────────
    # ① GROUNDING — ALL 8 PARALLEL
    # ─────────────────────────────────────────────────────────────────────────

    async def _ground_context(self, task_desc: str) -> List[Dict[str, str]]:
        """Load all context in parallel: rules + RAG + memory + perms + knowledge + config + code intel + engine."""
        tasks = [
            asyncio.to_thread(self._load_progressive_rules),           # 0: docs/NEXUS.md rules
            asyncio.to_thread(self.rag.retrieve_as_text, task_desc, top_k=3),  # 1: RAG
            asyncio.to_thread(self._load_session_memory),               # 2: Memory sync
            asyncio.to_thread(self._init_permissions),                  # 3: Permissions
            asyncio.to_thread(self._load_knowledge_context, task_desc), # 4: Knowledge atlas
            asyncio.to_thread(self._load_config_context),               # 5: Config
            asyncio.to_thread(self._load_code_intel, task_desc),        # 6: Code intel / repo map
            asyncio.to_thread(self._check_compiler_status),             # 7: Engine check
            asyncio.to_thread(self._load_project_docs),                  # 8: README/HIVE/manifest
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        system_rules     = results[0] if not isinstance(results[0], Exception) else "You are NEXUS AI, a sovereign engineering agent."
        rag_context      = results[1] if not isinstance(results[1], Exception) else ""
        memory_context   = results[2] if not isinstance(results[2], Exception) else ""
        # results[3] = permissions init (side effect, no return value needed)
        knowledge_ctx    = results[4] if not isinstance(results[4], Exception) else ""
        # results[5] = config (cached, side effect)
        code_intel_ctx   = results[6] if not isinstance(results[6], Exception) else ""
        project_docs_ctx = results[8] if not isinstance(results[8], Exception) else ""

        workstyle_ctx = await asyncio.to_thread(self._workstyle_context, task_desc)

        # Build tool descriptions
        tools_desc = self._load_tool_descriptions()

        messages = [{"role": "system", "content": system_rules}]

        if workstyle_ctx:
            messages.append({"role": "system", "content": workstyle_ctx})

        if tools_desc:
            messages.append({"role": "system", "content": tools_desc})

        if rag_context and "No relevant" not in rag_context:
            messages.append({"role": "system", "content": f"[GROUNDING_MEMORIES]:\n{rag_context}"})

        if memory_context:
            messages.append({"role": "system", "content": f"[SESSION_MEMORY]:\n{memory_context}"})

        if knowledge_ctx:
            messages.append({"role": "system", "content": f"[KNOWLEDGE_CONTEXT]:\n{knowledge_ctx}"})

        if code_intel_ctx:
            messages.append({"role": "system", "content": f"[CODEBASE_CONTEXT]:\n{code_intel_ctx}"})

        if project_docs_ctx:
            messages.append({"role": "system", "content": f"[PROJECT_DOCS]:\n{project_docs_ctx}"})

        messages.append({"role": "system", "content": "When the task is fully complete, end your response with TASK_COMPLETE."})
        messages.append({"role": "user", "content": ""})  # placeholder, will be set in inference

        # Inject task
        messages[-1] = {"role": "user", "content": task_desc}

        return messages

    def _load_session_memory(self) -> str:
        """Load session memory from disk."""
        try:
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            if not os.path.exists(path):
                path = os.path.join(self.root, "logs", "session_memory.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        # summarize last 3 turns
                        lines = []
                        for m in data[-6:]:
                            role = m.get("role", "")
                            content = m.get("content", "")
                            if role in ("user", "assistant"):
                                if "[VOICE_MODE]:" in content:
                                    if "\n\n[VOICE_MODE]:" in content:
                                        content = content.split("\n\n[VOICE_MODE]:")[0]
                                    else:
                                        content = content.split("[VOICE_MODE]:")[0]
                                content = content.strip()[:200]
                                lines.append(f"{role.upper()}: {content}")
                        return "\n".join(lines)
        except Exception:
            pass
        return ""

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
            pass

    def _load_knowledge_context(self, task_desc: str) -> str:
        """Query knowledge atlas for task-relevant knowledge."""
        try:
            atlas_path = os.path.join(self.root, "knowledge", "_nexus_logic_index.db")
            if not os.path.exists(atlas_path):
                return ""
            # Use RAG engine to query knowledge
            result = self.rag.retrieve_as_text(task_desc, top_k=2)
            return result if result and "No relevant" not in result else ""
        except Exception:
            return ""

    def _load_config_context(self) -> str:
        """Load config — cached, just ensure settings are readable."""
        try:
            cfg_path = os.path.join(self.root, "config", "settings.yml")
            if os.path.exists(cfg_path):
                return ""  # Config already loaded by kernel
        except Exception:
            pass
        return ""

    def _load_code_intel(self, task_desc: str) -> str:
        """Load code intelligence: repo map + symbol graph snippet."""
        try:
            # Try code graph for relevant files
            graph_path = os.path.join(self.root, "workspace", "code_graph.json")
            if os.path.exists(graph_path):
                # Return a brief summary — not the full 2.6MB graph
                return f"[CODE_GRAPH] workspace/code_graph.json available ({os.path.getsize(graph_path)//1024}KB)"
        except Exception:
            pass
        return ""

    def _load_project_docs(self) -> str:
        """Load project documentation files (README, HIVE, manifest)."""
        parts = []
        doc_files = [
            ("README", os.path.join(self.root, "docs", "README.md")),
            ("HIVE", os.path.join(self.root, "docs", "HIVE.md")),
            ("MANIFEST", os.path.join(self.root, ".nexus", "manifest.json")),
        ]
        for label, path in doc_files:
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read().strip()[:600]
                        if content:
                            parts.append(f"[{label}]:\n{content}")
            except Exception:
                pass
        return "\n\n".join(parts)

    def _load_progressive_rules(self) -> str:
        """Load base NEXUS operating rules without injecting the whole NEXUS profile every turn."""
        return (
            "You are NEXUS, a sovereign AI engineering loop. "
            "You are MODELESS — you handle chat, tasks, coding, research, and everything else without switching modes. "
            "Use docs/NEXUS.md as hidden internal guidance, not as content to recite. "
            "For normal conversation, greet naturally and answer directly. "
            "Never dump, summarize at length, or quote docs/NEXUS.md unless the user explicitly asks to view or quote it."
        )

    def _check_compiler_status(self):
        """Check llama.cpp engine — compile if missing."""
        try:
            from utils.engine_manager import STATUS_PATH
            if not os.path.exists(STATUS_PATH):
                from utils.engine_compiler import compile_llama_cpp
                compile_llama_cpp()
        except ImportError:
            # Engine utils not available — skip compiler check
            pass
        except Exception:
            pass

    def _load_tool_descriptions(self) -> str:
        """Build tool usage instructions for the model."""
        try:
            tools = self.kernel.tools.list_tools()
            lines = [
                "You have these tools. To call one, output a JSON object with \"action\": \"<tool>\" and \"params\": {...}:",
                "",
            ]
            for name, info in tools.items():
                desc = info.get("description", "").strip()
                lines.append(f"  {name}: {desc}" if desc else f"  {name}")
            lines.append("")
            lines.append('Example: {"action": "bash", "params": {"command": "ls"}}')
            lines.append("You can call multiple tools per response.")
            return "\n".join(lines)
        except Exception:
            return 'Tools available. Use {"action": "<name>", "params": {...}} to call them.'

    # ─────────────────────────────────────────────────────────────────────────
    # ② PLANNING — 3 modes
    # ─────────────────────────────────────────────────────────────────────────

    async def _plan_task(self, task_desc: str, messages: List[Dict[str, str]]) -> Optional[str]:
        """Ask model to pick plan type: none / checklist / phased."""
        self.current_plan = None
        self.current_phase = 0
        self._retry_counts.clear()

        tools_info = ""
        try:
            tools = self.kernel.tools.list_tools()
            tools_info = "\n".join(f"- {n}: {i.get('description','')[:80]}" for n, i in tools.items())
        except Exception:
            tools_info = "(tools unavailable)"

        prompt = f"""[PLAN_DECISION]
Task: {task_desc}

Available tools:
{tools_info}

Decide if this task needs a plan:
- "none": simple direct answer or small task, no plan needed
- "checklist": sequential steps 1,2,3,4 — for medium tasks
- "phased": multiple phases each with sub-goals, verified before advancing — for large/complex tasks

Respond with ONLY valid JSON:
{{"type": "none"}}
{{"type": "checklist", "steps": ["step 1", "step 2", "step 3"]}}
{{"type": "phased", "phases": [{{"name": "Phase 1", "goal": "...", "sub_goals": ["1.1 ...", "1.2 ..."]}}]}}
"""
        try:
            result = await asyncio.to_thread(self._call_model_for_prompt, prompt)
            if not result:
                return None
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1].rsplit("\n", 1)[0]
            data = json.loads(result)
            ptype = data.get("type", "none")

            if ptype == "none":
                return None
            if ptype == "checklist":
                steps = data.get("steps", ["Analyze", "Execute", "Verify"])
                self.current_plan = {"type": "checklist", "steps": steps, "current_step": 0}
                return self._render_todo_list()
            if ptype == "phased":
                phases = data.get("phases", [])
                self.current_plan = {"type": "phased", "phases": phases, "current_phase": 0}
                return self._render_todo_list()
        except Exception:
            pass
        return None

    def _render_todo_list(self) -> str:
        """Render live TODO list with ☑/☐ markers."""
        if not self.current_plan:
            return ""

        ptype = self.current_plan.get("type")

        if ptype == "checklist":
            steps = self.current_plan["steps"]
            cs    = self.current_plan.get("current_step", 0)
            lines = ["[TODO LIST]"]
            for i, s in enumerate(steps):
                mark = "[x]" if i < cs else "[ ]"
                arrow = " ←" if i == cs else ""
                lines.append(f"  {mark} {s}{arrow}")
            return "\n".join(lines)

        if ptype == "phased":
            phases = self.current_plan["phases"]
            cp     = self.current_plan.get("current_phase", 0)
            lines  = ["[TODO LIST]"]
            for i, ph in enumerate(phases):
                done  = i < cp
                mark  = "[x]" if done else "[ ]"
                arrow = " ← current" if i == cp else ""
                lines.append(f"  {mark} Phase {i+1}: {ph.get('name','')} — {ph.get('goal','')}{arrow}")
                for sg in ph.get("sub_goals", []):
                    sg_mark = "[x]" if done else "[ ]"
                    lines.append(f"    {sg_mark} {sg}")
            return "\n".join(lines)

        return ""

    def _advance_plan(self, messages: List[Dict[str, str]]) -> bool:
        """Advance checklist step or phased phase. Returns True if advanced."""
        if not self.current_plan:
            return False

        ptype = self.current_plan.get("type")

        if ptype == "checklist":
            cs    = self.current_plan.get("current_step", 0)
            steps = self.current_plan["steps"]
            if cs < len(steps) - 1:
                self.current_plan["current_step"] = cs + 1
                todo = self._render_todo_list()
                messages.append({"role": "system", "content": f"[STEP_COMPLETE] Step {cs+1} done.\n{todo}\nNext: {steps[cs+1]}"})
                return True
            else:
                self.current_plan["_complete"] = True
                messages.append({"role": "system", "content": f"[ALL_STEPS_DONE]\n{self._render_todo_list()}\nAll steps complete. End with TASK_COMPLETE."})
                return True

        if ptype == "phased":
            phases = self.current_plan["phases"]
            cp     = self.current_plan.get("current_phase", 0)
            if cp < len(phases) - 1:
                self.current_plan["current_phase"] = cp + 1
                next_ph = phases[cp + 1]
                todo    = self._render_todo_list()
                messages.append({"role": "system", "content": f"[PHASE_COMPLETE] Phase {cp+1} passed.\n{todo}\nNext: {next_ph.get('name','')} — {next_ph.get('goal','')}"})
                return True
            else:
                self.current_plan["_complete"] = True
                messages.append({"role": "system", "content": f"[ALL_PHASES_DONE]\n{self._render_todo_list()}\nAll phases done. End with TASK_COMPLETE."})
                return True

        return False

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
            return await asyncio.to_thread(self._call_model, fast_messages)
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # ④ AUDITING — Risk + Permissions + Sandbox Tier
    # ─────────────────────────────────────────────────────────────────────────

    async def _audit_and_approve(self, tool_calls: List[ToolCall]) -> bool:
        """Check permissions for all tool calls based on current policy."""
        if self.operator_bypass_mode:
            return True

        # Sync policy to core permissions system
        self._init_permissions()

        for tc in tool_calls:
            try:
                result = self.permissions.check(tc.name, str(tc.params))
                if not result.granted:
                    if result.prompt:
                        user_resp = await asyncio.to_thread(input, f"{result.prompt} ")
                        if user_resp.strip().lower() in ("y", "yes"):
                            try: self.permissions.pre_authorize(str(tc.params))
                            except Exception: pass
                            continue
                    return False
            except Exception:
                pass
        return True

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
        for tc in tool_calls:
            tc_sig = (tc.name, json.dumps(tc.params, sort_keys=True))
            if tc_sig == getattr(self, "_last_tool_signature", None):
                repeated_calls.append(tc.name)
            self._last_tool_signature = tc_sig

        for tc in tool_calls:
            tool = self.tool_registry.get(tc.name)
            if tool and tool.is_read_only(tc.params):
                read_calls.append(tc)
            else:
                write_calls.append(tc)

        observations: List[str] = []

        if repeated_calls:
            observations.append(f"[REPETITION_GUARD] Tool(s) already executed this turn: {', '.join(repeated_calls)}. Use the prior result above.")

        # ── Parallel reads ──
        if read_calls:
            tasks   = [self._run_tool(tc) for tc in read_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for tc, res in zip(read_calls, results):
                if isinstance(res, Exception):
                    observations.append(f"[{tc.name}]: Error — {res}")
                    await self._handle_tool_failure(tc, res)
                else:
                    observations.append(f"[{tc.name}]: {res}")

        # ── Sequential writes ──
        for tc in write_calls:
            try:
                res = await self._run_tool(tc)
                observations.append(f"[{tc.name}]: {res}")
            except Exception as e:
                observations.append(f"[{tc.name}]: Error — {e}")
                await self._handle_tool_failure(tc, e)

        return observations

    async def _run_tool(self, call: ToolCall) -> str:
        """Resolve and execute a single tool call."""
        # Auto-discover if not registered
        tool = self.tool_registry.get(call.name)
        if tool is None:
            self.logger.info(f"[AUTO-DISCOVER] '{call.name}' not in registry — scanning...")
            discovered = self._discover_and_register_tool(call.name)
            if discovered is None:
                available = list(self.tool_registry.list_tools().keys())
                return f"Error: Tool '{call.name}' not found. Available: {available}"

        # Terminal/bash → SovereignSandbox with dynamic tier
        if call.name in ("bash", "run_command", "terminal", "shell"):
            cmd = (
                call.params.get("CommandLine") or
                call.params.get("cmd") or
                call.params.get("command") or ""
            )
            assessment = self.risk_scorer.assess(cmd)
            self.sandbox.tier = self.sandbox_tier
            return await asyncio.to_thread(self.sandbox.execute, cmd)

        res = await self.tool_registry.execute(call.name, **call.params)
        from tools.nexus_tools.base_tool import ToolResult
        if isinstance(res, ToolResult):
            if res.success:
                return res.output
            return f"Error: {res.error}"
        return str(res)

    def _discover_and_register_tool(self, name: str):
        """Auto-discover a tool from tools/<name>/ directory and register it."""
        import importlib.util

        # Check tools/
        tool_dir = os.path.join(self.root, "tools", name)
        if os.path.isdir(tool_dir):
            scripts_dir = os.path.join(tool_dir, "scripts")
            if os.path.isdir(scripts_dir):
                from tools.nexus_tools.base_tool import BaseTool
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
                                    entry = ToolEntry(name=name, schema={}, instance=instance)
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
            asyncio.to_thread(self._render_todo_list), # TODO update
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        verify_result = results[0] if not isinstance(results[0], Exception) else (True, None)
        # results[1] = test result (currently informational)
        todo_str      = results[2] if not isinstance(results[2], Exception) else ""

        success, vaccine = verify_result if isinstance(verify_result, tuple) else (True, None)
        return {"success": success, "vaccine": vaccine, "todo": todo_str}

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
                pass
            return False, vaccine

        return True, None

    async def _run_targeted_tests(self, tool_calls: List[ToolCall]) -> Optional[str]:
        """Select and run targeted tests based on modified files."""
        try:
            git_tool = self.tool_registry.get("git")
            if not git_tool:
                return None
            diff = await asyncio.to_thread(git_tool.execute, command="diff", name_only=True)
            if not diff or isinstance(diff, str) and "error" in diff.lower():
                return None
            from optimization.test_selection import TestSelector
            ts           = TestSelector(self.root)
            changed      = [f.strip() for f in diff.split("\n") if f.strip()]
            selected     = ts.select_tests(changed)
            if not selected:
                return None
            tester_tool  = self.tool_registry.get("tester")
            if tester_tool:
                res = await asyncio.to_thread(tester_tool.execute, command="run", tests=selected)
                return res
        except Exception as e:
            self.logger.debug(f"[VERIFY] Targeted tests failed: {e}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # ⑦ EVOLVE — ALL PARALLEL
    # ─────────────────────────────────────────────────────────────────────────

    async def _finalize_session(self, task_desc: str, messages: List[Dict[str, str]]):
        """Run all 5 evolution steps in parallel."""
        last_resp = ""
        for m in reversed(messages):
            if m["role"] == "assistant":
                last_resp = m["content"]
                break

        success = "TASK_COMPLETE" in last_resp or "error" not in last_resp.lower()

        # Fire all 5 evolve tasks in parallel
        evolve_tasks = [
            self._evolve_log(success, task_desc),          # 1: EvolutionLog
            self._evolve_self_improve(messages),           # 2: SelfImprovementEngine
            self._evolve_gap_forge(),                      # 3: GapForge (retry gaps)
            self._evolve_hive_feedback(messages),          # 4: Hive persona scores
            self._evolve_memory_crystallize(messages),     # 5: Memory crystallize
        ]
        await asyncio.gather(*evolve_tasks, return_exceptions=True)

        # Write session bus
        await asyncio.to_thread(self._write_session_bus)

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
            pass

    async def _evolve_self_improve(self, messages: List[Dict[str, str]]):
        """Step 2: SelfImprovementEngine — analyze session, extract top 3 actions."""
        try:
            se     = SelfImprovementEngine(self.root)
            record = await asyncio.to_thread(se.analyze_session, messages)
            if record and record.actions:
                for action in record.actions[:3]:
                    await asyncio.to_thread(self.evolution_log.improvement, action)
        except Exception:
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
                pass
        self._gaps_found.clear()

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
            pass

        # Always save + sync memory
        self.save_memory()

    # ─────────────────────────────────────────────────────────────────────────
    # GAP DETECTION & FORGE
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_evolution_gaps(self, tool_calls, observations):
        """Hook: post_tool_call — detect gaps from observations."""
        pass  # Inline gap detection happens in _fill_gap_during_session

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
            pass

    async def _fill_gap(self, gap: Dict[str, Any]):
        """Execute a single gap fill immediately."""
        gtype = gap.get("type", "")
        name  = gap.get("name", "unknown")
        try:
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
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # CHECKPOINT
    # ─────────────────────────────────────────────────────────────────────────

    def _save_checkpoint(self, messages: List[Dict], task_desc: str, turn: int):
        """Save checkpoint to disk — resume after crash."""
        try:
            ckpt_dir = os.path.join(self.root, "logs", "checkpoints")
            os.makedirs(ckpt_dir, exist_ok=True)
            ckpt_path = os.path.join(ckpt_dir, f"{self.session_id}.json")
            with open(ckpt_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": self.session_id,
                    "task_desc":  task_desc,
                    "turn":       turn,
                    "state":      self.state.value,
                    "messages":   messages[-20:],  # Keep last 20 for resume
                    "plan":       self.current_plan,
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
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # MODEL CALLS
    # ─────────────────────────────────────────────────────────────────────────

    def _call_model(self, messages: List[Dict]) -> str:
        """Call model — stream then fallback to generate."""
        full = ""
        try:
            for chunk in self.brain.stream_generate(messages=messages):
                full += chunk
            if not full.strip():
                fallback = self.brain.generate(messages=messages)
                if fallback and not getattr(self.brain, "_looks_like_provider_error", lambda x: False)(fallback):
                    full = fallback
        except Exception as e:
            self.logger.error(f"Model call failed: {e}")
            return ""
        return full

    def _call_model_for_prompt(self, prompt: str) -> str:
        """Direct model call — no conversation history."""
        try:
            return self.brain.generate(messages=[{"role": "user", "content": prompt}])
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────────────────
    # TOOL CALL EXTRACTION
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_tool_calls(self, response: str) -> List[ToolCall]:
        calls: List[ToolCall] = []
        for obj in self._extract_raw_json_objects(response):
            self._append_call(calls, obj)
        return calls

    def _extract_raw_json_objects(self, text: str) -> List[Dict[str, Any]]:
        """Extract all JSON objects from text — handles nested braces."""
        results: List[Dict[str, Any]] = []
        depth  = 0
        start  = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    candidate = text[start:i+1]
                    parsed = self._robust_json_parse(candidate)
                    if isinstance(parsed, dict):
                        results.append(parsed)
                    start = -1
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
        if action:
            calls.append(ToolCall(action, params))

    # ─────────────────────────────────────────────────────────────────────────
    # CONTEXT COMPACTION
    # ─────────────────────────────────────────────────────────────────────────

    def _compact_memory(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """When messages > COMPACT_THRESHOLD, summarize old ones, keep last N."""
        if len(messages) <= self.COMPACT_THRESHOLD:
            return messages
        system  = messages[0] if messages and messages[0].get("role") == "system" else None
        history = messages[1:] if system else messages
        keep    = history[-self.COMPACT_KEEP:]
        old     = history[:-self.COMPACT_KEEP]

        summary     = self._summarize_compacted_messages(old)
        summary_msg = {"role": "system", "content": summary}

        result = [system] if system else []
        result.append(summary_msg)
        result.extend(keep)
        return result

    def _summarize_compacted_messages(self, messages: List[Dict[str, str]]) -> str:
        goals, progress = [], []
        for msg in messages:
            r = msg.get("role")
            c = msg.get("content", "")[:300]
            if r == "user":
                goals.append(c)
            elif r == "assistant":
                progress.append(c)
        lines = ["[CONTEXT_COMPACTED] Summary of prior conversation:"]
        for g in goals:    lines.append(f"- Goal: {g}")
        for p in progress: lines.append(f"- Progress: {p}")
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
        try:
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            if not os.path.exists(path) and self.session_id == "default":
                path = os.path.join(self.root, "logs", "session_memory.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self.memory = json.load(f)
            else:
                self.memory = []
        except Exception:
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
            pass

    def _write_session_bus(self, _messages=None):
        """Write session to session_bus for CLI/GUI/Gateway sync."""
        try:
            session_file = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(session_file), exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=2)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # ABORT
    # ─────────────────────────────────────────────────────────────────────────

    def abort(self):
        """Signal the loop to stop after the current turn."""
        self._abort_flag.set()
        self.logger.info("[LOOP] Abort signaled.")
