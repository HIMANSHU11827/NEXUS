"""
NEXUS UNIFIED COGNITIVE LOOP 10.0 (Sovereign Dual-Core Architecture)
An asynchronous, event-driven state machine coordinating context, tools, 
custom hooks, sandboxing, permission policies, and self-evolution.
"""

import asyncio
import json
import logging
import os
import re
import time
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
from evolution.forge.engine import ToolForge
from evolution.skill_forge.forge import SkillForge
from evolution.memory_forge.forge import MemoryForge
from evolution.knowledge_forge.forge import KnowledgeForge
from evolution.log import EvolutionLog
from evolution.self_improvement.engine import SelfImprovementEngine

class SCAState(str, Enum):
    GROUNDING = "grounding"          # Parallel RAG, unified graph, rules loading
    PLANNING = "planning"            # Complexity classifier & roadmap scaling
    INFERENCE = "inference"          # LLM turn with pre/post hook filters
    AUDITING = "auditing"            # Risk analysis & permission policy resolution
    EXECUTION = "execution"          # Concurrent reads, sequential writes, sandboxing
    VERIFICATION = "verification"    # Targeted test running & failure vaccine compilation
    EVOLVE = "evolve"                # Checkpointing, session_bus sync, log curation

class PermissionPolicy(str, Enum):
    AUTO = "auto"                    # Policy 1: Run all commands automatically
    AI_DECIDE = "ai_decide"          # Policy 2: AI safety laws and risk scoring
    ASK_ALL = "ask_all"              # Policy 3: Ask user every time
    CHECKLIST = "checklist"          # Policy 4: Whitelist checklist auto-run

class ToolCall:
    __slots__ = ("name", "params", "call_id")

    def __init__(self, name: str, params: Dict[str, Any], call_id: str = ""):
        self.name = name
        self.params = params
        self.call_id = call_id or f"call_{id(self)}"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "params": self.params, "call_id": self.call_id}

class HookRegistry:
    def __init__(self):
        self._callbacks: Dict[str, List[Callable[..., Any]]] = {
            "on_state_change": [],
            "pre_llm_call": [],
            "post_llm_call": [],
            "pre_tool_call": [],
            "post_tool_call": [],
            "on_turn_end": [],
        }

    def register(self, event_name: str, cb: Callable[..., Any]):
        if event_name in self._callbacks:
            self._callbacks[event_name].append(cb)

    async def trigger(self, event_name: str, *args, **kwargs):
        for cb in self._callbacks.get(event_name, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(*args, **kwargs)
                else:
                    await asyncio.to_thread(cb, *args, **kwargs)
            except Exception as e:
                logging.getLogger("sca_hooks").error(f"Hook '{event_name}' failed: {e}")

class NexusLoop:
    MAX_TURNS = 20
    COMPACT_THRESHOLD = 10
    COMPACT_KEEP = 4

    def __init__(self, root_dir: Optional[str] = None):
        from kernel import get_nexus_kernel
        self.kernel = get_nexus_kernel(root_dir=root_dir)
        self.root = self.kernel.root
        
        self.session_id = "default"
        self._current_turn_id = ""
        self.state = SCAState.GROUNDING
        self.hooks = HookRegistry()
        self.memory: List[Dict[str, str]] = []
        self._abort_flag = asyncio.Event()
        
        self.logger = logging.getLogger("sovereign_loop")
        self.operator_bypass_mode = os.environ.get("NEXUS_SOVEREIGN", "false").lower() == "true"
        
        # Default Configurations
        self.policy = PermissionPolicy.AI_DECIDE
        self.sandbox_tier = SandboxTier.NORMAL
        self.thinking_mode = True
        self.checklist = {"view_file", "glob", "grep", "list_dir", "test_select", "tester"}
        self._gaps_found: List[Dict[str, Any]] = []
        
        # Register evolution hooks
        self.hooks.register("post_tool_call", self._handle_evolution_gaps)
        
        self.active_agent = ""
        self.active_goal = ""
        self.additional_dirs: List[str] = []

        self.risk_scorer = CommandRiskScorer()
        self.sandbox = SovereignSandbox(self.root)

    # ── Subsystem Proxies ──
    @property
    def brain(self): return self.kernel.moe
    @property
    def discoverer(self): return self.kernel.indexer
    @property
    def tool_registry(self): return self.kernel.tools
    @property
    def rag(self): return self.kernel.rag
    @property
    def laws(self):
        from safety.laws import SafetyLaws
        return self.kernel._get_or_init("laws", lambda: SafetyLaws(self.root))
    @property
    def permissions(self):
        from permissions import NexusPermissions
        return self.kernel._get_or_init("permissions", NexusPermissions)
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
        from evolution.self_improvement.engine import SelfImprovementEngine
        return self.kernel._get_or_init("self_improvement", lambda: SelfImprovementEngine(self.root))
    @property
    def evolution_log(self):
        from evolution.log import EvolutionLog
        return self.kernel._get_or_init("evolution_log", lambda: EvolutionLog(self.root))

    # ── Entry Points ──
    async def run(self, task_desc: str, voice_mode: bool = False) -> str:
        results = []
        async for chunk in self.stream_run(task_desc, voice_mode=voice_mode):
            if chunk.get("type") == "content":
                results.append(chunk["data"])
        return "".join(results)

    async def stream_run(self, task_desc: str, provider: Optional[str] = None, model: Optional[str] = None, voice_mode: bool = False, turn_id: str = "") -> AsyncGenerator[Dict[str, Any], None]:
        self._abort_flag.clear()
        self._current_turn_id = turn_id
        
        # Configure model overrides
        if provider:
            try:
                self.brain.set_override(provider)
            except Exception:
                pass
        if model:
            try:
                active_provider = getattr(self.brain.base_router, "provider", None)
                if active_provider is not None and hasattr(active_provider, "model"):
                    active_provider.model = model
            except Exception:
                pass

        messages: List[Dict[str, str]] = []
        self.state = SCAState.GROUNDING
        turn = 0

        while turn < self.MAX_TURNS:
            if self._abort_flag.is_set():
                yield {"type": "status", "data": "\n[ABORTED]"}
                return

            await self.hooks.trigger("on_state_change", self.state, self)

            if self.state == SCAState.GROUNDING:
                # ── 1. Parallel Grounding ──
                yield {"type": "status", "data": "\n[1/7 Grounding Context in parallel...]"}
                messages = await self._ground_context(task_desc)
                self.state = SCAState.PLANNING

            elif self.state == SCAState.PLANNING:
                # ── 2. Planning Classifier ──
                yield {"type": "status", "data": "\n[2/7 Scaling Planning complexity...]"}
                plan = await self._plan_task(task_desc, messages)
                if plan:
                    yield {"type": "plan", "data": plan}
                    messages.append({"role": "system", "content": f"[PLAN_ROADMAP]:\n{plan}"})
                self.state = SCAState.INFERENCE

            elif self.state == SCAState.INFERENCE:
                # ── 3. Inference Turn ──
                turn += 1
                yield {"type": "status", "data": f"\n[3/7 Inference Turn {turn}]"}
                
                await self.hooks.trigger("pre_llm_call", messages)
                response = await asyncio.to_thread(self._call_model, messages)
                await self.hooks.trigger("post_llm_call", response)
                
                if not response:
                    self.state = SCAState.EVOLVE
                    continue

                yield {"type": "content", "data": response}
                messages.append({"role": "assistant", "content": response})

                tool_calls = self._extract_tool_calls(response)
                if not tool_calls:
                    if "TASK_COMPLETE" in response:
                        self.state = SCAState.EVOLVE
                    else:
                        self.state = SCAState.INFERENCE
                    continue

                yield {"type": "tools_discovered", "tool_calls": [tc.to_dict() for tc in tool_calls]}
                self.state = SCAState.AUDITING

            elif self.state == SCAState.AUDITING:
                # ── 4. Safety Auditing & Permission Policy ──
                yield {"type": "status", "data": "\n[4/7 Auditing proposed operations...]"}
                approved = await self._audit_and_approve(tool_calls)
                if approved:
                    self.state = SCAState.EXECUTION
                else:
                    yield {"type": "status", "data": "\n[BLOCKED] Auditing failed or user rejected execution."}
                    self.state = SCAState.EVOLVE

            elif self.state == SCAState.EXECUTION:
                # ── 5. Concurrent / Serial Sandboxed Execution ──
                yield {"type": "status", "data": "\n[5/7 Spawning tools...]"}
                await self.hooks.trigger("pre_tool_call", tool_calls)
                
                observations = await self._execute_tools(tool_calls)
                yield {"type": "observations", "data": observations}
                
                await self.hooks.trigger("post_tool_call", tool_calls, observations)
                messages.append({"role": "system", "content": "\n".join(observations)})
                
                self.state = SCAState.VERIFICATION

            elif self.state == SCAState.VERIFICATION:
                # ── 6. Verification Gate & Vaccine ──
                yield {"type": "status", "data": "\n[6/7 Verifying compiler & tests...]"}
                success, vaccine = await self._verify_execution(messages)
                if not success and vaccine:
                    yield {"type": "status", "data": "\n[FAILURE] Applying vaccine & replanning."}
                    messages.append({"role": "system", "content": f"[FAILURE_VACCINE]: {vaccine}"})
                    self.state = SCAState.INFERENCE
                else:
                    messages = self._compact_memory(messages)
                    # Gap detection: analyze conversation for evolution opportunities
                    context = "\n".join([m.get("content", "")[:200] for m in messages[-6:]])
                    await self._fill_gap_during_session(context)
                    self.state = SCAState.INFERENCE

            elif self.state == SCAState.EVOLVE:
                # ── 7. Evolve & Finalize ──
                yield {"type": "status", "data": "\n[7/7 Synchronizing checkouts & self-reflection...]"}
                await self._finalize_session(task_desc, messages)
                break

        yield {"type": "status", "data": "\n[COMPLETED]"}

    # ── Internal Methods ──

    async def _ground_context(self, task_desc: str) -> List[Dict[str, str]]:
        # Run grounding RAG, rules, and engine check in parallel
        tasks = [
            asyncio.to_thread(self._load_progressive_rules),
            asyncio.to_thread(self.rag.retrieve_as_text, task_desc, top_k=2),
            asyncio.to_thread(self._check_compiler_status)
        ]
        system_rules, grounding, _ = await asyncio.gather(*tasks, return_exceptions=True)
        
        if isinstance(system_rules, Exception):
            system_rules = "You are NEXUS, a sovereign AI code engine."
        if isinstance(grounding, Exception):
            grounding = ""

        messages = [{"role": "system", "content": system_rules}]
        if grounding and "No relevant matches" not in grounding:
            messages.append({"role": "system", "content": f"[GROUNDING_MEMORIES]:\n{grounding}"})

        return messages

    def _check_compiler_status(self):
        try:
            from utils.engine_manager import STATUS_PATH
            if not os.path.exists(STATUS_PATH):
                from utils.engine_compiler import compile_llama_cpp
                compile_llama_cpp()
        except Exception:
            pass

    def _load_progressive_rules(self) -> str:
        rules = "You are NEXUS, a sovereign AI engineering loop."
        claude_path = os.path.join(self.root, "CLAUDE.md")
        if os.path.exists(claude_path):
            try:
                with open(claude_path, "r", encoding="utf-8") as f:
                    rules += f"\n\n[CLAUDE.md Rules]:\n{f.read()}"
            except Exception:
                pass
        return rules

    async def _plan_task(self, task_desc: str, messages: List[Dict[str, str]]) -> Optional[str]:
        words = len(task_desc.split())
        if words < 8:
            return None # Tier 0: Direct Chat
        if words < 18:
            # Tier 1: Checklist - Dynamically construct using keyword scans in the task prompt
            task_lower = task_desc.lower()
            items = []
            if any(w in task_lower for w in ["search", "find", "grep", "locate", "discover"]):
                items.append("Search the codebase to locate target files or occurrences.")
            if any(w in task_lower for w in ["read", "view", "inspect", "show", "check"]):
                items.append("Read and inspect the target files to understand current implementation.")
            if any(w in task_lower for w in ["edit", "modify", "change", "update", "correct", "write", "rename", "add", "remove", "delete"]):
                items.append("Execute necessary modifications and edits to target files.")
            if any(w in task_lower for w in ["compile", "build", "run"]):
                items.append("Compile project or run workspace tasks.")
            if any(w in task_lower for w in ["test", "pytest", "verify"]):
                items.append("Verify the changes by running unit tests or executing verification scripts.")
            
            if not items:
                items = [
                    f"Analyze the task parameters: '{task_desc[:60]}...'",
                    "Identify and inspect relevant code components.",
                    "Execute the requested updates.",
                    "Verify the implementation correctness."
                ]
            
            return "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, 1))
        
        # Tier 2: Roadmap Phases
        try:
            plan = await asyncio.to_thread(self.architect.plan, task_desc)
            lines = ["Plan Phases:"]
            for idx, p in enumerate(plan, 1):
                lines.append(f"Phase {idx}: {p.get('description', 'Sub-goal')}")
            return "\n".join(lines)
        except Exception:
            return "Phase 1: Research\nPhase 2: Code Edits\nPhase 3: Test Verification"

    async def _audit_and_approve(self, tool_calls: List[ToolCall]) -> bool:
        if self.operator_bypass_mode:
            return True

        # Sync loop configurations to core permissions singleton mode
        if self.policy == PermissionPolicy.AUTO:
            self.permissions.set_mode(PermissionMode.BYPASS)
        elif self.policy == PermissionPolicy.AI_DECIDE:
            self.permissions.set_mode(PermissionMode.AUTO_PILOT)
        elif self.policy == PermissionPolicy.ASK_ALL:
            self.permissions.set_mode(PermissionMode.APPROVE)
        elif self.policy == PermissionPolicy.CHECKLIST:
            self.permissions.set_mode(PermissionMode.PRE_AUTHORIZED)
            self.permissions._pre_authorized_list = list(self.checklist)

        # Check permission modes via core permissions system
        for tc in tool_calls:
            try:
                result = self.permissions.check(tc.name, str(tc.params))
                if not result.granted:
                    # In interactive mode, prompt user via stdin
                    if result.prompt:
                        user_resp = await asyncio.to_thread(input, f"{result.prompt} ")
                        if user_resp.strip().lower() in ("y", "yes"):
                            self.permissions.pre_authorize(str(tc.params))
                            continue
                    return False
            except Exception:
                pass
        return True

    async def _execute_tools(self, tool_calls: List[ToolCall]) -> List[str]:
        read_calls = []
        write_calls = []
        for tc in tool_calls:
            tool = self.tool_registry.get(tc.name)
            if tool and tool.is_read_only(tc.params):
                read_calls.append(tc)
            else:
                write_calls.append(tc)

        observations = []

        # 1. Parallel Reads
        if read_calls:
            tasks = [asyncio.to_thread(self._run_tool, tc) for tc in read_calls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for tc, res in zip(read_calls, results):
                if isinstance(res, Exception):
                    observations.append(f"[{tc.name}]: Failed with error {res}")
                    await self._handle_tool_failure(tc, res)
                else:
                    observations.append(f"[{tc.name}]: {res}")

        # 2. Sequential Writes
        for tc in write_calls:
            try:
                res = await asyncio.to_thread(self._run_tool, tc)
                observations.append(f"[{tc.name}]: {res}")
            except Exception as e:
                observations.append(f"[{tc.name}]: Failed with error {e}")
                await self._handle_tool_failure(tc, e)

        return observations

    def _run_tool(self, call: ToolCall) -> str:
        # Dynamic Sandbox selection based on command risk score (For bash execution)
        if call.name in ("bash", "run_command"):
            cmd = call.params.get("CommandLine") or call.params.get("cmd") or call.params.get("command") or ""
            assessment = self.risk_scorer.assess(cmd)
            # Route through SovereignSandbox execution
            self.sandbox.tier = self.sandbox_tier
            return self.sandbox.execute(cmd)
        return self.tool_registry.execute(call.name, use_cache=True, compress=True, **call.params)

    async def _verify_execution(self, messages: List[Dict[str, str]]) -> Tuple[bool, Optional[str]]:
        if not messages:
            return True, None
            
        last_msg = messages[-1].get("content", "")
        has_error = False
        error_lines = []
        
        # Look for traceback, exception names, error messages or failed lines in last observation
        for line in last_msg.splitlines():
            line_lower = line.lower()
            if "error" in line_lower or "exception" in line_lower or "failed" in line_lower:
                has_error = True
                clean_line = line.strip()
                if len(clean_line) > 120:
                    clean_line = clean_line[:120] + "..."
                if clean_line and clean_line not in error_lines:
                    error_lines.append(clean_line)
                    
        if has_error:
            # Compile dynamic failure vaccine instruction
            if error_lines:
                specific_errors = " | ".join(error_lines[:3])
                vaccine = f"CRITICAL PREVENTIVE VACCINE: The execution failed with error details: [{specific_errors}]. Inspect the traceback or message, correct any syntax/import/logic errors, and verify the file paths/arguments before running this operation again."
            else:
                vaccine = "CRITICAL PREVENTIVE VACCINE: The execution encountered an unknown error. Verify syntax, import correctness, and file existence before executing."
            return False, vaccine

        # Targeted verification using test selector from codebase modifications
        try:
            git_tool = self.tool_registry.get("git")
            if git_tool:
                diff = git_tool.execute(command="diff", name_only=True)
                if diff and "error" not in diff.lower():
                    from optimization.test_selection import TestSelector
                    ts = TestSelector(self.root)
                    changed_files = [f.strip() for f in diff.split("\n") if f.strip()]
                    selected_tests = ts.select_tests(changed_files)
                    
                    if selected_tests:
                        tester_tool = self.tool_registry.get("tester")
                        if tester_tool:
                            res = tester_tool.execute(command="run", tests=selected_tests)
                            if "failed" in res.lower() or "error" in res.lower():
                                return False, f"Targeted tests failed: {res[:200]}"
        except Exception as e:
            self.logger.debug(f"Targeted verification failed: {e}")

        return True, None

    async def _finalize_session(self, task_desc: str, messages: List[Dict[str, str]]):
        last_resp = ""
        for m in reversed(messages):
            if m["role"] == "assistant":
                last_resp = m["content"]
                break
        
        success = "TASK_COMPLETE" in last_resp or "error" not in last_resp.lower()
        
        # Log evolution data
        try:
            await asyncio.to_thread(
                self.evolution_log.win if success else self.evolution_log.lose,
                "agent", "nexus", f"Task finalized. Success: {success}",
                0.0, {"task": task_desc}
            )
        except Exception:
            pass

        # Retry any remembered gaps from the session
        if self._gaps_found:
            self.logger.info(f"Retrying {len(self._gaps_found)} remembered gaps from session...")
            for gap in self._gaps_found:
                await self._retry_gap(gap)
            self._gaps_found.clear()

        # Self-improvement analysis
        try:
            se = SelfImprovementEngine(self.root)
            record = await asyncio.to_thread(se.analyze_session, messages)
            if record and record.actions:
                for action in record.actions[:3]:
                    await asyncio.to_thread(self.evolution_log.improvement, action)
        except Exception:
            pass

        # Write to shared logs / session_bus sync in thread
        await asyncio.to_thread(self._write_session_bus, messages)

    async def _handle_evolution_gaps(self, tool_calls, observations):
        """Hook: post_tool_call — detect gaps from tool observations."""
        pass  # Filled by _fill_gap_during_session when triggered inline

    async def _handle_tool_failure(self, tc: ToolCall, error: Exception):
        """When a tool fails with 'not found' or 'unknown', auto-create it via ToolForge."""
        msg = str(error).lower()
        if "not found" in msg or "unknown tool" in msg or "no such tool" in msg:
            self.logger.info(f"[EVOLVE] Tool '{tc.name}' not found — attempting auto-creation via ToolForge...")
            try:
                forge = ToolForge(self.root)
                tool_def = {
                    "name": tc.name,
                    "description": f"Auto-created to fulfill call: {tc.name}",
                    "params": tc.params,
                }
                result = await asyncio.to_thread(forge.forge, tool_def)
                if result.get("created"):
                    await asyncio.to_thread(
                        self.evolution_log.improvement,
                        f"Auto-created tool '{tc.name}' from failure recovery"
                    )
                    self.logger.info(f"[EVOLVE] Tool '{tc.name}' created successfully")
            except Exception as e:
                self.logger.debug(f"[EVOLVE] Tool auto-creation failed: {e}")
                self._gaps_found.append({
                    "type": "tool",
                    "name": tc.name,
                    "error": str(error),
                })

    async def _fill_gap_during_session(self, context: str):
        """Detect real gaps during chat using LLM analysis of full conversation context."""
        try:
            from evolution.forge.engine import ToolForge
            from evolution.skill_forge.forge import SkillForge
            from evolution.memory_forge.forge import MemoryForge
            from evolution.knowledge_forge.forge import KnowledgeForge

            prompt = f"""[EVOLUTION_GAP_DETECTION]
Analyze the following conversation context for gaps NEXUS should fill:

{context[:2000]}

Respond with a JSON list of gaps to fill. Each gap has:
  - "type": "missing_tool" | "missing_skill" | "memory_candidate" | "knowledge_gap"
  - "name": short name for the entity
  - "reason": why this should be created
  - "create_now": true if it should be created immediately, false if it can wait
If no gaps found, return: {{"gaps": []}}

Return ONLY valid JSON.
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

    def _call_model_for_prompt(self, prompt: str) -> str:
        """Direct model call without message history."""
        try:
            return self.brain.generate(messages=[{"role": "user", "content": prompt}])
        except Exception:
            return ""

    async def _fill_gap(self, gap: Dict[str, Any]):
        """Execute a single gap fill immediately."""
        gtype = gap.get("type", "")
        name = gap.get("name", "unknown")
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
        """Retry a previously remembered gap at session end."""
        try:
            await self._fill_gap(gap)
            self.logger.info(f"[EVOLVE:GAP-FILLED] {gap.get('type', 'unknown')} '{gap.get('name', '?')}' retried successfully")
        except Exception:
            pass

    def _write_session_bus(self, messages):
        try:
            session_file = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            os.makedirs(os.path.dirname(session_file), exist_ok=True)
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=2)
        except Exception:
            pass

    # ── Lower level Helpers ──

    def _call_model(self, messages: List[Dict]) -> str:
        full_response = ""
        try:
            # Handle thinking mode configurations
            modified_messages = list(messages)
            if self.thinking_mode:
                modified_messages.append({"role": "system", "content": "Think step by step inside <thinking>...</thinking> tags before answering."})
            else:
                modified_messages.append({"role": "system", "content": "Answer directly and omit reasoning blocks."})

            for chunk in self.brain.stream_generate(messages=modified_messages):
                full_response += chunk
            if not full_response.strip():
                fallback = self.brain.generate(messages=modified_messages)
                if fallback and not self.brain._looks_like_provider_error(fallback):
                    full_response = fallback
        except Exception as e:
            self.logger.error(f"Model call failed: {e}")
            return ""
        return full_response

    def _extract_tool_calls(self, response: str) -> List[ToolCall]:
        calls = []
        for obj in self._extract_raw_json_objects(response):
            self._append_call(calls, obj)
        return calls

    def _extract_raw_json_objects(self, text: str) -> List[Dict[str, Any]]:
        results = []
        for m in re.finditer(r"(\{.*?\})", text, re.DOTALL):
            val = self._robust_json_parse(m.group(1))
            if isinstance(val, dict):
                results.append(val)
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

    def _compact_memory(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if len(messages) <= self.COMPACT_THRESHOLD:
            return messages
        system = messages[0] if messages and messages[0].get("role") == "system" else None
        history = messages[1:] if system else messages
        keep = history[-self.COMPACT_KEEP:]
        compacted = history[:-self.COMPACT_KEEP]

        summary = self._summarize_compacted_messages(compacted)
        summary_msg = {"role": "system", "content": summary}

        result = [system] if system else []
        result.append(summary_msg)
        result.extend(keep)
        return result

    def _summarize_compacted_messages(self, messages: List[Dict[str, str]]) -> str:
        goals, progress = [], []
        for msg in messages:
            r = msg.get("role")
            c = msg.get("content", "")
            if r == "user":
                goals.append(c)
            elif r == "assistant":
                progress.append(c)
        lines = ["[CONTEXT_COMPACTED] Previous conversation summary:"]
        for g in goals: lines.append(f"- Goal: {g}")
        for p in progress: lines.append(f"- Progress: {p}")
        return "\n".join(lines)

    def save_memory(self):
        """Persists short-term memory to disk immediately."""
        try:
            path = os.path.join(self.root, "logs", "sessions", f"{self.session_id}.json")
            if self.session_id == "default": # Legacy fallback
                old_path = os.path.join(self.root, "logs", "session_memory.json")
                if not os.path.exists(os.path.dirname(path)) and os.path.exists(old_path):
                     os.makedirs(os.path.dirname(path), exist_ok=True)
            
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to auto-save memory: {e}")

    def load_memory(self, session_id: Optional[str] = None):
        """Loads short-term memory from disk for a specific session."""
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
        """High-performance sync of memory from disk to ensure CLI/GUI cohesion."""
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

