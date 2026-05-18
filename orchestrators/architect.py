import os
import re
import threading
import time
import platform
import subprocess
import concurrent.futures
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Iterator, Union

from core.discovery import NexusAutoDiscover
from core.router import IntentRouter
from core.prompts import NexusPromptEngine
from core.providers.router import ModelRouter
from core.tool_adapters import RegistryTerminalTool as TerminalTool
from core.tool_adapters import RegistryFileTools as NexusFileTools
from core.safety.prover import LogicProver
from rag.engine import NexusAtlasRAG
from core.tool_adapters import RegistryGitTools as NexusGitTools
from core.hive import NexusHiveEngine
from tools.reporter.script import NexusLSPTool
from core.tool_adapters import RegistryTestTool as NexusTestTool
from core.nexus_compat import s, sx, itail
from tools.nexus_tools.registry import ToolRegistry
from core.tasks import TaskManager, TaskType
from core.permissions import PermissionSystem, PermissionMode
from evolution.ensemble import EnsembleManager
from evolution.skill_synthesizer import SkillSynthesizer
from core.intelligence.moa import MixtureOfArchitects
from core.telemetry.database import NexusTelemetryDB
from core.observer import NexusObserver
from core.skills import NexusSkillMaster
from rag.atlas.engine import NexusAtlasEngine
from rag.atlas.mapper import AtlasCognitiveMapper
from knowledge.vault import KnowledgeVault
from core.kernel import get_nexus_kernel

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class C:
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    DARKCYAN = '\033[36m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    MAGENTA = '\033[35m'
    GRAY = '\033[90m'
    RESET = '\033[0m'

class NexusArchitect:
    """
    Legacy orchestration coordinator.
    Kept for compatibility while the unified loop owns the primary runtime path.
    """

    VAULT_IMPORTANCE_LIMIT: float = 1.0

    MAX_TURNS: int = 20

    discoverer: NexusAutoDiscover
    brain: ModelRouter
    terminal: TerminalTool
    files: NexusFileTools
    prover: LogicProver
    rag: NexusAtlasRAG
    git: NexusGitTools
    hive: NexusHiveEngine
    lsp: NexusLSPTool
    tester: NexusTestTool
    router: IntentRouter
    browser: Any
    tool_registry: ToolRegistry
    task_manager: TaskManager
    permissions: PermissionSystem
    ensemble: EnsembleManager
    atlas: NexusAtlasEngine
    mapper: AtlasCognitiveMapper
    observer: NexusObserver
    skill_manager: NexusSkillMaster
    skill_synthesizer: SkillSynthesizer
    vault: KnowledgeVault
    memory: List[Dict[str, str]]
    failure_counter: int
    hive_buffer: List[str]
    _log_path: str
    _hive_manifest_path: str
    _last_manifest_mtime: float

    def __init__(self) -> None:
        workspace = os.path.join(_ROOT, "workspace")
        logs_dir = os.path.join(_ROOT, "logs")
        os.makedirs(workspace, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)
        self._log_path = os.path.join(logs_dir, "nexus_ops.log")
        self.kernel = get_nexus_kernel()

        self.discoverer = NexusAutoDiscover(_ROOT)
        self.brain = ModelRouter()
        self.terminal = TerminalTool(_ROOT)
        self.files = NexusFileTools(_ROOT)
        
        # ⚡ [v18 BOOT_FIX]: Ensure attributes exist before background thread starts
        self._cached_system_prompt = None
        self._last_prompt_check = 0.0
        self.task_complexity = "simple"
        self.force_reasoning = False
        self.memory: List[Dict[str, str]] = []
        self.failure_counter = 0
        self.hive_buffer: List[str] = []
        self._last_manifest_mtime = 0.0
        self.moa = self.kernel.moa
        
        # ⚡ [v18 CORE_STABILITY]: Keep mission-critical tools in main thread
        self.router = IntentRouter()
        self.rag = NexusAtlasRAG()
        self.vault = KnowledgeVault()
        self.tool_registry = ToolRegistry()
        
        self.telemetry = NexusTelemetryDB()
        self.prover = LogicProver(strictness=0.8)
        self.git = NexusGitTools(_ROOT)
        self.hive = NexusHiveEngine(_ROOT)
        self.lsp = NexusLSPTool(_ROOT)
        self.tester = NexusTestTool(_ROOT)
        self.task_manager = TaskManager()
        self.permissions = PermissionSystem()
        self.ensemble = EnsembleManager(os.path.join(_ROOT, "workspace"))
        self.atlas = NexusAtlasEngine(_ROOT)
        self.mapper = AtlasCognitiveMapper(_ROOT)
        self.observer = NexusObserver(_ROOT)
        self.skill_manager = NexusSkillMaster(_ROOT)
        self.skill_synthesizer = SkillSynthesizer(_ROOT)
        self.atlas = NexusAtlasEngine(_ROOT)
        
        self._hive_manifest_path = os.path.join(
            _ROOT, "logs", "hive", "hive_manifest.json"
        )
        
        # ⚡ [v18 BOOT_OPTIMIZATION]: Background sync for non-blocking start
        from tools.browser.script import BrowserTool
        self.browser = BrowserTool()
        threading.Thread(target=self.safe_boot_sync, daemon=True).start()

    def plan(self, task: str) -> List[str]:
        """Strategic mission planning."""
        return [f"Execute mission: {task}"]

    def get_mission_map(self) -> str:
        """Returns a visual map of the mission."""
        return "NEXUS [DIRECT_EXECUTION_PATH] -> SUCCESS"

    def safe_boot_sync(self) -> None:
        """Safe background synchronization of system memory."""
        try:
            self.boot_sync_index()
        except Exception as e:
            # Silent failure for UX stability
            pass

    def _get_super_prompt(self, intent_hints: List[str] = None) -> str:
        """Cached super prompt to avoid redundant disk I/O and reconstruction."""
        now = time.time()
        if self._cached_system_prompt and (now - self._last_prompt_check) < 15.0 and not intent_hints:
            return self._cached_system_prompt
        
        self._cached_system_prompt = NexusPromptEngine.build_super_prompt(
            _ROOT, self.discoverer.get_context_map(), intent_hints=intent_hints
        )
        
        # ⚡ Shared Evolution Context
        insights = self.vault.retrieve_as_text("evolution project growth architecture", top_k=5)
        if "No relevant knowledge" not in insights:
            self._cached_system_prompt = f"{self._cached_system_prompt}\n\n[SHARED_PROJECT_EVOLUTION_VAULT]:\n{insights}"

        self._last_prompt_check = now
        return self._cached_system_prompt

    def _observe_hive(self) -> None:
        """RECURSIVE HIVE OBSERVER. Ingests sub-agent results into main brain."""
        hive_logs = os.path.join(_ROOT, "workspace", "hive_logs")
        if not os.path.exists(hive_logs):
            return

        try:
            for f in os.listdir(hive_logs):
                if f.endswith(".log"):
                    path = os.path.join(hive_logs, f)
                    mtime = os.path.getmtime(path)
                    if (time.time() - mtime) < 120.0:
                        with open(path, "r", encoding="utf-8") as f_obj:
                            lines = f_obj.readlines()
                            if lines:
                                last_few = "".join(lines[-10:])
                                msg = f"[HIVE_UPDATE: {f}]: {last_few}"
                                if msg not in self.hive_buffer:
                                    self.hive_buffer.append(msg)
        except (OSError, IOError):
            pass

    def coordinate_task(self, task_desc: str) -> str:
        """Execute the main cognitive loop for a task."""
        # Bypass LLM hallucinations for simple greetings.
        clean_task = task_desc.lower().strip().replace(".", "").replace("!", "")
        greetings = {
            "hello": "Hello. NEXUS is ready.",
            "hi": "Hi. NEXUS is ready.",
            "who are you": "I am NEXUS, a local-first autonomous engineering agent platform with direct tool execution, memory, retrieval, and verification.",
            "thanks": "You're welcome.",
            "thank you": "You're welcome."
        }
        if clean_task in greetings:
            return greetings[clean_task]

        self.failure_counter = 0
        self.hive_buffer = []

        pre_grounding = self.rag.retrieve_as_text(task_desc, top_k=2)
        
        # --- v17 INTENT-DRIVEN COMPACTION ---
        intent_res = self.router.classify(task_desc)
        intent_hints = intent_res.tool_hints
        
        # ⚡ [v19.1 COMPACT_LOCAL]: Use lightweight prompt for offline brains
        import os
        if os.environ.get("NEXUS_OFFLINE_MODE") == "true":
            from core.prompts import NexusPromptEngine
            system = NexusPromptEngine.build_local_prompt()
        else:
            system = self._get_super_prompt(intent_hints=intent_hints)

        # Inject dynamic skill prompt if active
        skill_prompt = self.skill_manager.get_active_prompt()
        if skill_prompt:
            system = f"{system}\n\n[ACTIVE_SKILL_OVERRIDE]:\n{skill_prompt}"

        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        if "No relevant matches" not in pre_grounding:
            messages.append(
                {
                    "role": "system",
                    "content": f"[AUTO-RECALL]: Facts retrieved from Long-Term Memory:\n{pre_grounding}",
                }
            )

        for m in self.memory:
            messages.append(m)
        messages.append({"role": "user", "content": task_desc})

        last_resp = ""
        for turn in range(1, self.MAX_TURNS + 1):
            self._observe_hive()
            
            # ⚡ [AGI_PHASE]: Mission Planning (SOVEREIGN TRIGGER)
            if turn == 1 or self.force_reasoning:
                # Detect complexity once
                self.task_complexity = self.router.classify(task_desc).complexity

                # --- v21 AUTONOMOUS SWARM ESCALATION ---
                if self.task_complexity == "complex" and not intent_hints:
                    print(f"{C.MAGENTA}[NEXUS_SCALING]: Complexity threshold exceeded. Activating Hive Intelligence...{C.RESET}")
                    escalation_result = self._run_tool("hive_auto_delegate", {"task": task_desc})
                    print(f"\n\033[95m[HIVE_ESCALATION]: {escalation_result}\033[0m\n")
                    # After spawning the hive, we can either wait or continue. 
                    # For now, we continue to monitor the hive logs in the background.
                
                # Check for manual toggle or extreme initial complexity
                should_plan = self.force_reasoning or (self.task_complexity == "complex")
                
                if should_plan:
                    planning_prompt = f"PLAN_MISSION: Analyze the task and describe the internal state, potential risks, and the most robust tool chain. Goal: {task_desc}"
                    planning_resp = self.brain.generate(prompt=planning_prompt, system_prompt=system)
                    messages.append({"role": "system", "content": f"[MISSION_STRATEGY]: {planning_resp}"})
                    
                    self.force_reasoning = False
                    
                # --- v11 HYPER_KERNEL SOP INJECTION ---
                task_type = self.router.classify(task_desc).task_type
                sop = self.kernel.hyper.load_sop(task_type)
                if sop:
                    messages.append({"role": "system", "content": f"[SOP_PROTOCOL]:\n{sop}"})

            if self.hive_buffer:
                messages.append(
                    {"role": "system", "content": "\n".join(self.hive_buffer)}
                )
                self.hive_buffer = []

            # 🌐 [HIVE_COLLECTIVE_RECALL]
            signals = self.hive.get_live_signals()
            if signals:
                messages.append({"role": "system", "content": "[HIVE_CONTEXT]: Live signals from agent nodes:\n" + "\n".join(signals)})

            response = self.brain.generate(messages=messages, mode="smart")
            self.observer.log_reasoning_step(response, turn)
            last_resp = response

            queue = self._extract_tool_calls(response)

            # 🛡️ [RED_TEAM_AUDIT]: Adversarial Self-Correction
            high_impact = [call for call in queue if call[0] in ("file_edit", "mutate_code", "nexus_evolve") and call[1].get("command") not in ("view", "read")]
            if high_impact:
                audit_prompt = f"RED_TEAM_AUDIT: Critically review these proposed system changes: {high_impact}. Respond with 'APPROVED' or 'REJECTED: [Reason]'."
                audit_resp = self.brain.generate(prompt=audit_prompt, system_prompt="You are the NEXUS Red-Team Security Auditor.", mode="fast")
                if "REJECTED" in audit_resp:
                    print(f"\033[91m[SECURITY_BLOCK]: {audit_resp}\033[0m")
                    self.hive_buffer.append(f"[AUDIT_REJECTION]: {audit_resp}")
                    # Remove high-impact calls from queue
                    queue = [q for q in queue if q not in high_impact]

            if not queue:
                break
            
            # Subtle indicator of activity
            print(f"\033[90m[NEXUS]: Executing {len(queue)} operation(s)...\033[0m")

            observations: List[str] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(self._run_tool, t[0], t[1]): t for t in queue
                }
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    observations.append(res)
            
            # Subtle indicator that we are progressing
            print(f"\033[90m└─ [COMPLETED]: {len(observations)} tool execution(s).\033[0m")

            messages.append({"role": "assistant", "content": response})
            
            # ⚡ [REFLECTION_PHASE]: Detect failures and pivot
            error_streak = [obs for obs in observations if "[TOOL_ERROR]" in obs or "[FAILURE]" in obs]
            if error_streak:
                self.failure_counter += 1
                reflection_prompt = f"""[SOVEREIGN_FAILURE_ANALYSIS]:
Multiple tools failed or returned errors: {error_streak}.
Failure Count: {self.failure_counter}
As the God-Architect, you have the power to SELF-REPAIR.
If a tool logic is flawed, consider using 'file_edit' to fix the script or 'nexus_evolve' to analyze the codebase.
ADJUST STRATEGY: What is the root cause? How will you fix the tool and retry?"""
                
                # 🛠️ [AUTONOMOUS_TOOL_REPAIR]: If failures persist, target the most problematic tool
                if self.failure_counter >= 3:
                    print(f"\033[91m[CRITICAL]: Repeated failures detected. Activating Recursive Tool Repair...\033[0m")
                    t_name = re.findall(r"\[([\w_]+)\]:", str(error_streak[0]))[0] if "[" in str(error_streak[0]) else "unknown"
                    repair_task = f"FIX_TOOL: Investigating and fixing performance failure in tool '{t_name}'. Error: {error_streak[0]}"
                    messages.append({"role": "system", "content": f"[RECURSIVE_REPAIR_TRIGGERED]: {repair_task}"})
                    self.failure_counter = 0 # Reset for the repair attempt

                reflection_resp = self.brain.generate(prompt=reflection_prompt, system_prompt=system)
                messages.append({"role": "system", "content": f"[SYSTEM_REFLECTION]: {reflection_resp}"})

            messages.append({"role": "system", "content": "\n".join(observations)})
            if "TASK_COMPLETE" in response:
                break

        self.memory.append({"role": "user", "content": task_desc})
        self.memory.append({"role": "assistant", "content": last_resp})
        
        # Post-task learning hook.
        if "TASK_COMPLETE" in last_resp:
            if len(messages) > 10:
                self.skill_synthesizer.synthesize_from_history(messages, task_desc)
            
            # --- NEURAL REINFORCEMENT (Backprop) ---
            task_type = self.router.classify(task_desc).task_type
            for m in messages:
                if m.get("role") == "assistant" and "TOOL_CALL" in str(m.get("content", "")):
                    # Simple regex to find tool names in response
                    tools_used = re.findall(r"TOOL_CALL: ([\w_]+)", str(m.get("content", "")))
                    for t_name in tools_used:
                        self.kernel.nerve.reinforce(task_type, t_name, 0.1)
        
        else:
            # Research/development trigger.
            gaps = self.kernel.researcher.identify_gaps([{"tool": "last_run", "success": False}])
            if gaps:
                import asyncio
                topic = f"Systemic failure in tools during task: {task_desc}"
                threading.Thread(target=lambda: asyncio.run(self.kernel.researcher.run_discovery_mission(topic)), daemon=True).start()

        return last_resp

    def _run_tool(
        self, action: str, params: Union[Dict[str, Any], Tuple[Any, ...]]
    ) -> str:
        """Unified tool dispatcher with caching and parallel support."""
        start_time = time.time()
        try:
            from tools.nexus_tools.output_optimizer import ToolCache, OutputOptimizer

            # Normalize params if they are just a string (legacy support)
            if isinstance(params, str):
                if action == "bash": p = {"cmd": params}
                elif action == "rag": p = {"query": params}
                elif action == "lsp": p = {"symbol": params}
                elif action == "test": p = {"path": params}
                elif action == "git": p = {"cmd": params}
                else: p = {}
            elif isinstance(params, dict):
                p = params
            elif isinstance(params, tuple):
                if action == "bash": p = {"cmd": params[0]}
                elif action == "file_edit": p = {"path": params[0], "old": params[1], "new": params[2]}
                elif action == "file_write": p = {"path": params[0], "content": params[1]}
                elif action == "git": p = {"cmd": params[0]}
                elif action == "rag": p = {"query": params[0]}
                elif action == "lsp": p = {"symbol": params[0]}
                elif action == "test": p = {"path": params[0]}
                elif action == "atlas_map": p = {"dir": params[0]}
                elif action == "nexus_evolve": p = {"mode": params[0], "patch": params[1] if len(params) > 1 else None}
                elif action == "hive": p = {"agent_type": params[0], "task": params[1]}
                elif action == "use_skill": p = {"name": params[0]}
                elif action == "craft_skill": p = {"name": params[0], "prompt": params[1]}
                else: p = {}
            else:
                p = {}

            cacheable = action not in ("bash", "file_edit", "file_write", "git")
            if cacheable:
                cached = ToolCache.get(action, p)
                if cached:
                    res = cached
                else:
                    res = self._dispatch_action(action, p)
            else:
                res = self._dispatch_action(action, p)
            
            self.telemetry.log_tool_call(action, p, res, True, time.time() - start_time)

        except Exception as e:
            res = f"[TOOL_ERROR]: {e}"
            self.telemetry.log_tool_call(action, p, res, False, time.time() - start_time)

        self.observer.log_tool_execution(action, p, res, time.time() - start_time)
        return res

    def _dispatch_action(self, action: str, p: Dict[str, Any]) -> str:
        """Helper to dispatch normalized parameters to tools."""
        if action == "bash":
            cmd = p.get("cmd", "")
            if cmd.startswith("cd "):
                target = cmd.replace("cd ", "").strip()
                new_path = os.path.abspath(os.path.join(self.terminal.root, target))
                if os.path.exists(new_path):
                    self.terminal.root = new_path
                    return f"[CWD_CHANGED]: Now in {self.terminal.root}"
                return f"[CWD_ERROR]: Folder {target} not found."
            return self.terminal.execute_stream(cmd)


        if action == "bash_bg":
            cmd = p.get("cmd", "")
            pid = p.get("pid", "task_main")
            return self.terminal.spawn(cmd, pid)

        if action == "bash_parallel":
            cmds = p.get("commands", [])
            pids = p.get("pids", [])
            results = []
            for c, pid in zip(cmds, pids):
                results.append(self.terminal.spawn(c, pid))
            return "\n".join(results)

        if action == "bash_poll":
            pid = p.get("pid", "")
            return self.terminal.poll(pid)

        if action in ("file_edit", "file", "editor", "file_ops"):
            path = p.get("path")
            old = p.get("old")
            new = p.get("new")
            command = p.get("command", "view")
            
            # If the model uses 'read' instead of 'view'
            if command == "read": command = "view"
            
            if command == "view":
                return self.files.read_file(path)
                
            # --- V10 OMNI_VERIFICATION BARRIER ---
            import asyncio
            is_valid, reason = asyncio.run(self.kernel.omni.validate_mutation(path, old, new))
            if not is_valid:
                return f"[VERIFICATION_FAILED]: {reason}"
            
            # Create safety chromosome before patch
            self.kernel.omni.archive_state(f"Surgical patch: {path}")
            
            # --- v16 LOG TO SELF-CREATION DATABASE ---
            self.kernel.nerve.log_mutation(path, "file_edit", f"Autonomous patch for {path}")
            
            res = self.files.edit_file(path, old, new)
            if "SUCCESS" in res:
                self.lsp.index_file(p.get("path"))
                self.rag.index_workspace(file_path=p.get("path"))
                return f"{res}\n[AUTO-SYNC]: Index updated for {p.get('path')}"
            return res
        if action == "file_write":
            path = p.get("path")
            # --- v16 LOG TO SELF-CREATION DATABASE ---
            self.kernel.nerve.log_mutation(path, "file_write", f"Autonomous creation of {path}")
            
            res = self.files.write_file(path, p.get("content"))
            self.lsp.index_file(p.get("path"))
            self.rag.index_workspace(file_path=p.get("path"))
            return f"{res}\n[AUTO-SYNC]: Index updated for {p.get('path')}"
        if action in ("file_read", "read_file", "view_file"):
            return self.files.read_file(p.get("path"))
        if action == "web_search":
            return self.browser.search(p.get("query"))
        if action == "read_url":
            return self.browser.read_url(p.get("url"))
        if action == "rag":
            query = p.get("query")
            atlas_res = self.atlas.atlas_retrieve(query)
            return f"### [NEXUS ATLAS RAG ACTIVE]\n{atlas_res}"
        if action == "atlas_map":
            return self.mapper.map_directory(p.get("dir", "."))
        if action == "nexus_evolve":
            # --- V10 OMNI_EVOLVE ENHANCEMENT ---
            if p.get("mode") in ("apply", "improve"):
                self.kernel.omni.archive_state(f"System Evolution: {p.get('mode')}")
            return self.tool_registry.execute("nexus_evolve", **p)
        if action == "lsp":
            return self.lsp.find_symbol(p.get("symbol"))
        if action == "test":
            return self.tester.run_tests(p.get("path", "."))
        if action == "git":
            cmd = p.get("cmd", "")
            if cmd.startswith("git "):
                cmd = cmd[4:].strip()
            return self.git.execute(cmd)
        if action == "hive":
            return self.hive.spawn_agent(p.get("task", ""), p.get("persona", "WORKER"))
        if action == "hive_hive":
            return self.hive.spawn_hive(p.get("tasks", []), p.get("persona", "WORKER"))
        if action == "hive_report":
            return self.hive.consolidate_hive(p.get("hive_id", ""))
        if action == "hive_control":
            self.hive.post_to_blackboard("ARCHITECT", p.get("hive_id", ""), p.get("directive", ""))
            return f"[HIVE_CONTROL]: Signal broadcasted to {p.get('hive_id')}."
        if action == "use_skill":
            name = p.get("name", "")
            if self.skill_manager.load_skill(name):
                return f"[SKILL_ACTIVE]: NEXUS Brain swapped to '{name}'. The skill will apply to the NEXT turn."
            return f"[SKILL_ERROR]: Could not find skill '{name}'."
        if action == "craft_skill":
            return self.skill_manager.craft_skill(p.get("name"), p.get("prompt"))
        if action == "scan_skills":
            deep = p.get("deep", False)
            if deep:
                return json.dumps(self.skill_manager.deep_scan(), indent=2)
            return json.dumps(self.skill_manager.list_skills(), indent=2)
        if action == "delete_skill":
            return self.skill_manager.delete_skill(p.get("name"))
        
        if action == "learn":
            insight = p.get("insight", "")
            cat = p.get("category", "architect_discovery")
            imp = float(p.get("importance", 7.0))
            return self.vault.add_fact("ARCHITECT_SHELL", cat, insight, imp)

        if action == "moa_solve":
            task = p.get("task", "")
            import asyncio
            return asyncio.run(self.moa.solve(task))

        if action == "list_insights":
            stats = self.telemetry.get_stats()
            return f"### [SYSTEM_INSIGHTS]:\n{json.dumps(stats, indent=2)}"

        if action == "local_vision_grounding":
            path = p.get("path")
            return str(self.kernel.local_brain.scan_image(path))

        if action in ("glob", "grep", "web_search", "web_fetch", "todo"):
            return self.tool_registry.execute(action, **p)
        
        return f"[UNKNOWN_TOOL]: {action}"

    def _extract_tool_calls(self, response: str) -> List[Tuple[str, Any]]:
        """Extract tool calls from response using both JSON and legacy patterns."""
        queue: List[Tuple[str, Any]] = []

        # 1. Try to find JSON code blocks
        for m in re.finditer(r"```json\s+(.*?)```", response, re.DOTALL):
            try:
                tool_call = json.loads(m.group(1))
                if isinstance(tool_call, dict):
                    action = tool_call.get("action")
                    params = tool_call.get("params", {})
                    if action:
                        queue.append((action, params))
            except:
                pass
        
        # 2. Try to find raw JSON if no queue yet
        if not queue:
            try:
                # Look for something that looks like an action/params object
                # Greedy match from first { to last } 
                raw_json_match = re.search(r'\{.*"action":\s*".*?\".*\}', response, re.DOTALL)
                if raw_json_match:
                    tool_call = json.loads(raw_json_match.group(0))
                    action = tool_call.get("action")
                    params = tool_call.get("params", {})
                    if action:
                        queue.append((action, params))
            except:
                pass

        queue.extend(
            [
                ("bash", {"cmd": m.group(1).strip()})
                for m in re.finditer(r"```bash\s*(.*?)```", response, re.DOTALL)
            ]
        )
        queue.extend(
            [
                ("file_edit", (m.group(1), m.group(2), m.group(3)))
                for m in re.finditer(
                    r"EDIT_FILE\(['\"](.*?)['\"]\s*,\s*['\"](.*?)['\"]\s*,\s*['\"](.*?)['\"]\)",
                    response,
                )
            ]
        )
        queue.extend(
            [
                ("file_write", (m.group(1), m.group(2)))
                for m in re.finditer(
                    r"WRITE_FILE\(['\"](.*?)['\"]\s*,\s*['\"](.*?)['\"]\)",
                    response,
                    re.DOTALL,
                )
            ]
        )
        queue.extend(
            [
                ("git", m.group(1))
                for m in re.finditer(r"GIT_CMD\(['\"](.*?)['\"]\)", response)
            ]
        )
        queue.extend(
            [
                ("rag", m.group(1))
                for m in re.finditer(r"RAG_QUERY\(['\"](.*?)['\"]\)", response)
            ]
        )
        queue.extend(
            [
                ("lsp", m.group(1))
                for m in re.finditer(r"LSP_CHECK\(['\"](.*?)['\"]\)", response)
            ]
        )
        queue.extend(
            [
                ("test", m.group(1))
                for m in re.finditer(r"RUN_TESTS\(['\"](.*?)['\"]\)", response)
            ]
        )
        queue.extend(
            [
                ("hive", (m.group(1), m.group(2)))
                for m in re.finditer(
                    r"SWARM_SPAWN\(['\"](.*?)['\"]\s*,\s*['\"](.*?)['\"]\)", response
                )
            ]
        )

        return queue

    def stream_coordinate(self, task_desc: str) -> Iterator[str]:
        """Streaming version of the cognitive loop."""
        # Bypass LLM for simple greetings.
        clean_task = task_desc.lower().strip().replace(".", "").replace("!", "")
        greetings = {
            "hello": "Hello. NEXUS is ready.",
            "hi": "Hi. NEXUS is ready.",
            "who are you": "I am NEXUS, a local-first autonomous engineering agent platform with direct tool execution, memory, retrieval, and verification.",
            "thanks": "You're welcome.",
            "thank you": "You're welcome."
        }
        if clean_task in greetings:
            yield greetings[clean_task]
            return

        self.failure_counter = 0
        system = self._get_super_prompt()
        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        for m in self.memory:
            messages.append(m)
        user_msg = {"role": "user", "content": task_desc}
        messages.append(user_msg)
        self.memory.append(user_msg)

        for turn in range(1, self.MAX_TURNS + 1):
            self._observe_hive()
            
            # ⚡ [AGI_PHASE]: Mission Planning (SOVEREIGN TRIGGER)
            if turn == 1 or self.force_reasoning:
                self.task_complexity = self.router.classify(task_desc).complexity
                should_plan = self.force_reasoning or (self.task_complexity == "complex")
                
                if should_plan:
                    planning_prompt = f"PLAN_MISSION: Analyze the task and describe the internal state, potential risks, and the most robust tool chain. Goal: {task_desc}"
                    planning_resp = self.brain.generate(prompt=planning_prompt, system_prompt=system)
                    messages.append({"role": "system", "content": f"[MISSION_STRATEGY]: {planning_resp}"})
                    self.force_reasoning = False

            if self.hive_buffer:
                messages.append(
                    {"role": "system", "content": "\n".join(self.hive_buffer)}
                )
                self.hive_buffer = []

            full_resp = ""
            for chunk in self.brain.stream_generate(messages=messages):
                full_resp += chunk
                yield chunk

            queue = self._extract_tool_calls(full_resp)

            if not queue:
                break

            yield "\n\033[90m[* Processing Tools...]\033[0m\n"
            observations: List[str] = []
            
            # Concurrency Control: Separate thread-safe from thread-sensitive tools
            safe_calls = []
            unsafe_calls = []
            for t in queue:
                tool = self.tool_registry.get(t[0])
                if tool and tool.is_concurrency_safe(t[1]):
                    safe_calls.append(t)
                else:
                    unsafe_calls.append(t)

            # 1. Execute thread-safe tools in parallel
            if safe_calls:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(safe_calls)) as executor:
                    futures = {executor.submit(self._run_tool, t[0], t[1]): t for t in safe_calls}
                    for f in concurrent.futures.as_completed(futures):
                        res = f.result()
                        observations.append(res)
                        yield f"\033[90m[OBS_PARALLEL]: {res[:150]}...\033[0m\n"

            # 2. Execute thread-sensitive tools sequentially
            for t in unsafe_calls:
                res = self._run_tool(t[0], t[1])
                observations.append(res)
                yield f"\033[90m[OBS_SEQUENTIAL]: {res[:150]}...\033[0m\n"

            messages.append({"role": "assistant", "content": full_resp})
            # Also update long-term session memory
            self.memory.append({"role": "assistant", "content": full_resp})

            # ⚡ [REFLECTION_PHASE]: Detect failures
            error_streak = [obs for obs in observations if "[TOOL_ERROR]" in obs or "[FAILURE]" in obs]
            if error_streak:
                reflection_prompt = f"""[SOVEREIGN_FAILURE_ANALYSIS]:
Tool failure detected: {error_streak}.
As the God-Architect, you have the power to SELF-REPAIR.
Consider using 'file_edit' to fix the script or 'nexus_evolve' to analyze the codebase.
ADJUST STRATEGY: What happened and how will you fix it?"""
                reflection_resp = self.brain.generate(prompt=reflection_prompt, system_prompt=system)
                messages.append({"role": "system", "content": f"[SYSTEM_REFLECTION]: {reflection_resp}"})
                yield f"\n\033[91m[REFLECTING]: {reflection_resp[:100]}...\033[0m\n"

            system_feedback = "\n".join(observations)
            messages.append({"role": "system", "content": system_feedback})
            self.memory.append({"role": "system", "content": system_feedback})

            if "TASK_COMPLETE" in full_resp:
                # ⚡ [EVOLUTION_TRIGGER]
                if len(messages) > 10:
                    yield f"\n{C.MAGENTA}[EVOLUTION]: Synthesizing procedural memory...{C.RESET}\n"
                    self.skill_synthesizer.synthesize_from_history(messages, task_desc)
                break
        
        self._compact_history()

    def boot_sync_index(self, silent: bool = True) -> None:
        """Ensures the system memory is not stale on boot."""
        if not silent: print("[*] Synchronizing System Memory (Hybrid Index)...")
        try:
            self.lsp.index_workspace()
            self.rag.index_workspace()
            self.atlas.refresh_index()
        except: pass

    def _compact_history(self) -> None:
        """Persistent record compaction."""
        if len(self.memory) > 30: # Allow more history before compacting
            self.memory = self.memory[-15:]
            print("\n\n\033[90m[*] Context optimized.\033[0m")
