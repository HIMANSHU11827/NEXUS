"""
NATE — NEXUS Native Tool Engine
8-layer fused runtime for universal tool calling.
Zero MCP overhead. Any model, any tool, any provider.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from nexus.capabilities.intelligence.nate.adaptive_schema import AdaptiveSchemaEngine
from nexus.capabilities.intelligence.nate.execution_graph import ExecutionGraph
from nexus.capabilities.intelligence.nate.gene_map import SelfHealingEngine
from nexus.capabilities.intelligence.nate.universal_adapter import UniversalAdapter, UniversalTool


class NATE:
    def __init__(self):
        try:
            self.adapter = UniversalAdapter()
            self.schema_engine = AdaptiveSchemaEngine()
            self.exec_graph = ExecutionGraph()
            self.healer = SelfHealingEngine()
        except Exception as e:
            logger.warning(f"NATE init failed: {e}")
            raise
        self._enabled_layers: Dict[str, bool] = {
            "universal_adapter": True,
            "adaptive_schema": True,
            "execution_graph": True,
            "self_healing": True,
        }
        self._metrics: Dict[str, Any] = {
            "total_calls": 0,
            "schema_tokens_saved": 0,
            "routing_llm_calls_saved": 0,
            "healing_llm_calls_saved": 0,
            "cache_hits": 0,
            "failures_handled": 0,
        }

    def register_tool(self, name: str, description: str = "", parameters: Optional[Dict] = None,
                      required: Optional[List[str]] = None, handler: Optional[Callable] = None,
                      cost: float = 1.0) -> None:
        tool = UniversalTool(name, description, parameters, required)
        self.adapter.register(tool)
        schema = tool.to_dict()
        self.schema_engine.register_tool(schema)
        self.exec_graph.add_tool(name, handler, cost)

    def register_tools(self, tools: List[Dict[str, Any]]) -> None:
        for t in tools:
            self.register_tool(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("parameters"),
                required=t.get("required", []),
                handler=t.get("handler"),
                cost=t.get("cost", 1.0),
            )

    def add_dependency(self, from_name: str, to_name: str, weight: float = 1.0) -> None:
        self.exec_graph.add_dependency(from_name, to_name, weight)

    def set_flow(self, start: str, goal: str) -> None:
        self.exec_graph.set_start(start)
        self.exec_graph.set_goal(goal)

    def register_healing_strategy(self, name: str, handler: Optional[Callable] = None) -> None:
        self.healer.register_strategy(name, handler)

    def record_tool_sequence(self, sequence: List[str]) -> None:
        self.healer.gene_map.record_call_sequence(sequence)

    def get_schemas(self, query: str, provider: str = "openai", top_k: int = 5) -> Dict[str, Any]:
        if not self._enabled_layers["adaptive_schema"]:
            all_tools = self.adapter.convert(provider)
            return {"all": all_tools}

        try:
            schema_result = self.schema_engine.get_schemas(query, top_k=top_k)
        except Exception as e:
            logger.warning(f"NATE schema loading failed: {e}")
            all_tools = self.adapter.convert(provider)
            return {"all": all_tools}
        raw_size = sum(len(json.dumps(t.to_dict())) for t in self.adapter.all())

        always_names = []
        for t in schema_result["always_loaded"]:
            if isinstance(t, dict):
                name = t.get("n")
                if not name:
                    name = t.get("name", "")
                always_names.append(name)
            else:
                always_names.append(t.name)
        lazy_names = []
        for t in schema_result["lazy_loaded"]:
            if isinstance(t, dict):
                name = t.get("n")
                if not name:
                    name = t.get("name", "")
                lazy_names.append(name)
            else:
                lazy_names.append(t.name)
        all_selected = always_names + lazy_names

        if not all_selected:
            route_info = schema_result.get("route_info", {})
            if route_info.get("path") == "no_tools":
                converted_tools = []
            else:
                converted_tools = self.adapter.convert(provider)
        else:
            converted_tools = self.adapter.convert(provider, names=all_selected)

        comp_size = sum(len(json.dumps(t)) for t in converted_tools)
        saved = raw_size - comp_size
        self._metrics["schema_tokens_saved"] += max(0, saved)
        return {
            "all": converted_tools,
            "routed": schema_result["routed"],
            "route_info": schema_result.get("route_info", {}),
        }

    def plan(self, start: Optional[str] = None, goal: Optional[str] = None) -> Tuple[Optional[List[str]], float]:
        if start and goal:
            self.exec_graph.set_start(start)
            self.exec_graph.set_goal(goal)
        if not self._enabled_layers["execution_graph"]:
            return None, 0.0
        path, cost = self.exec_graph.plan()
        self._metrics["routing_llm_calls_saved"] += 1
        return path, cost

    def execute(self, context: Optional[Dict] = None) -> Tuple[bool, List[str], List[Any]]:
        self._metrics["total_calls"] += 1
        success, executed, results = self.exec_graph.execute(context)
        if success:
            for name in executed:
                self.exec_graph.graph.mark_recovered(name)
            self.record_tool_sequence(executed)
        return success, executed, results

    def heal(self, failure_code: str, error: Any) -> Tuple[bool, str, str]:
        self._metrics["failures_handled"] += 1
        self._metrics["healing_llm_calls_saved"] += 1
        return self.healer.heal(failure_code, error)

    def convert_tools(self, provider: str = "openai", names: Optional[List[str]] = None) -> List[Dict]:
        return self.adapter.convert(provider, names)

    def router_stats(self) -> Dict[str, Any]:
        """Return NATE-Route embedding router stats."""
        return self.schema_engine.router.stats()

    def record_router_feedback(self, tool_name: str, query: str, success: bool) -> None:
        """Record OATS feedback for embedding refinement."""
        self.schema_engine.router.record_feedback(tool_name, query, success)

    def apply_oats_feedback(self, decay: float = 0.1) -> int:
        """Apply OATS embedding interpolation. Returns number of tools updated."""
        return self.schema_engine.router.apply_oats_feedback(decay)

    def stats(self) -> Dict[str, Any]:
        schema_stats = self.schema_engine.schema_stats()
        router = self.router_stats()
        return {
            "engine": "NATE-Route v1.0",
            "tools_registered": len(self.adapter.all()),
            "total_calls": self._metrics["total_calls"],
            "schema_tokens_saved": self._metrics["schema_tokens_saved"],
            "routing_llm_calls_saved": self._metrics["routing_llm_calls_saved"],
            "healing_llm_calls_saved": self._metrics["healing_llm_calls_saved"],
            "cache_hits": self._metrics["cache_hits"],
            "failures_handled": self._metrics["failures_handled"],
            "schema": {
                "raw_bytes": schema_stats["raw_bytes"],
                "compressed_bytes": schema_stats["compressed_bytes"],
                "savings_percent": schema_stats["savings_percent"],
            },
            "router": router,
            "exec_graph": self.exec_graph.stats(),
            "healer": self.healer.stats(),
        }

    def set_layer(self, layer: str, enabled: bool) -> None:
        if layer in self._enabled_layers:
            self._enabled_layers[layer] = enabled

    def before_after_report(self, query: str = "") -> Dict[str, Any]:
        all_tools = self.adapter.all()
        num_tools = len(all_tools)

        raw_tokens = sum(len(json.dumps(t.to_dict())) for t in all_tools)

        route_info = {}
        if query and self._enabled_layers["adaptive_schema"]:
            schema_result = self.schema_engine.get_schemas(query, top_k=5)
            always_names = []
            for t in schema_result.get("always_loaded", []):
                n = t.get("n")
                always_names.append(n if n else t.get("name", ""))
            lazy_names = []
            for t in schema_result.get("lazy_loaded", []):
                n = t.get("n")
                lazy_names.append(n if n else t.get("name", ""))
            selected_names = always_names + lazy_names
            selected_tools = [t for t in all_tools if t.name in selected_names]
            after_tokens = sum(len(json.dumps(t.to_dict())) for t in selected_tools) if selected_tools else raw_tokens
            route_info = schema_result.get("route_info", {})
        else:
            after_tokens = raw_tokens

        routing_calls_before = num_tools
        routing_calls_after = 0 if self._enabled_layers["execution_graph"] else routing_calls_before

        healing_calls_before = 3
        healing_calls_after = 0 if self._enabled_layers["self_healing"] else healing_calls_before

        schema_savings = round((1 - after_tokens / max(raw_tokens, 1)) * 100, 1)

        return {
            "before": {
                "schema_tokens": raw_tokens,
                "routing_llm_calls": routing_calls_before,
                "healing_llm_calls": healing_calls_before,
                "total_estimate": raw_tokens + (routing_calls_before * 100) + (healing_calls_before * 200),
            },
            "after": {
                "schema_tokens": after_tokens,
                "routing_llm_calls": routing_calls_after,
                "healing_llm_calls": healing_calls_after,
                "total_estimate": after_tokens + (routing_calls_after * 100) + (healing_calls_after * 200),
            },
            "savings_percent": {
                "schema": schema_savings,
                "routing": 100.0 if self._enabled_layers["execution_graph"] else 0.0,
                "healing": 100.0 if self._enabled_layers["self_healing"] else 0.0,
            },
            "route_info": route_info,
        }

    def __repr__(self):
        s = self.stats()
        return (f"NATE(tools={s['tools_registered']}, calls={s['total_calls']}, "
                f"schema_saved={s['schema_tokens_saved']}B, "
                f"routing_saved={s['routing_llm_calls_saved']}, "
                f"healing_saved={s['healing_llm_calls_saved']})")
