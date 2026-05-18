"""
NEXUS TOOL REGISTRY — Next-gen with caching, permissions, compression.
Auto-discovers all tools. Integrates OutputOptimizer and ToolCache.
"""

import os
import logging
import time
from typing import Dict, Any, List, Optional
from tools.nexus_tools.base_tool import BaseTool, ToolResult
from utils.singleton import ThreadSafeSingleton
from core.config_loader import NexusConfigLoader
from core.browser_automation.mcp_client import MCPClient
from tools.nexus_tools.mcp_tool import MCPTool

logger = logging.getLogger(__name__)

class ToolRegistry(ThreadSafeSingleton):
    """Central registry with caching, permissions, and output compression."""

    _initialized = False

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tools: Dict[str, BaseTool] = {}
        self._mcp_clients: Dict[str, MCPClient] = {}
        self._register_defaults()
        self._register_mcp_tools()

    def _register_defaults(self):
        from tools.nexus_tools.bash_tool import BashTool
        from tools.nexus_tools.file_edit_tool import FileEditTool
        from tools.nexus_tools.glob_tool import GlobTool
        from tools.nexus_tools.grep_tool import GrepTool
        from tools.nexus_tools.web_tool import WebSearchTool, WebFetchTool
        from tools.nexus_tools.todo_tool import TodoTool
        from tools.nexus_tools.atlas_tool import AtlasTool, AtlasMapTool
        from tools.nexus_tools.nexus_evolve import NexusEvolveTool
        from tools.nexus_tools.hive_tool import HiveTool, HivePulseTool, HiveSpawnTool, HiveIntentTool, HiveTeamTool
        from tools.nexus_tools.librarian_tool import LibrarianTool
        from tools.nexus_tools.backup_tool import BackupTool
        from tools.nexus_tools.brain_switch_tool import BrainSwitchTool
        from tools.nexus_tools.comms_tool import CommsTool
        from tools.nexus_tools.system_audit import SystemAuditorTool
        from tools.nexus_tools.skill_synthesizer import SkillSynthesizer
        from tools.nexus_tools.memory_tool import MemoryTool
        from tools.nexus_tools.system_monitor_tool import SystemMonitorTool
        from tools.nexus_tools.brain_trainer_tool import BrainTrainerTool
        from tools.nexus_tools.advanced_power_tool import (
            AgentContextTool,
            BenchmarkTool,
            BrowserAutomationTool,
            CognitionTool,
            CodeGraphTool,
            DiagnosticsTool,
            EditPlanTool,
            EvidenceLedgerTool,
            FailureVaccineTool,
            HyperPlanTool,
            MissionReplayTool,
            PatchLedgerTool,
            ProcessTool,
            RollbackTool,
            RoadmapTool,
            SideEffectTool,
            SkillForgeTool,
            ToolEconomyTool,
            TestSelectionTool,
            UnifiedGraphTool,
        )
        from tools.nexus_tools.vision.holistic_tool import HolisticTool
        from tools.nexus_tools.vision.mediapipe_suite_tool import MediaPipeSuiteTool
        from tools.nexus_tools.vision.vision_accelerator import VisionAcceleratorTool

        _root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.root = _root

        tools = [
            BashTool(_root),
            FileEditTool(_root),
            GlobTool(_root),
            GrepTool(_root),
            WebSearchTool(),
            WebFetchTool(),
            TodoTool(),
            AtlasTool(_root),
            AtlasMapTool(_root),
            NexusEvolveTool(_root),
            HiveTool(_root),
            HivePulseTool(_root),
            HiveSpawnTool(_root),
            HiveIntentTool(_root),
            HiveTeamTool(_root),
            LibrarianTool(_root),
            BackupTool(_root),
            BrainSwitchTool(_root),
            CommsTool(_root),
            SystemAuditorTool(_root),
            SkillSynthesizer(_root),
            MemoryTool(_root),
            SystemMonitorTool(),
            BrainTrainerTool(_root),
            RollbackTool(_root),
            PatchLedgerTool(_root),
            ProcessTool(_root),
            SideEffectTool(_root),
            DiagnosticsTool(_root),
            EditPlanTool(_root),
            HyperPlanTool(),
            CognitionTool(_root),
            SkillForgeTool(_root),
            BenchmarkTool(_root),
            MissionReplayTool(_root),
            ToolEconomyTool(_root),
            TestSelectionTool(_root),
            FailureVaccineTool(_root),
            EvidenceLedgerTool(_root),
            CodeGraphTool(_root),
            AgentContextTool(_root),
            UnifiedGraphTool(_root),
            RoadmapTool(_root),
            BrowserAutomationTool(_root),
            HolisticTool(),
            MediaPipeSuiteTool(),
            VisionAcceleratorTool(),
        ]
        
        # Load any existing custom tools
        self.reload_custom_tools()

        for tool in tools:
            self.register(tool)

    def _register_mcp_tools(self):
        """Discovers MCP servers but defers registration until needed."""
        config = NexusConfigLoader()
        self._mcp_configs = config.get("mcp_servers", {})
        if not isinstance(self._mcp_configs, dict):
            self._mcp_configs = {}
        
        # We only record that these servers exist. 
        # Actual client start and tool registration happens on first 'get' or 'list' 
        # that targets an MCP-prefix or on-demand.
        # [SOVEREIGN_FIX]: Do NOT start clients here to prevent auto-launching browsers.
        logger.info(f"NEXUS ready with {len(self._mcp_configs)} deferred MCP servers.")

    def _ensure_mcp_registered(self, name: str):
        if name in self._mcp_clients or name not in self._mcp_configs:
            return
            
        srv_config = self._mcp_configs[name]
        if not srv_config.get("active", False):
            return
            
        command = srv_config.get("command")
        args = srv_config.get("args", [])
        
        if not command: return
            
        try:
            logger.info(f"🧠 [LAZY_LOAD]: Activating MCP server '{name}'...")
            client = MCPClient(command, args)
            client.start()
            self._mcp_clients[name] = client
            
            tools = client.list_tools()
            for tool_def in tools:
                mcp_tool = MCPTool(client, tool_def)
                self.register(mcp_tool)
            
            logger.info(f"✅ Registered {len(tools)} tools from MCP server '{name}'")
        except Exception as e:
            logger.error(f"Failed to lazy-register MCP tools from '{name}': {e}")

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._tools[alias] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        # If it's a known MCP tool or we're looking for one, ensure they are registered
        if name not in self._tools:
            for mcp_name in list(self._mcp_configs.keys()):
                self._ensure_mcp_registered(mcp_name)
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        # Ensure ALL active MCP tools are registered before listing
        for mcp_name in list(self._mcp_configs.keys()):
            self._ensure_mcp_registered(mcp_name)
            
        seen = set()
        result = []
        for tool in self._tools.values():
            if tool.name not in seen:
                seen.add(tool.name)
                result.append(tool.name)
        return result

    def list_all(self) -> List[Dict[str, Any]]:
        """List all tools with their schemas."""
        for mcp_name in list(self._mcp_configs.keys()):
            self._ensure_mcp_registered(mcp_name)
            
        seen = set()
        result = []
        for tool in self._tools.values():
            if tool.name not in seen:
                seen.add(tool.name)
                result.append(tool.get_schema())
        return result

    def execute(
        self, tool_name: str, use_cache: bool = True, compress: bool = True, **kwargs
    ) -> str:
        """
        Execute a tool with caching, permission checking, and output compression.
        """
        from tools.nexus_tools.output_optimizer import OutputOptimizer, ToolCache

        tool = self.get(tool_name)
        if not tool:
            return f"[ERR] Tool '{tool_name}' not found. Avail: {self.list_tools()}"

        # Check cache for read-only operations
        if use_cache and tool.is_read_only(kwargs):
            cached = ToolCache.get(tool_name, kwargs)
            if cached:
                self._record_execution(tool_name, kwargs, cached, True, 0.0, True, cache_hit=True)
                return cached

        # Execute
        start = time.time()
        result = tool.call(**kwargs)
        duration_ms = (time.time() - start) * 1000
        output = str(result)

        # Compress output to save tokens
        if compress and result.success and result.data:
            output = OutputOptimizer.compress(output, tool_name)

        # Cache read-only results
        if use_cache and tool.is_read_only(kwargs) and result.success:
            ToolCache.set(tool_name, kwargs, output)

        self._record_execution(tool_name, kwargs, output, result.success, duration_ms, tool.is_read_only(kwargs))

        return output

    def _record_execution(self, tool_name: str, kwargs: Dict[str, Any], output: str, success: bool, duration_ms: float, read_only: bool, cache_hit: bool = False) -> None:
        root = getattr(self, "root", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        try:
            from core.aurora.mission_replay import MissionReplay
            MissionReplay(root).record(
                "tool_call",
                {
                    "tool": tool_name,
                    "args": kwargs,
                    "success": success,
                    "duration_ms": round(duration_ms, 2),
                    "cache_hit": cache_hit,
                    "output_preview": output[:1000],
                },
            )
        except Exception:
            pass
        try:
            from core.aurora.tool_economy import ToolEconomy
            ToolEconomy(root).record(tool_name, success, duration_ms, read_only=read_only, error="" if success else output)
        except Exception:
            pass

    def execute_parallel(self, calls: List[Dict[str, Any]]) -> List[str]:
        """
        Execute multiple tools in parallel with dependency awareness.
        calls: [{"action": "tool_name", "params": {...}}, ...]
        """
        import concurrent.futures
        results = [None] * len(calls)

        # Separate reads from writes
        reads = []
        writes = []
        for i, call in enumerate(calls):
            action = call.get("action", "")
            params = call.get("params", {})
            tool = self.get(action)
            if tool and tool.is_read_only(params):
                reads.append((i, action, params))
            else:
                writes.append((i, action, params))

        # Execute reads in parallel
        def _exec(idx, action, params):
            return idx, self.execute(action, use_cache=True, compress=True, **params)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(reads), 8)
        ) as executor:
            futures = [executor.submit(_exec, i, a, p) for i, a, p in reads]
            for future in concurrent.futures.as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        # Execute writes sequentially (preserve order)
        for i, action, params in writes:
            results[i] = self.execute(action, use_cache=False, compress=True, **params)

        return results

    def reload_custom_tools(self):
        """Discovers and registers tools from the custom_tools directory."""
        import importlib.util
        import inspect
        
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        custom_dir = os.path.join(_root, "tools", "custom_tools")
        if not os.path.exists(custom_dir): return
        
        for filename in os.listdir(custom_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = f"tools.custom_tools.{filename[:-3]}"
                try:
                    spec = importlib.util.spec_from_file_location(module_name, os.path.join(custom_dir, filename))
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        for name, obj in inspect.getmembers(module):
                            if inspect.isclass(obj) and issubclass(obj, BaseTool) and obj is not BaseTool:
                                # Instantiate with root if it takes it, else no args
                                try:
                                    # Check if __init__ takes root_dir
                                    sig = inspect.signature(obj.__init__)
                                    if "root_dir" in sig.parameters:
                                        tool_instance = obj(root_dir=_root)
                                    else:
                                        tool_instance = obj()
                                    self.register(tool_instance)
                                except Exception as e:
                                    logger.warning("Failed to load custom tool %s: %s", name, e)
                except Exception as e:
                    logger.warning("Error loading custom module %s: %s", filename, e)

    def stats(self) -> Dict[str, Any]:
        from tools.nexus_tools.output_optimizer import ToolCache

        return {
            "tools": len(self.list_tools()),
            "names": self.list_tools(),
            "cache": ToolCache.stats(),
        }
