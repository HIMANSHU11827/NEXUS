"""Roadmap reality audit backed by local files and implemented systems."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from typing import Any, Dict, List


@dataclass
class RoadmapItem:
    phase: str
    item: str
    status: str
    evidence: List[str] = field(default_factory=list)
    remaining: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RoadmapAuditor:
    """Classify roadmap items as done, partial, or missing from real project state."""

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)

    def audit(self) -> Dict[str, Any]:
        items = [
            self._item("Phase 1", "Git-aware patch ledger with automatic revert points", ["os_power/patch_ledger.py", "tools/nexus_tools/advanced_power_tool.py"], ["Git integration is limited because this workspace is not a Git repo."]),
            self._item("Phase 1", "Repo map cache with incremental updates", ["code_intel/repo_map.py", "code_intel/knowledge_graph.py", "workspace/code_graph.json"], ["Incremental graph invalidation is still coarse; refresh is mostly full rebuild."]),
            self._item("Phase 1", "LSP diagnostics integration", ["code_intel/diagnostics.py"], ["Diagnostics are compile/schema/build based; no live LSP server adapter yet."]),
            self._item("Phase 1", "Test-fix loop with failure memory", ["optimization/failure_vaccine.py", "cognition/memory_graph.py", "workspace/failure_vaccines.jsonl"]),
            self._item("Phase 1", "Tool result contracts and structured observations", ["tools/nexus_tools/base_tool.py", "optimization/mission_replay.py", "optimization/evidence_ledger.py"], ["Tool schemas are not yet strictly validated for every tool."]),
            self._item("Phase 1", "Deterministic command risk policy", ["sandbox/risk.py", "permissions.py", "tools/nexus_tools/bash_tool.py"]),
            self._item("Phase 1", "Provider latency registry, health status API, and fallback tuning", ["providers/router.py", "providers/base.py", "config_loader.py"], ["gui provider health is still basic; cost tracking is not complete."]),
            self._item("Phase 1", "gui request audit viewer", ["gui/api.py", "gui/src/App.tsx", "optimization/mission_replay.py", "optimization/unified_graph.py"], ["Audit control plane exists; needs richer filters/export/replay UX."]),
            self._item("Phase 2", "Hybrid BM25 + vector retrieval", ["rag/engine.py", "rag/turbo_vector.py"]),
            self._item("Phase 2", "Timeline memory with decay and importance ranking", ["cognition/memory_graph.py"], ["Temporal/episodic memory is basic and deterministic."]),
            self._item("Phase 2", "Project knowledge graph linking files, symbols, tests, failures, and decisions", ["code_intel/knowledge_graph.py", "optimization/unified_graph.py", "workspace/unified_graph.json"]),
            self._item("Phase 2", "Memory cleanup jobs to remove stale or low-value facts", ["cognition/memory_graph.py", "tools/nexus_tools/advanced_power_tool.py"]),
            self._item("Phase 2", "Retrieval regression set for project-specific memory", ["tests/test_cognition.py", "tests/test_hardening.py"], ["Dedicated RAG answer-quality benchmark set is still thin."]),
            self._item("Phase 2", "Promote adaptive memory graph into a hybrid graph/vector store", ["cognition/memory_graph.py", "optimization/unified_graph.py"], ["Memory is graph plus search; not a production vector graph database."]),
            self._item("Phase 2", "Add contradiction review UI and memory provenance browser", ["cognition/memory_graph.py"], ["No gui UI for contradiction/provenance review yet."]),
            self._item("Phase 3", "Background job manager", ["os_power/process_manager.py"]),
            self._item("Phase 3", "Long-task checkpointing and resume", ["context/persistence.py", "optimization/mission_replay.py"], ["Resume is file-backed but not deeply integrated into every long mission."]),
            self._item("Phase 3", "Hive task economy with explicit artifacts", ["hive/engine.py", "optimization/tool_economy.py"], ["Task economy, artifacts, contracts, and handoffs exist; role-specific LLM workers remain partial."]),
            self._item("Phase 3", "Role-specific LLM execution adapters for Hive tasks", ["hive/engine.py"], ["Hive contracts/handoffs exist; independent per-role model adapters are not complete."]),
            self._item("Phase 3", "Predictive debugging from historical failures", ["optimization/failure_vaccine.py", "cognition/intent_forecaster.py"], ["Prediction is heuristic, not learned from a large failure corpus."]),
            self._item("Phase 3", "Benchmark trainer that turns failures into regression tests", ["optimization/failure_vaccine.py", "evaluation/benchmark.py"], ["Automatic test file generation from failures is not complete."]),
            self._item("Phase 3", "Self-improvement loop with verified persistence", ["cognition/self_improvement.py", "workspace/self_improvement.json"], ["Requires stronger benchmark gates before automatic prompt/tool changes."]),
            self._item("Phase 4", "Authenticated gui", ["gui/api.py"], ["Current posture is local-first hardening; full auth UX is not complete."]),
            self._item("Phase 4", "Profiles for coding, research, automation, architecture, and bug hunt", ["prompts/__init__.py", "orchestrators/architect.py"], ["Profiles are mostly prompt/tool conventions, not a complete product switcher."]),
            self._item("Phase 4", "MCP-compatible tool/plugin SDK", ["mcp/server.py", "docs/MCP_CODE_GRAPH.md", "pyproject.toml"], ["Current MCP export is code-graph focused, not full SDK."]),
            self._item("Phase 4", "Provider health checks and fallback router", ["providers/base.py", "providers/router.py", "tests/test_provider_routing.py"]),
            self._item("Phase 4", "CI template and release packaging", [".github/workflows/ci.yml", "pyproject.toml"], ["Release publishing workflow is not complete."]),
            self._item("Phase 5", "Local-first autonomous engineering OS moat", ["optimization/unified_graph.py", "code_intel/agent_context.py", "tools/nexus_tools/advanced_power_tool.py"], ["Still experimental; gui UX, graph RAG, and production packaging remain major gates."]),
            self._item("Cross-Cut", "Browser/computer-use automation with screenshots and action logs", ["tools/nexus_tools/advanced_power_tool.py", "docs/BROWSER_AUTOMATION.md"], ["Real Playwright browser execution is optional and depends on installing browser extras."]),
        ]
        counts = {"done": 0, "partial": 0, "missing": 0}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return {
            "total": len(items),
            "counts": counts,
            "completion_ratio": round((counts.get("done", 0) + counts.get("partial", 0) * 0.5) / max(len(items), 1), 4),
            "items": [item.to_dict() for item in items],
            "remaining_top": [item.to_dict() for item in items if item.status != "done"][:12],
        }

    def to_markdown(self) -> str:
        audit = self.audit()
        lines = [
            "# NEXUS Roadmap Status",
            "",
            "This status is generated from real repository files and implemented systems.",
            "",
            f"- Total items: {audit['total']}",
            f"- Done: {audit['counts'].get('done', 0)}",
            f"- Partial: {audit['counts'].get('partial', 0)}",
            f"- Missing: {audit['counts'].get('missing', 0)}",
            f"- Weighted completion: {audit['completion_ratio'] * 100:.1f}%",
            "",
            "## Item Status",
            "",
            "| Phase | Status | Item | Evidence | Remaining |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in audit["items"]:
            lines.append(
                f"| {item['phase']} | {item['status']} | {self._esc(item['item'])} | {self._esc(', '.join(item['evidence']) or 'none')} | {self._esc('; '.join(item['remaining']) or 'none')} |"
            )
        lines.extend(
            [
                "",
                "## Next Completion Gates",
                "",
                "1. Add a real gui audit timeline for mission replay, evidence, tool economy, and unified graph events.",
                "2. Add live LSP integration on top of the current compile/build diagnostics.",
                "3. Promote graph/RAG retrieval into a tested multi-hop GraphRAG path.",
                "4. Finish role-specific LLM swarm adapters with explicit agent contracts.",
                "5. Add release packaging/publishing checks and stronger gui auth UX.",
                "",
            ]
        )
        return "\n".join(lines)

    def write_status(self, target: str = "docs/ROADMAP_STATUS.md") -> str:
        path = os.path.join(self.root, target)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())
        return path

    def _item(self, phase: str, item: str, evidence_paths: List[str], remaining: List[str] | None = None) -> RoadmapItem:
        evidence = [path for path in evidence_paths if self._exists(path)]
        if len(evidence) == len(evidence_paths) and not remaining:
            status = "done"
        elif evidence:
            status = "partial" if remaining else "done"
        else:
            status = "missing"
        return RoadmapItem(phase, item, status, evidence=evidence, remaining=remaining or [])

    def _exists(self, rel_path: str) -> bool:
        return os.path.exists(os.path.join(self.root, rel_path))

    @staticmethod
    def _esc(text: str) -> str:
        return str(text).replace("|", "\\|").replace("\n", " ")


