"""Generate compact project context files for coding agents."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Dict, Iterable, List

from code_intel.knowledge_graph import CodebaseKnowledgeGraph, CodeGraph


DEFAULT_TARGETS = ("NEXUS.md",)


@dataclass
class ContextWriteResult:
    target: str
    status: str
    path: str
    bytes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "status": self.status,
            "path": self.path,
            "bytes": self.bytes,
        }


class AgentContextGenerator:
    """Create NEXUS.md from verified repo structure."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)
        self.graph = CodebaseKnowledgeGraph(self.root)

    def generate(self, target: str = "NEXUS.md", graph: CodeGraph | None = None) -> str:
        graph = graph or self._load_or_build_graph()
        summary = self.graph.summary(graph, limit=12)
        title = "NEXUS AI Agent Context"
        if os.path.basename(target).upper() == "CLAUDE.MD":
            title = "NEXUS AI Claude Context"

        return "\n".join(
            [
                f"# {title}",
                "",
                "This file is generated from the local NEXUS code graph. Keep it concise, factual, and easy for coding agents to obey.",
                "",
                "## Project Identity",
                "",
                "- NEXUS AI is a local-first autonomous engineering agent platform for direct system control, coding workflows, RAG, memory, provider routing, tools, and gui operations.",
                "- The product direction is fast autonomous execution with intelligent safeguards: command risk scoring, rollback, evidence logging, diagnostics, and recovery instead of approval friction.",
                "- Treat claims as untrusted until backed by source code, tests, command output, or persisted evidence.",
                "",
                "## Architecture Snapshot",
                "",
                "*This snapshot comes from `workspace/code_graph.json`; refresh it with `code_graph build` or `nexus-mcp` graph tools after meaningful code changes.*",
                "",
                f"- Graph nodes: {summary.get('nodes', 0)}",
                f"- Graph edges: {summary.get('edges', 0)}",
                f"- Node kinds: {self._format_counts(summary.get('by_kind', {}))}",
                f"- Edge kinds: {self._format_counts(summary.get('edge_kinds', {}))}",
                f"- Built at: {self._format_time(summary.get('built_at'))}",
                "",
                "### High-Signal Hubs",
                "",
                "* " + "\n* ".join(self._format_hubs(summary.get("top_hubs", []))),
                "",
                "## Core Working Areas",
                "",
                "- `core/`: kernel, config, providers, safety, cognition, code intelligence, evaluation, OS power, telemetry, and advanced agent systems.",
                "- `tools/nexus_tools/`: tool registry and callable agent tools, including shell, file edit, RAG, graph, unified graph, evidence, rollback, process, diagnostics, and benchmarks.",
                "- `orchestrators/`: planning and execution loops that coordinate agents, tools, prompts, and long-running work.",
                "- `rag/` and `knowledge/`: retrieval, indexing, memory, and knowledge ingestion surfaces.",
                "- `integrations/`: external protocol integrations, including the MCP stdio code graph server.",
                "- `gui/`: frontend/gui experience and API integration.",
                "- `tests/`: regression coverage for core behavior, tools, providers, MCP, safety, and next-gen systems.",
                "",
                "## Commands",
                "",
                "- Full tests: `python -m pytest -q`",
                "- Targeted next-gen tests: `python -m pytest tests\\test_nextgen_power.py -q`",
                "- Compile check: `python -m compileall -q core orchestrators tools rag knowledge utils integrations gui\\api.py nexus.py shell.py`",
                "- gui build: `cd gui && npm run build`",
                "- Benchmark: `python -c \"from evaluation.benchmark import BenchmarkRunner; import json; print(json.dumps(BenchmarkRunner('.').run(), indent=2))\"`",
                "- MCP server: `python -m mcp.server` or installed entry point `nexus-mcp`",
                "",
                "## Agent Tooling",
                "",
                "- Use `code_graph` before broad edits to search symbols, inspect dependencies, and find dependents without reading giant files.",
                "- Use `unified_graph` to connect code, memory, evidence, mission/session events, tool metrics, benchmarks, todos, strategies, and agent context files.",
                "- Use Hive contracts and handoff packets for delegated work so Hive workers receive scoped objectives, constraints, required outputs, and artifact pointers instead of raw history.",
                "- Use `evidence_ledger` to record important claims with proof, especially after tests, audits, or risky fixes.",
                "- Use `rollback` or `patch_ledger` before high-risk multi-file edits.",
                "- Use `diagnostics`, `test_select`, and full tests to verify behavior after code changes.",
                "- Use `browser status`, `browser fetch`, and optional Playwright-backed `browser run_sequence` for rendered frontend checks, screenshots, and action logs.",
                "- Use `agent_context preview` to inspect this file and `agent_context write` to refresh `NEXUS.md`.",
                "",
                "## MCP Code Graph Tools",
                "",
                "Expose structural awareness to compatible clients through:",
                "",
                "```powershell",
                "python -m mcp.server",
                "```",
                "",
                "Available MCP tools include `nexus_code_graph_build`, `nexus_code_graph_summary`, `nexus_code_graph_search`, `nexus_code_graph_dependencies`, `nexus_code_graph_dependents`, and `nexus_code_graph_symbol_context`.",
                "",
                "## Engineering Rules",
                "",
                "- Do not invent status. Verify from real files, configs, tests, logs, or command output.",
                "- Keep edits scoped and work with existing project patterns before adding abstractions.",
                "- Prefer structured parsers and graph queries over brittle text guessing.",
                "- Preserve user changes. Never revert unrelated work.",
                "- Avoid writing generated/runtime data into source unless the feature explicitly requires it.",
                "- For shell execution, prefer autonomous execution with risk scoring, timeouts, logs, and rollback plans.",
                "",
                "## Do Not Treat As Source",
                "",
                "- `workspace/`, `logs/`, `models/`, `data/`, `training_data/`, `gui/node_modules/`, `dist/`, `build/`, `.pytest_cache/`, and `__pycache__/` are runtime, dependency, or generated surfaces.",
                "",
                "## Refresh Policy",
                "",
                "Regenerate after architecture changes, tool registry changes, MCP changes, new verification commands, or major gui/backend workflow changes.",
                "",
            ]
        )

    def write(self, targets: Iterable[str] | None = None, force: bool = False) -> List[ContextWriteResult]:
        graph = self._load_or_build_graph()
        results: List[ContextWriteResult] = []
        for target in targets or DEFAULT_TARGETS:
            safe_target = self._safe_target(target)
            path = os.path.join(self.root, safe_target)
            if os.path.exists(path) and not force:
                results.append(ContextWriteResult(safe_target, "skipped_exists", path, os.path.getsize(path)))
                continue
            content = self.generate(safe_target, graph=graph)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            results.append(ContextWriteResult(safe_target, "written", path, len(content.encode("utf-8"))))
        return results

    def _load_or_build_graph(self) -> CodeGraph:
        graph = self.graph.load()
        if not graph.nodes:
            graph = self.graph.build()
        return graph

    def _safe_target(self, target: str) -> str:
        name = os.path.basename(target or "NEXUS.md")
        if name not in DEFAULT_TARGETS:
            raise ValueError("target must be NEXUS.md")
        return name

    def _format_counts(self, counts: Dict[str, Any]) -> str:
        if not counts:
            return "none"
        return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))

    def _format_hubs(self, hubs: List[Dict[str, Any]]) -> List[str]:
        if not hubs:
            return ["No hubs recorded yet; build the code graph first."]
        formatted = []
        for hub in hubs[:12]:
            node = hub.get("node", hub)
            label = node.get("path") or node.get("name") or node.get("id", "unknown")
            formatted.append(f"`{label}` ({node.get('kind', 'node')}, degree={hub.get('degree', 0)})")
        return formatted

    def _format_time(self, value: Any) -> str:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
        except (TypeError, ValueError, OSError):
            return "unknown"

