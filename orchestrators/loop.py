"""
NEXUS UNIFIED COGNITIVE LOOP 4.0
Single loop architecture inspired by Claude Code, OpenClaw, and HyperAgents.

Design principles:
- NO MODES: Single loop handles chat and agentic tasks identically
- NATIVE TOOL CALLING: Uses provider's tool calling when available
- DEMAND-LOADED SKILLS: Only summaries in prompt, full skills on demand
- CONTEXT COMPACTION: Auto-compacts when history exceeds threshold
- STREAMING-FIRST: Generator-based for real-time updates
- PARALLEL EXECUTION: Read-only tools run concurrently
"""

import os
import re
import json
import time
import logging
import threading
import asyncio
from typing import List, Dict, Any, Optional, Iterator, Tuple, Generator, Union
from permissions import PermissionMode
from enum import Enum
import concurrent.futures
from typing import TYPE_CHECKING
from router import IntentRouter

if TYPE_CHECKING:
    from discovery import NexusAutoDiscover
    from prompts import NexusPromptEngine
    from observer import NexusObserver
    from skills import NexusSkillMaster
    from providers.router import ModelRouter
    from tool_adapters import RegistryTerminalTool
    from tool_adapters import RegistryFileTools
    from safety.prover import LogicProver
    from rag.engine import NexusAtlasRAG
    from tool_adapters import RegistryGitTools
    from hive import NexusHiveEngine
    from tools.reporter.script import NexusLSPTool
    from tool_adapters import RegistryTestTool
    from tools.nexus_tools.registry import ToolRegistry
    from tasks import TaskManager
    from permissions import PermissionSystem
    from evolution.ensemble import EnsembleManager
    from knowledge.vault import KnowledgeVault
    from tools.nexus_tools.nexus_operator_tool import NexusGUIOperator
    from evolution.skill_synthesizer import SkillSynthesizer
    from intelligence.moa import MixtureOfArchitects
    from telemetry.database import NexusTelemetryDB
    from safety.laws import NexusLawKernel
    from tasks.scheduler import NexusTaskScheduler

from nexus_compat import s, itail

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TurnResult(Enum):
    COMPLETED = "completed"
    MAX_TURNS = "max_turns"
    ERROR = "error"
    ABORTED = "aborted"


class ToolCall:
    """Represents a single tool call from the model."""

    __slots__ = ("name", "params", "call_id")

    def __init__(self, name: str, params: Dict[str, Any], call_id: str = ""):
        self.name = name
        self.params = params
        self.call_id = call_id or f"call_{id(self)}"

    def __repr__(self) -> str:
        return f"ToolCall({self.name}, {list(self.params.keys())})"


class NexusLoop:
    """
    NEXUS UNIFIED COGNITIVE LOOP 4.0

    Single loop that handles ALL interactions — chat, code, research, debug.
    No mode switching. The model decides tool usage based on context.

    Architecture:
    1. Assemble prompt (system + skills summaries + grounding)
    2. Call LLM with tool definitions
    3. Extract tool calls from response
    4. Execute tools (parallel reads, serial writes)
    5. Inject observations
    6. Repeat until no tool calls or max turns
    """

    MAX_TURNS = 20
    COMPACT_THRESHOLD = 10
    COMPACT_KEEP = 4

    def __init__(self, root_dir: Optional[str] = None):
        from kernel import get_nexus_kernel
        self.kernel = get_nexus_kernel(root_dir=root_dir)
        self.root = self.kernel.root
        self.session_id = "default"
        self.model = ""
        self.provider_override = ""
        self.permission_mode = "auto"
        self.active_agent = ""
        self.active_goal = ""
        self.additional_dirs: List[str] = []
        
        self.memory: List[Dict[str, str]] = []
        self._abort_flag = threading.Event()
        self.hive_buffer: List[str] = []

        self.logger = logging.getLogger("unified_loop")
        self.simulation_depth = 0 
        self.task_complexity = "simple"
        self.force_reasoning = False
        
        # Operator mode keeps direct execution, but still routes through risk checks.
        self.operator_bypass_mode = os.environ.get("NEXUS_SOVEREIGN", "false").lower() == "true"
        
        if not self.operator_bypass_mode:
            self.permissions.set_mode(PermissionMode.AUTO)

    # ── Kernel Proximity Proxies (Unified Access) ──
    @property
    def brain(self): return self.kernel.moe
    
    @property
    def discoverer(self): return self.kernel.indexer
    
    @property
    def terminal(self): return self.kernel.tools.get("bash")
    
    @property
    def files(self): return self.kernel.tools.get("file_edit")
    
    @property
    def prover(self): return self.kernel.prover
    
    @property
    def rag(self): return self.kernel.rag
    
    @property
    def git(self): return self.kernel.tools.get("git")
    
    @property
    def hive(self):
        from hive import NexusHiveEngine
        return self.kernel._get_or_init("hive", lambda: NexusHiveEngine(self.root))
    
    @property
    def lsp(self): return self.kernel.tools.get("reporter")
    
    @property
    def tester(self): return self.kernel.tools.get("tester")
    
    @property
    def tool_registry(self): return self.kernel.tools
    
    @property
    def task_manager(self):
        from tasks import TaskManager
        return self.kernel._get_or_init("task_manager", TaskManager)
    
    @property
    def permissions(self):
        from permissions import PermissionSystem
        return self.kernel._get_or_init("permissions", PermissionSystem)
    
    @property
    def ensemble(self): 
        from evolution.ensemble import EnsembleManager
        workspace = os.path.join(self.root, "workspace")
        return self.kernel._get_or_init("ensemble", lambda: EnsembleManager(workspace))
    
    @property
    def browser(self): return self.kernel.tools.get("browser")
    
    @property
    def skill_manager(self):
        from skills import NexusSkillMaster
        return self.kernel._get_or_init("skill_manager", lambda: NexusSkillMaster(self.root))
    
    @property
    def observer(self):
        from observer import NexusObserver
        return self.kernel._get_or_init("observer", lambda: NexusObserver(self.root))
    
    @property
    def vault(self):
        from knowledge.vault import KnowledgeVault
        return self.kernel._get_or_init("vault", KnowledgeVault)
    
    @property
    def gui(self): return self.kernel.tools.get("nexus_operator")
    
    @property
    def router(self): return self.kernel.moe
    
    @property
    def synthesizer(self):
        from evolution.skill_synthesizer import SkillSynthesizer
        return self.kernel._get_or_init("synthesizer", lambda: SkillSynthesizer(self.root))
    
    @property
    def moa(self): return self.kernel.moa
    
    @property
    def telemetry(self): return self.kernel.telemetry
    
    @property
    def laws(self):
        from safety.laws import NexusLawKernel
        return self.kernel._get_or_init("laws", NexusLawKernel)
    
    @property
    def architect(self):
        from orchestrators.architect import NexusArchitect
        return self.kernel._get_or_init("architect", lambda: NexusArchitect())
    
    @property
    def scheduler(self):
        from tasks.scheduler import NexusTaskScheduler
        return self.kernel._get_or_init("scheduler", lambda: NexusTaskScheduler(self.run))

    @property
    def memory_kernel(self):
        from neural.memory_kernel import MemoryKernel
        return self.kernel._get_or_init("memory_kernel", lambda: MemoryKernel(self.root))

    @property
    def failure_memory(self):
        from sandbox.failure_memory import FailureMemory
        return self.kernel._get_or_init("failure_memory", lambda: FailureMemory(self.root))

    @property
    def repo_map_builder(self):
        from code_intel.repo_map import RepoMapBuilder
        return self.kernel._get_or_init("repo_map_builder", lambda: RepoMapBuilder(self.root))

    @property
    def memory_graph(self):
        from cognition.memory_graph import AdaptiveMemoryGraph
        return self.kernel._get_or_init("adaptive_memory_graph", lambda: AdaptiveMemoryGraph(self.root))

    @property
    def context_engine(self):
        from cognition.context_engine import ZeroTokenContextEngine
        return self.kernel._get_or_init("zero_token_context", lambda: ZeroTokenContextEngine(self.root))

    @property
    def self_improvement(self):
        from cognition.self_improvement import SelfImprovementEngine
        return self.kernel._get_or_init("self_improvement", lambda: SelfImprovementEngine(self.root))


    def _hive_cast(self, mission_map: str) -> str:
        """
        [HIVE-CASTING]: Deploys specialized sub-agents to execute a complex mission.
        """
        hive_id = f"MISSION_{int(time.time())}"
        self.logger.info(f"🚀 [HIVE]: Initiating Hive-Cast '{hive_id}'...")
        
        # 🧠 [AGI_PHASE]: Extract roles from mission map
        roles = []
        if "ENGINEER" in mission_map.upper(): roles.append("ENGINEER")
        if "RESEARCHER" in mission_map.upper(): roles.append("RESEARCHER")
        if "AUDITOR" in mission_map.upper(): roles.append("AUDITOR")
        if "ARCHITECT" in mission_map.upper(): roles.append("ARCHITECT")
        
        if not roles: roles = ["ENGINEER", "AUDITOR"] # Default elite duo
        
        deployment_msgs = []
        for role in roles:
            # We pass the specific segment of the mission map if possible, 
            # but for now we pass the whole map and let the agent filter.
            msg = self.hive.spawn_agent(task=mission_map, persona=role, hive_id=hive_id)
            deployment_msgs.append(msg)
            
        return f"\n[HIVE_STATUS]: {len(roles)} agents deployed (ID: {hive_id}).\n" + "\n".join(deployment_msgs)

    def _get_workspace_delta(self) -> str:
        """[WORKSPACE_SENSING]: Returns a summary of recent changes and repo health."""
        try:
            if not os.path.exists(os.path.join(self.root, ".git")):
                return "[WORKSPACE]: Stable."

            # 1. Check for git diff (fast)
            diff_cmd = "git diff --stat"
            diff_out = self.tool_registry.execute("bash", cmd=diff_cmd, use_cache=False)
            if "[TOOL_ERROR]" in diff_out or "not a git repository" in diff_out.lower():
                return "[WORKSPACE]: Stable."
            
            # 2. Check for new files (optimized: only check top-level and known source dirs if possible, 
            # or use a more efficient way than recursive glob)
            # For now, let's just limit the depth or skip if too many files.
            recent_files = []
            # ... (Omitted slow glob for now, can be replaced with an index-based check)
            
            delta = []
            if "diff" in diff_out and "---" not in diff_out and len(diff_out.strip()) > 0:
                delta.append(f"[GIT_CHANGES]:\n{diff_out}")
                
            return "\n".join(delta) if delta else "[WORKSPACE]: Stable."
        except Exception:
            return "[WORKSPACE]: Sensing offline."

    def _build_system_prompt(self, task_hint: str = "") -> str:
        from prompts import NexusPromptEngine
        active_provider = getattr(getattr(self.kernel.moe.base_router, "provider", None), "provider_name", "")
        if active_provider in {"lm_studio", "ollama", "llama_cpp"}:
            return NexusPromptEngine.build_local_prompt()

        # Route intent dynamically if task_hint is provided
        intent_hints = None
        intent = "chat"
        complexity = "simple"
        needs_tools = False
        if task_hint:
            try:
                from cognition.routing import IntentRouter
                intent_res = IntentRouter(self.brain.base_router).classify(task_hint)
                if intent_res:
                    intent_hints = intent_res.tool_hints
                    intent = intent_res.intent
                    complexity = intent_res.complexity
                    needs_tools = intent_res.needs_tools
            except Exception:
                pass

        context_map = self.discoverer.get_context_map()
        system = NexusPromptEngine.build_super_prompt(
            self.root,
            context_map,
            intent_hints=intent_hints,
            intent=intent,
            complexity=complexity,
            needs_tools=needs_tools
        )
        if "NEXUS" not in system:
            system = f"# NEXUS IDENTITY: Local-first autonomous assistant.\n{system}"
        try:
            max_files = 50 if getattr(self, "_voice_mode", False) else 800
            repo_summary = self.repo_map_builder.build(max_files=max_files).summary(limit=60)
            system = f"{system}\n\n[CODEBASE_CONSCIOUSNESS_MAP]:\n{repo_summary}"
        except Exception as e:
            self.logger.warning(f"Repo map build failed: {e}")

        try:
            packet = self.memory_graph.compressed_packet("project architecture failures safety tests", limit=6)
            if packet["facts"]:
                context_packet = self.context_engine.create_packet(
                    title="current_project_memory",
                    content="\n".join(packet["facts"]),
                    pointers=packet["pointers"],
                    metadata={"source": "adaptive_memory_graph"},
                )
                system = f"{system}\n\n[ZERO_TOKEN_CONTEXT_PACKET]: {context_packet.id}\n{context_packet.summary}"
        except Exception as e:
            self.logger.warning(f"Adaptive memory injection failed: {e}")
        
        # Inject dynamic skill prompt if active
        skill_prompt = self.skill_manager.get_active_prompt()
        if skill_prompt:
            system = f"{system}\n\n[ACTIVE_SKILL_OVERRIDE]:\n{skill_prompt}"
        
        # ⚡ Shared Evolution Context
        insights = self.vault.retrieve_as_text("evolution project growth architecture AGI", top_k=5)
        if "No relevant knowledge" not in insights:
            system = f"{system}\n\n[SHARED_EVOLUTIONARY_INSIGHTS]:\n{insights}"
            
        system = f"{system}\n\n[SELF_IMPROVEMENT]:\n- Improve real code only when the requested task requires it or a verified defect is found.\n- Before high-impact edits in core runtime files, create a rollback snapshot or patch ledger baseline.\n- Prefer small, reviewable patches, targeted tests, and explicit remaining-risk notes.\n- Do not claim AGI, consciousness, or production readiness unless verified by working code and tests."

        system = f"{system}\n\n[COMMUNICATION_PROTOCOL]:\n- Be concise, direct, and technically honest.\n- Current provider tier: {self.kernel.moe.base_router.mode}.\n- Use tools through JSON blocks when action is required: {{\"action\": \"tool_name\", \"params\": {{...}}}}.\n- After a read-only tool returns relevant observations, answer in prose instead of calling more tools.\n- Do not repeat similar search/list/read tools unless the previous observation was empty or erroneous.\n- Explain what changed and how it was verified.\n- If the mission is complete, output TASK_COMPLETE."
        
        # 🛡️ [v20.0 SELF_CORRECTION_PROTOCOL]
        system = f"{system}\n\n[SELF_CORRECTION]:\n- If a tool returns an [ERROR], analyze the error before retrying.\n- Do not repeat the same failing command unchanged.\n- Try a safer fix strategy: check paths, syntax, provider credentials, timeouts, or permissions.\n- State the cause and the next corrective action briefly."

        # 🧠 [v21.0 SOVEREIGN_MEMORY]
        ram_dump = self.memory_kernel.ram_dump()
        system = f"{system}\n\n{ram_dump}"
        
        retrospection = self.memory_kernel.retrospective_review(self.session_id)
        if "No past episodes" not in retrospection:
            system = f"{system}\n\n{retrospection}"

        return system

    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Returns tool definitions, compacted for smaller models to preserve context."""
        all_tools = self.tool_registry.list_all()
        
        # Detect if we are using a 'NANO' or 'MICRO' scale model
        messages_for_tier = [{"role": "user", "content": "Checking tier scale..."}]
        tier = self.kernel.moe.base_router._get_required_tier(messages_for_tier)
        
        if tier in ["NANO", "MICRO"]:
            # Extreme Compaction: Only name and description, minimal params
            compacted = []
            for tool in all_tools:
                compacted.append({
                    "name": tool["name"],
                    "description": tool["description"][:100] + "...",
                    "parameters": {"type": "object", "properties": {}} # Minimal
                })
            return compacted
            
        return all_tools

    def _extract_tool_calls(self, response: str) -> List[ToolCall]:
        calls = []
        
        # 1. Multi-Stage Extraction Logic (Markdown Blocks)
        # Handle ```json ... ``` and ``` ... ```
        blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
        
        for block in blocks:
            try:
                data = self._robust_json_parse(block)
                if data:
                    if isinstance(data, list):
                        for item in data:
                            self._append_call(calls, item)
                    else:
                        self._append_call(calls, data)
            except Exception:
                continue

        # 2. Heuristic Raw JSON Extraction (For models that miss code blocks or embed JSON in text)
        if not calls:
            for data in self._extract_raw_json_objects(response):
                self._append_call(calls, data)

        # 3. Explicit Bash Blocks (v19.1 Priority)
        bash_blocks = re.findall(r"```bash\s*(.*?)```", response, re.DOTALL)
        for cmd in bash_blocks:
            calls.append(ToolCall("bash", {"cmd": cmd.strip()}))

        return calls

    def _extract_raw_json_objects(self, text: str) -> List[Dict[str, Any]]:
        """Extract complete raw JSON tool objects, including nested params."""
        found: List[Dict[str, Any]] = []
        decoder = json.JSONDecoder()
        idx = 0
        while idx < len(text):
            start = text.find("{", idx)
            if start == -1:
                break
            try:
                data, end = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                idx = start + 1
                continue
            if isinstance(data, dict) and (data.get("action") or data.get("name")):
                found.append(data)
            idx = start + max(end, 1)
        return found

    def _robust_json_parse(self, text: str) -> Optional[Any]:
        """[NEURAL_REPAIR]: Advanced repair for hallucinatory or malformed JSON."""
        text = text.strip()
        if not text: return None
        
        try:
            return json.loads(text)
        except Exception:
            pass

        # Stage 2: Structural Repair
        try:
            # Fix common LLM mistakes
            cleaned = text
            # 1. Replace smart quotes
            cleaned = cleaned.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")
            # 2. Fix trailing commas before closing braces/brackets
            cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
            # 3. Fix missing quotes on keys (only for simple alphanumeric keys)
            cleaned = re.sub(r"([{,]\s*)([a-zA-Z0-9_]+)\s*:", r'\1"\2":', cleaned)
            # 4. Handle escaped newlines that should be literal
            cleaned = cleaned.replace("\\n", "\n")
            
            return json.loads(cleaned)
        except Exception:
            # Stage 3: Greedy extraction for deeply nested or partial JSON
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                try: 
                    # Try one more time with the greedy match
                    return json.loads(match.group(1))
                except: 
                    # Last ditch: try to fix common issues in the greedy match
                    try:
                        inner = match.group(1)
                        inner = re.sub(r",\s*([\]}])", r"\1", inner)
                        return json.loads(inner)
                    except:
                        return None
        return None

    def _append_call(self, calls: List[ToolCall], data: Dict[str, Any]):
        action = data.get("action") or data.get("name")
        params = data.get("params", data.get("arguments"))
        if params is None:
            params = {
                key: value
                for key, value in data.items()
                if key not in {"action", "name", "call_id", "id"}
            }
        if action:
            calls.append(ToolCall(action, params))

    def _execute_tools(self, tool_calls: List[ToolCall]) -> List[str]:
        """
        Executes a batch of tool calls with optimized parallel/serial split.
        """
        if getattr(self, "in_planning_phase", False):
            # Block any non-read-only tool calls during planning phase
            write_calls = [
                tc for tc in tool_calls
                if not (self.tool_registry.get(tc.name) and self.tool_registry.get(tc.name).is_read_only(tc.params))
            ]
            if write_calls:
                blocked_names = ", ".join(tc.name for tc in write_calls)
                self.logger.info(f"🛡️ [PLAN_ACT_SEPARATION]: Blocked write tool calls: {blocked_names} during planning phase.")
                return [
                    f"[PLANNING_PHASE_RESTRICTION]: Write/edit tool calls ({blocked_names}) are blocked during the planning phase. "
                    "First, outline your detailed implementation plan. You may use read-only tools (like glob, grep, view_file) to research. "
                    "The writing phase will activate in the next turn."
                ]

        for tc in tool_calls:
            # Yield structured marker for the Shell UI
            # Using a custom generator-friendly way to pass this back to stream_run
            # but since we are inside a method called by stream_run, we can't yield directly 
            # unless we return a generator. For now, we'll just log and execute.
            pass

        read_tools = [
            tc for tc in tool_calls 
            if self.tool_registry.get(tc.name) and self.tool_registry.get(tc.name).is_read_only(tc.params)
        ]
        write_tools = [tc for tc in tool_calls if tc not in read_tools]

        # Partition write tools into parallel-safe writes and sequential writes.
        # A write tool is parallel-safe if the tool is concurrency-safe and does not target overlapping paths.
        parallel_writes = []
        sequential_writes = []
        
        write_paths = {}
        for tc in write_tools:
            tool = self.tool_registry.get(tc.name)
            if not tool:
                sequential_writes.append(tc)
                continue
                
            if not tool.is_concurrency_safe(tc.params):
                sequential_writes.append(tc)
                continue
                
            # Check for path parameter to detect conflicts
            path_param = tc.params.get("path") or tc.params.get("file") or tc.params.get("filepath") or tc.params.get("uri")
            if path_param and isinstance(path_param, str):
                try:
                    if hasattr(tool, "_resolve_path"):
                        full_path = os.path.abspath(tool._resolve_path(path_param))
                    else:
                        full_path = os.path.abspath(path_param)
                    write_paths.setdefault(full_path, []).append(tc)
                except Exception:
                    write_paths.setdefault(path_param, []).append(tc)
            else:
                # No path parameter and is concurrency-safe -> can be run in parallel!
                parallel_writes.append(tc)
                
        for path, calls in write_paths.items():
            if len(calls) == 1:
                parallel_writes.append(calls[0])
            else:
                # Multiple calls to the same path must run sequentially
                sequential_writes.extend(calls)

        observations = []

        # 1. Parallel Read Execution
        if read_tools:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(read_tools), 8)) as executor:
                futures = {executor.submit(self._run_tool, tc): tc for tc in read_tools}
                for future in concurrent.futures.as_completed(futures):
                    tc = futures[future]
                    try:
                        result = future.result()
                        observations.append(f"[{tc.name}]: {result}")
                    except Exception as e:
                        obs = self._handle_tool_failure(tc, str(e))
                        observations.append(obs)

        # 2. Parallel Safe Write Execution
        if parallel_writes:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(parallel_writes), 8)) as executor:
                futures = {executor.submit(self._run_tool, tc): tc for tc in parallel_writes}
                for future in concurrent.futures.as_completed(futures):
                    tc = futures[future]
                    try:
                        result = future.result()
                        observations.append(f"[{tc.name}]: {result}")
                    except Exception as e:
                        obs = self._handle_tool_failure(tc, str(e))
                        observations.append(obs)

        # 3. Sequential Write Execution
        if sequential_writes:
            for tc in sequential_writes:
                try:
                    result = self._run_tool(tc)
                    observations.append(f"[{tc.name}]: {result}")
                except Exception as e:
                    obs = self._handle_tool_failure(tc, str(e))
                    observations.append(obs)

        return observations

    def _handle_tool_failure(self, call: ToolCall, error: str) -> str:
        """[SELF_CORRECTION]: Analyzes failure and provides guidance or automatic fixes."""
        self.logger.warning(f"Tool {call.name} failed: {error}")
        try:
            self.failure_memory.record(
                task="tool_execution",
                tool=call.name,
                error=error,
                context={"params": call.params},
            )
            self.self_improvement.learn_from_failure(
                task=f"tool_execution:{call.name}",
                error=error,
                fix="Inspect tool parameters, validate paths/commands, and retry with the smallest safe correction.",
            )
        except Exception:
            pass
        
        # 1. Path errors
        if "not found" in error.lower() or "no such file" in error.lower():
            target = call.params.get("path") or call.params.get("target_path") or call.params.get("cmd")
            if target:
                return f"[ERROR]: {error}. TIP: Try 'glob' or 'ls' to verify the path before retrying."
        
        # 2. Permission errors
        if "denied" in error.lower() or "permission" in error.lower():
            return f"[ERROR]: {error}. TIP: You may need to ask the user for elevated access or use a different path."
            
        return f"[ERROR]: {error}"

    def _run_tool(self, call: ToolCall) -> str:
        action = call.name
        p = call.params
        
        # Log starting status
        evt_id = self._log_work_event(action, p, "running")
        
        try:
            # phase 0: World Simulation (Imagination Layer)
            if action in ("file_edit", "bash", "git", "nexus_evolve"):
                try:
                    sim_res = self.hive.world_simulate(action, str(p))
                    self.logger.info(f"🔮 [WORLD_MODELER]: {sim_res}")
                except: pass

            # Phase 1: policy audit. Compatibility bypass remains env-gated.
            if not self.operator_bypass_mode:
                audit_res = self.laws.audit(action, p)
                if not audit_res["granted"]:
                    self._log_work_event(action, p, "error", evt_id, output=f"[LAW_BLOCKED]: {audit_res['reason']}")
                    return f"[LAW_BLOCKED]: {audit_res['reason']} (Law: {audit_res['law_name']})"
                
                perm_result = self.permissions.check(action, str(p))
                if not perm_result.granted:
                    self._log_work_event(action, p, "error", evt_id, output=f"[PERMISSION_DENIED]: {perm_result.reason}")
                    return f"[PERMISSION_DENIED]: {perm_result.reason}"
            
            # Delegate to ToolRegistry
            res = self.tool_registry.execute(action, use_cache=True, compress=True, **p)
            
            # Log success status
            self._log_work_event(action, p, "done", evt_id, output=str(res))
            return res

        except Exception as e:
            # Log failure status
            self._log_work_event(action, p, "error", evt_id, output=str(e))
            return f"[ERROR]: {str(e)}"

    def _compact_memory(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if len(messages) <= self.COMPACT_THRESHOLD:
            return messages
            
        # Let's identify the system prompt (first system message)
        system_prompt = None
        start_idx = 0
        if messages and messages[0].get("role") == "system":
            system_prompt = messages[0]
            start_idx = 1

        # The rest is history
        history = messages[start_idx:]
        keep_count = getattr(self, "COMPACT_KEEP", 4)

        # We scan history from the end to find the index where the number of non-system messages is `keep_count`.
        non_sys_seen = 0
        cutoff_idx = 0
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") != "system":
                non_sys_seen += 1
                if non_sys_seen == keep_count:
                    cutoff_idx = i
                    break
        
        # So the kept history is history[cutoff_idx:]
        # The history to compact is history[:cutoff_idx]
        to_compact = history[:cutoff_idx]
        kept = history[cutoff_idx:]

        # Create the summary from to_compact
        summary_content = self._summarize_compacted_messages(to_compact, kept_count=len(kept))
        summary_msg = {
            "role": "system",
            "content": summary_content
        }

        # Keep the main system prompt
        result = [system_prompt] if system_prompt else []
        
        # Also, check if there's any active AUTO-RECALL or AUTO_OBSERVATION in the compacted messages that we might want to keep at the root level
        for m in reversed(to_compact):
            if m.get("role") == "system" and ("[AUTO-RECALL]" in m.get("content", "") or "[AUTO_OBSERVATION]" in m.get("content", "")):
                result.append(m)
                break
                
        result.append(summary_msg)
        result.extend(kept)
        return result

    def _summarize_compacted_messages(self, messages: List[Dict[str, str]], kept_count: int = 8) -> str:
        """Summarize history into a compact context block for the model."""
        goals = []
        progress = []
        observations = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                goals.append(content)
            elif role == "assistant":
                progress.append(content)
            elif role in ("system", "tool"):
                observations.append(content)
                
        lines = [
            f"[CONTEXT_COMPACTED]: Previous {len(messages)} interactions summarized to preserve context window.",
            "User goals:",
        ]
        for g in goals:
            lines.append(f"- {g}")
        lines.append("Assistant progress/actions:")
        for p in progress:
            lines.append(f"- {p}")
        if observations:
            lines.append("System/Tool observations:")
            for o in observations:
                lines.append(f"- {o}")
                
        return "\n".join(lines)

    @property
    def persistence(self):
        from context.persistence import NexusFilePersistence
        return NexusFilePersistence(self.root)

    def _checkpoint_loop_session(self, task: str, messages: list, turn: int, status: str, last_response: str) -> None:
        """Saves session checkpoint to disk with relevant metadata."""
        metadata = {
            "turn": turn,
            "status": status,
            "task": task,
            "last_response": last_response
        }
        self.persistence.checkpoint_session(self.session_id, messages, metadata)

    def _should_delegate_to_hive(self, task: str, intent: Any) -> bool:
        """Determines if a task should be delegated to the Hive based on complexity/intent."""
        if getattr(intent, "intent", "") == "chat" and getattr(intent, "complexity", "") == "simple":
            return False
        if len(task.split()) > 15 or getattr(intent, "complexity", "") in ("medium", "high", "complex"):
            return True
        return False

    def _hive_roles_for_task(self, task: str, hint_roles: str = "") -> List[str]:
        """Returns the list of Hive roles required for the task."""
        roles = ["ARCHITECT"]
        
        task_lower = task.lower()
        if "gui" in task_lower or "ux" in task_lower:
            roles.append("GUI_UX_SPECIALIST")
        if "provider" in task_lower or "routing" in task_lower:
            roles.append("PROVIDER_ROUTING_SPECIALIST")
        if "compaction" in task_lower or "context" in task_lower:
            roles.append("MEMORY_CONTEXT_ARCHITECT")
        if "benchmark" in task_lower or "performance" in task_lower:
            roles.append("PERFORMANCE_ENGINEER")
        if "roadmap" in task_lower or "strategy" in task_lower:
            roles.append("PRODUCT_STRATEGIST")
            
        if hint_roles:
            for word in hint_roles.split():
                if word == "ENGINEER" and "ENGINEER" not in roles:
                    roles.append("ENGINEER")
                elif word == "AUDITOR" and "AUDITOR" not in roles:
                    roles.append("AUDITOR")
                elif word == "RESEARCHER" and "RESEARCHER" not in roles:
                    roles.append("RESEARCHER")
                    
        if "fix" in task_lower or "code" in task_lower:
            if "ENGINEER" not in roles:
                roles.append("ENGINEER")
        if "test" in task_lower or "verify" in task_lower:
            if "QA_EXPERT" not in roles:
                roles.append("QA_EXPERT")
        if "audit" in task_lower:
            if "AUDITOR" not in roles:
                roles.append("AUDITOR")
        if "research" in task_lower:
            if "RESEARCHER" not in roles:
                roles.append("RESEARCHER")
                
        roles.append("LIBRARIAN")
        return roles

    def _log_work_event(self, action_name: str, params: dict, status: str = "running", event_id: str = None, output: str = None) -> str:
        """Logs a real work event to workspace/work_events/{session_id}.jsonl."""
        try:
            import json
            import uuid
            import time
            
            session_id = self.session_id or "default"
            events_dir = os.path.join(self.root, "workspace", "work_events")
            os.makedirs(events_dir, exist_ok=True)
            events_file = os.path.join(events_dir, f"{session_id}.jsonl")
            
            # 1. Determine tool kind/type
            kind = "tool"
            action = action_name
            target = ""
            
            lowered_action = action_name.lower()
            if any(token in lowered_action for token in ("search", "ddg", "duck", "web", "grep", "glob", "find")):
                kind = "search"
                action = "Searching"
                target = params.get("query") or params.get("q") or params.get("pattern") or params.get("path") or ""
            elif lowered_action in ("file_edit", "write_to_file", "replace_file_content", "multi_replace_file_content", "view_file", "read_file", "create_file", "delete_file", "file_ops"):
                kind = "file"
                target = params.get("TargetFile") or params.get("AbsolutePath") or params.get("path") or ""
                if lowered_action in ("view_file", "read_file"):
                    action = "Read file"
                elif lowered_action in ("write_to_file", "create_file"):
                    action = "Create file"
                elif lowered_action == "delete_file":
                    action = "Delete file"
                else:
                    action = "Edit file"
            elif lowered_action in ("bash", "run_command", "process", "shell", "terminal", "exec"):
                kind = "command"
                action = "Run command"
                target = params.get("CommandLine") or params.get("cmd") or params.get("command") or ""
            elif "rag" in lowered_action or "atlas" in lowered_action or "context" in lowered_action:
                kind = "rag"
                action = "Read context"
                target = params.get("query") or ""
            elif "mcp" in lowered_action:
                kind = "mcp"
                action = "Use MCP"
                target = params.get("tool") or params.get("name") or params.get("server") or lowered_action
            elif "browser" in lowered_action:
                kind = "browser"
                action = "Browse"
                target = params.get("url") or params.get("query") or params.get("target") or lowered_action
            elif "plugin" in lowered_action:
                kind = "plugin"
                action = "Use plugin"
                target = params.get("name") or params.get("plugin") or lowered_action
            elif "skill" in lowered_action:
                kind = "skill"
                action = "Use skill"
                target = params.get("name") or params.get("skill") or lowered_action
            elif "provider" in lowered_action or "model" in lowered_action:
                kind = "provider"
                action = "Check provider"
                target = params.get("provider") or params.get("model") or lowered_action
            else:
                if params and isinstance(params, dict):
                    target = str(list(params.values())[0]) if params.values() else ""
                elif params:
                    target = str(params)
                else:
                    target = ""
                
            # 2. Determine active phase by reading existing todo events from the file
            todo_events = []
            if os.path.exists(events_file):
                with open(events_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        try:
                            evt = json.loads(line)
                            if evt.get("kind") == "todo" and evt.get("phase_index") is not None:
                                todo_events.append(evt)
                        except:
                            continue
            
            # Sort todo events by phase_index
            todo_events.sort(key=lambda x: int(x.get("phase_index") or 0))
            
            phase_index = None
            phase_title = ""
            if todo_events:
                research_idx = 1
                impl_idx = 2
                verify_idx = len(todo_events)
                
                for i, e in enumerate(todo_events, 1):
                    title_lower = str(e.get("title") or "").lower()
                    if any(w in title_lower for w in ["research", "spec", "analyze", "design", "plan"]):
                        research_idx = i
                    if any(w in title_lower for w in ["implement", "code", "write", "create", "build", "develop", "patch"]):
                        impl_idx = i
                    if any(w in title_lower for w in ["verify", "test", "check", "run", "compile"]):
                        verify_idx = i
                        
                is_explicit = False
                target_lower = str(target).lower()
                basename = os.path.basename(target_lower)
                for e in todo_events:
                    for item in (e.get("items") or []):
                        item_lower = str(item).lower()
                        if target_lower in item_lower or (basename and basename in item_lower):
                            is_explicit = True
                            break
                    if is_explicit:
                        break

                if target_lower.endswith("todo.md") or action_name == "todo" or kind == "todo":
                    is_explicit = True

                if is_explicit:
                    if kind in ["search", "rag"]:
                        phase_index = research_idx
                    elif kind == "file":
                        phase_index = impl_idx
                    elif kind == "command":
                        phase_index = verify_idx
                    else:
                        phase_index = research_idx
                else:
                    phase_index = None
                    
                if phase_index is not None:
                    if phase_index <= len(todo_events):
                        phase_title = f"Phase {phase_index}: {todo_events[phase_index-1].get('title')}"
                    else:
                        phase_title = f"Phase {phase_index}: Work"
            
            # 3. Construct event
            if not event_id:
                event_id = f"evt_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
                
            payload = {
                "id": event_id,
                "session_id": session_id,
                "created_at": time.time(),
                "kind": kind,
                "type": kind,
                "action": action,
                "title": action,
                "target": target,
                "status": status,
            }
            if phase_index is not None:
                payload["phase_index"] = phase_index
                payload["phase"] = phase_title
                
            if output is not None:
                payload["output"] = output
                payload["result"] = output
                if kind == "command":
                    if status == "error":
                        payload["stderr"] = output
                    else:
                        payload["stdout"] = output
                
            # If it is a file event, read the content preview
            if kind == "file" and target:
                try:
                    abs_path = os.path.abspath(os.path.join(self.root, target))
                    if os.path.exists(abs_path) and os.path.isfile(abs_path):
                        payload["path"] = os.path.relpath(abs_path, self.root)
                        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                            payload["preview"] = f.read(20000)
                except:
                    pass
                    
            with open(events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
                
            # Also update todo checkmarks if status is done
            if status == "done" and phase_index is not None and kind not in ("todo", "planning_artifact") and payload.get("role") != "planning_artifact":
                try:
                    from gui.api import update_todo_file_and_states
                    update_todo_file_and_states(session_id, payload, "")
                except Exception as e:
                    self.logger.warning(f"Could not update todo file from loop: {e}")
                
            return event_id
        except Exception as e:
            self.logger.error(f"Failed to log work event: {e}")
            return None

    def _recent_memory_for_prompt(self) -> List[Dict[str, str]]:
        """Return a small, clean chat tail so stale smoke tests do not steer local models."""
        active_provider = getattr(getattr(self.kernel.moe.base_router, "provider", None), "provider_name", "")
        if active_provider in {"lm_studio", "ollama", "llama_cpp"} and os.environ.get("NEXUS_LOCAL_CHAT_MEMORY", "").lower() not in {"1", "true", "yes"}:
            return []

        noisy_markers = (
            "NEXUS_SHELL_OK",
            "NEXUS_PROVIDER_OK",
            "NEXUS_STREAM_OK",
            "provider smoke test",
            "health check of provider routing",
        )
        clean: List[Dict[str, str]] = []
        for item in self.memory[-12:]:
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if any(marker in content for marker in noisy_markers):
                continue
            clean.append({"role": item.get("role", "user"), "content": content[:2000]})
        return clean[-4:]


    def _observe_hive(self) -> List[str]:
        """[HIVE-TELEMETRY]: Pulls the latest signals from the hive blackboard."""
        try:
            signals = self.hive.get_live_signals()
            if not signals:
                hive_logs = os.path.join(self.root, "logs", "hive")
                if os.path.isdir(hive_logs):
                    for name in sorted(os.listdir(hive_logs)):
                        if not name.endswith(".log"):
                            continue
                        path = os.path.join(hive_logs, name)
                        try:
                            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                                lines = [line.strip() for line in f.readlines()[-3:] if line.strip()]
                            if lines:
                                signals.append(f"[{name}]: {' | '.join(lines)}")
                        except OSError:
                            continue
            new_signals = []
            for s in signals:
                if s not in self.hive_buffer:
                    # Filter for high-value signals
                    if s.endswith(".log") or ".log]:" in s or any(kw in s.upper() for kw in ["RESULT", "FAIL", "PASS", "BOOT", "DISCOVERY"]):
                        new_signals.append(s)
                        self.hive_buffer.append(s)
            return new_signals
        except Exception as e:
            self.logger.warning(f"Hive telemetry sync failed: {e}")
            return []

    def abort(self) -> None:
        self._abort_flag.set()

    def reset(self) -> None:
        self._abort_flag.clear()
        self.hive_buffer = []

    def run(self, task_desc: str, voice_mode: bool = False) -> str:
        result_parts = []
        for chunk in self.stream_run(task_desc, voice_mode=voice_mode):
            result_parts.append(chunk)
        return "".join(result_parts)

    def _should_continue_without_tools(self, response: str, turn: int) -> bool:
        """
        Decide whether a model response with no tool calls needs another loop turn.

        A normal assistant answer is complete even when a provider omits the
        literal TASK_COMPLETE marker. Continuing in that case makes chat feel
        stuck and can multiply slow provider calls.
        """
        text = (response or "").strip()
        if not text:
            return False
        if "TASK_COMPLETE" in text:
            return False
        if text.startswith("[PROVIDER_ERROR]") or text.lower().startswith("error:"):
            return False
        return False

    def stream_run(self, task_desc: str, provider: Optional[str] = None, model: Optional[str] = None, voice_mode: bool = False) -> Generator[str, None, None]:
        self._voice_mode = voice_mode
        self.in_planning_phase = False
        if provider:
            try:
                self.brain.set_override(provider)
                self.provider_override = provider
            except Exception as e:
                self.logger.warning(f"Failed to override brain provider to {provider}: {e}")
        if model:
            self.model = model
            try:
                active_provider = getattr(self.brain.base_router, "provider", None)
                if active_provider is not None and hasattr(active_provider, "model"):
                    active_provider.model = model
            except Exception:
                pass
        try:
            pre_grounding = self.rag.retrieve_as_text(task_desc, top_k=2)
        except Exception as e:
            self.logger.warning(f"RAG retrieval failed: {e}")
            pre_grounding = "No relevant matches found (System Constraint)."
        system = self._build_system_prompt(task_desc)

        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]

        if "No relevant matches" not in pre_grounding:
            messages.append(
                {
                    "role": "system",
                    "content": f"[AUTO-RECALL]: Facts retrieved from Long-Term Memory:\n{pre_grounding}",
                }
            )

        for m in self._recent_memory_for_prompt():
            messages.append(m)

        messages.append({
            "role": "system",
            "content": "The next user message is the current task. Answer it directly; do not continue or repeat older turns.",
        })
        if self.active_agent:
            messages.append({
                "role": "system",
                "content": f"[ACTIVE_AGENT]: {self.active_agent}. Use this configured agent/persona when interpreting and executing the current task.",
            })
        if self.active_goal:
            messages.append({
                "role": "system",
                "content": f"[ACTIVE_GOAL]: {self.active_goal}. Keep this goal in mind across turns. If the user's latest request conflicts with it, follow the latest request and explain the conflict.",
            })
        if self.additional_dirs:
            messages.append({
                "role": "system",
                "content": "[ADDITIONAL_WORKING_DIRECTORIES]:\n" + "\n".join(f"- {directory}" for directory in self.additional_dirs),
            })
        messages.append({"role": "user", "content": task_desc})

        last_response = ""
        turn = 0
        tool_turns = 0

        while turn < self.MAX_TURNS:
            if self._abort_flag.is_set():
                yield "\n[ABORTED]"
                return

            turn += 1

            # 👁️ [WORKSPACE_SENSING_DELTA]
            if turn > 1:
                delta = self._get_workspace_delta()
                if "Stable" not in delta:
                    messages.append({"role": "system", "content": f"[AUTO_OBSERVATION]: {delta}"})

            # Hive blackboard stays internal — do not leak ENGINEER/AUDITOR RESULT lines into chat.
            self._observe_hive()
            if len(self.hive_buffer) > 50:
                self.hive_buffer = self.hive_buffer[-20:]

            # ⚡ [AGI_PHASE]: Mission Planning (SOVEREIGN TRIGGER)
            if turn == 1 or self.force_reasoning:
                # 🧠 [INTENT_AWARE_LOOP]: Resolve high-fidelity intent
                intent_router = IntentRouter(self.brain.base_router)
                intent_res = intent_router.classify(task_desc)
                
                # Apply strategy from neural engine if possible
                from cognition.intent_engine import NexusIntent
                intent_val = intent_res.intent
                legacy_to_nexus = {
                    "code": NexusIntent.MISSION,
                    "file_ops": NexusIntent.UTILITY,
                    "research": NexusIntent.UTILITY,
                    "debug": NexusIntent.DIAGNOSTIC,
                    "git": NexusIntent.MISSION,
                    "test": NexusIntent.MISSION,
                    "hive": NexusIntent.MISSION,
                    "strategy": NexusIntent.COGNITION,
                    "chat": NexusIntent.SOCIAL,
                }
                if intent_val in [i.value for i in NexusIntent]:
                    nexus_intent = NexusIntent(intent_val)
                elif intent_val in legacy_to_nexus:
                    nexus_intent = legacy_to_nexus[intent_val]
                else:
                    nexus_intent = intent_router.neural_engine.classify(task_desc)
                strategy = intent_router.neural_engine.get_strategy(nexus_intent)
                
                self.MAX_TURNS = strategy.get("max_turns", 20)
                self.force_reasoning = strategy.get("force_reasoning", False)
                self.task_complexity = strategy.get("task_complexity", intent_res.complexity)

                # Only pay the legacy architect/hive startup cost when the
                # request actually needs complex tool orchestration.
                should_plan = not voice_mode and (self.force_reasoning or (intent_res.needs_tools and self.task_complexity == "complex"))
                if nexus_intent in {NexusIntent.SOCIAL, NexusIntent.COGNITION} and not intent_res.needs_tools:
                    should_plan = False
                if should_plan:
                    self.in_planning_phase = True
                    plan = self.architect.plan(task_desc)
                    self.task_complexity = "complex" if len(plan) > 1 else self.task_complexity
                    
                    # Create and save todo.md plan
                    todo_lines = ["## TODO List", "", f"Task: {task_desc}", ""]
                    for idx, goal in enumerate(plan, 1):
                        desc = goal.get("description") or goal.get("desc") or f"Sub-goal {idx}"
                        todo_lines.append(f"- [ ] Phase {idx}: {desc}")
                        todo_lines.append(f"  - [ ] Execute: {desc}")
                        todo_lines.append(f"  - [ ] Verify execution")
                    todo_content = "\n".join(todo_lines).strip() + "\n"
                    todo_path = os.path.join(self.root, "workspace", "todo.md")
                    os.makedirs(os.path.dirname(todo_path), exist_ok=True)
                    try:
                        with open(todo_path, "w", encoding="utf-8") as f:
                            f.write(todo_content)
                    except Exception as e:
                        self.logger.warning(f"Could not create planning todo.md: {e}")

                    yield "\n[SYSTEM: COMPLEX MISSION DETECTED - ACTIVATING FULL-AUTO HIVE-CAST]"
                    yield "\n[THINKING: Designing optimal hive trajectory...]"
                    
                    mission_map = self.architect.get_mission_map()
                    yield f"\n\033[96m{mission_map}\033[0m\n"
                    
                    # 🚀 [HIVE_CAST_DEPLOYMENT]
                    hive_status = self._hive_cast(mission_map)
                    yield f"\n\033[93m{hive_status}\033[0m\n"
                    
                    messages.append({"role": "system", "content": f"{mission_map}\n[HIVE_DEPLOYED]: Swarm is active and reporting to blackboard."})
                    
                    # Reset triggers
                    self.force_reasoning = False 
                else:
                    # High-speed Zero-Thinking Mode: delete todo.md plan
                    todo_path = os.path.join(self.root, "workspace", "todo.md")
                    if os.path.exists(todo_path):
                        try:
                            os.remove(todo_path)
                        except Exception:
                            pass

            full_response = ""

            try:
                for chunk in self.brain.stream_generate(messages=messages):
                    full_response += chunk
                    yield chunk

                if not full_response.strip():
                    fallback_response = self.brain.generate(messages=messages)
                    if fallback_response and not self.brain._looks_like_provider_error(fallback_response):
                        full_response = fallback_response
                        yield fallback_response

                last_response = full_response

                # 🚀 [v21.0 SOVEREIGN_EXECUTION]: Process turn with automated oversight
                tool_calls = self._extract_tool_calls(full_response)

                if not tool_calls:
                    messages.append({"role": "assistant", "content": full_response})
                    if not self._should_continue_without_tools(full_response, turn):
                        break
                    messages.append({"role": "system", "content": "[SYSTEM]: Continue only if another concrete tool/action turn is required. Otherwise output TASK_COMPLETE."})
                else:
                    for tc in tool_calls:
                        try:
                            marker_params = json.dumps(tc.params, ensure_ascii=False)
                        except Exception:
                            marker_params = "{}"
                        yield f"\n[TOOL_START:{tc.name}:{marker_params}]\n"

                    observations = self._execute_tools(tool_calls)

                    for obs in observations:
                        tool_name = "tool"
                        result_text = obs
                        match = re.match(r"^\[([^\]]+)\]:\s*(.*)$", obs, re.DOTALL)
                        if match:
                            tool_name = match.group(1)
                            result_text = match.group(2)
                        try:
                            marker_result = json.dumps(
                                {"output": result_text},
                                ensure_ascii=False,
                            )
                        except Exception:
                            marker_result = '{"output": ""}'
                        yield f"\n[TOOL_RESULT:{tool_name}:{marker_result}]\n"

                    for tc in tool_calls:
                        yield f"\n[TOOL_END:{tc.name}]\n"

                    messages.append({"role": "assistant", "content": full_response})
                    messages.append({"role": "system", "content": "\n".join(observations)})
                    messages = self._compact_memory(messages)
                    tool_turns += 1
                    if tool_turns >= 4 and all(
                        self.tool_registry.get(tc.name) and self.tool_registry.get(tc.name).is_read_only(tc.params)
                        for tc in tool_calls
                    ):
                        messages.append({
                            "role": "system",
                            "content": (
                                "[TOOL_LOOP_GUARD]: You have already used several read-only tools. "
                                "Stop calling tools now. Give the user the best concise answer from the observations, "
                                "including any uncertainty or concern."
                            ),
                        })

                self.in_planning_phase = False

                if "TASK_COMPLETE" in full_response:
                    break

            except Exception as e:
                self.in_planning_phase = False
                yield f"\n[ERROR]: {e}"
                # [SELF_HEAL]: Attempt to recover from kernel panics
                self.logger.critical(f"Loop failure: {e}")
                break
            
        self.memory.append({"role": "user", "content": task_desc})
        self.memory.append({"role": "assistant", "content": last_response})

        if len(self.memory) > 20:
            self.memory = self.memory[-10:]
            
        self.save_memory()

        # --- Post-task learning hooks ---
        if "TASK_COMPLETE" in last_response or "success" in last_response.lower():
            # 1. Procedural Memory (Skill)
            try:
                synth_res = self.synthesizer.synthesize_from_history(messages, task_desc)
                if synth_res:
                    yield f"\n\033[92m[{synth_res}]\033[0m"
            except Exception as e:
                self.logger.warning(f"Skill synthesis failed: {e}")
            
            # 2. Experiential memory (Fact Learning)
            try:
                learning_prompt = "MISSION_ARCHIVE: Extract the single most critical LESSON or DISCOVERY from this mission. Format: 'DISCOVERY: [Statement]'."
                lesson = self.brain.generate(prompt=learning_prompt, system_prompt=last_response)
                if "DISCOVERY:" in lesson:
                    f_res = self.vault.add_fact("NEXUS_EVOLUTION", "lesson_learned", lesson.strip())
                    yield f"\n\033[94m[{f_res}]\033[0m"
                    
                # ⚡ [v20.0 SOVEREIGN_AUTO_COLLECT]: Save to training dataset
                if len(messages) > 3:
                    train_file = os.path.join(self.root, "training_data", "live_evolution.json")
                    sample = {
                        "instruction": task_desc,
                        "context": messages[0]["content"], # System prompt
                        "response": last_response,
                        "timestamp": time.time()
                    }
                    try:
                        import json
                        existing = []
                        if os.path.exists(train_file):
                            with open(train_file, "r", encoding="utf-8") as f:
                                existing = json.load(f)
                        existing.append(sample)
                        with open(train_file, "w", encoding="utf-8") as f:
                            json.dump(existing, f, indent=2)
                        yield f"\n\033[90m[SYSTEM]: Interaction archived to Live Evolution Dataset.\033[0m"
                        
                        # 🧬 [EVOLUTION_MONITOR]: Check if we have enough data for a new cycle
                        if len(existing) >= 50 and len(existing) % 50 == 0:
                             yield f"\n\033[93m[ADVISORY]: NEXUS has collected {len(existing)} new high-fidelity interactions. A 'brain_trainer' cycle is recommended to fuse this knowledge into the GGUF core.\033[0m"
                        
                        # 🌐 [INFINITE_HISTORY]: Append to Global Memory for RAG
                        memory_dir = os.path.join(self.root, "logs", "memory")
                        os.makedirs(memory_dir, exist_ok=True)
                        memory_file = os.path.join(memory_dir, "global_history.md")
                        with open(memory_file, "a", encoding="utf-8") as f:
                            f.write(f"\n## SESSION: {self.session_id} | DATE: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                            f.write(f"### USER: {task_desc}\n")
                            f.write(f"### NEXUS: {last_response}\n")
                            f.write("---\n")
                        
                        # Trigger RAG index refresh for memory
                        self.rag.index_workspace(file_path=os.path.relpath(memory_file, self.root))
                        
                        # 🧠 [v20.0 BIG_BRAIN_REFINEMENT]: Use cloud to refine training data
                        if os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                            try:
                                yield f"\n\033[95m[EVOLUTION]: Engaging Big Brain for Neural Refinement...\033[0m"
                                refinement_prompt = (
                                    "MISSION_RECONSTRUCTION: Review the full interaction history below. "
                                    "Your task is to reconstruct this entire mission into a single, PERFECT "
                                    "Instruction-Response pair. The response must include the ideal reasoning "
                                    "and the correct sequence of tool actions (as JSON) that lead to success. "
                                    "Fix any errors or inefficiencies. Return ONLY a JSON object: "
                                    "{\"instruction\": \"...\", \"response\": \"...\"}"
                                )
                                # Send the full context (last 10 messages for depth)
                                history_context = json.dumps(messages[-10:], indent=2)
                                raw_data = f"FULL_MISSION_RECORD:\n{history_context}"
                                refined_json = self.brain.generate(prompt=raw_data, system_prompt=refinement_prompt, mode="heavy")
                                
                                if "{" in refined_json:
                                    refined_sample = json.loads(refined_json[refined_json.find("{"):refined_json.rfind("}")+1])
                                    refined_sample["timestamp"] = time.time()
                                    refined_sample["source"] = "synthetic_refinement"
                                    
                                    gold_file = os.path.join(self.root, "training_data", "gold_standard_agent.json")
                                    gold_data = []
                                    if os.path.exists(gold_file):
                                        with open(gold_file, "r") as f: gold_data = json.load(f)
                                    gold_data.append(refined_sample)
                                    with open(gold_file, "w") as f: json.dump(gold_data, f, indent=2)
                                    yield f"\n\033[92m[SUCCESS]: Gold Standard sample synthesized and archived.\033[0m"
                            except Exception as e:
                                self.logger.error(f"Synthetic refinement failed: {e}")
                    except Exception as e:
                        self.logger.error(f"Evolution archival failed: {e}")
                
                # 🧠 [EPISODIC_LOGGING]: Record this interaction in the project narrative
                try:
                    summary_prompt = "MISSION_DEBRIEF: Create a one-sentence summary of what we just achieved. Title: [Action]. Summary: [Result]."
                    debrief = self.brain.generate(prompt=summary_prompt, system_prompt=last_response)
                    title = "Mission Success"
                    summary = debrief
                    if ":" in debrief:
                        parts = debrief.split(":", 1)
                        title = parts[0].strip("[] ")
                        summary = parts[1].strip()
                    
                    self.memory_kernel.log_episode(
                        session_id=self.session_id,
                        title=title,
                        summary=summary,
                        content=last_response
                    )
                except Exception as e:
                    self.logger.warning(f"Episodic logging failed: {e}")
            except Exception:
                pass



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

    def boot_sync_index(self) -> None:
        self.logger.info("Synchronizing System Memory (Hybrid Index)...")
        self.lsp.index_workspace()
        self.rag.index_workspace()
