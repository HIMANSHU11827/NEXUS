"""Competitive moat audit for local-first agent frameworks.

This module does not claim live market facts. It tracks capability categories
commonly expected from modern coding agents and compares NEXUS against them
using repository evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from typing import Any, Dict, List


@dataclass
class CompetitiveCapability:
    area: str
    target: str
    status: str
    evidence: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    priority: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CompetitiveMoatAuditor:
    """Audit NEXUS against competitor-style capability expectations."""

    COMPETITOR_ARCHETYPES = [
        "Claude Code style terminal coding agent",
        "Gemini CLI style command-line assistant",
        "OpenHands/OpenDevin style autonomous software worker",
        "HyperAgent style parallel automation",
        "Hermes style local memory and skill workflow",
        "Cursor/Windsurf style codebase-aware IDE agent",
    ]

    def __init__(self, root_dir: str) -> None:
        self.root = os.path.abspath(root_dir)

    def audit(self) -> Dict[str, Any]:
        capabilities = self._capabilities()
        counts = {"done": 0, "partial": 0, "missing": 0}
        for capability in capabilities:
            counts[capability.status] = counts.get(capability.status, 0) + 1
        weighted = counts.get("done", 0) + counts.get("partial", 0) * 0.5
        total = max(len(capabilities), 1)
        gaps = [cap.to_dict() for cap in sorted(capabilities, key=lambda item: (item.status == "done", item.priority)) if cap.status != "done"]
        return {
            "competitor_archetypes": self.COMPETITOR_ARCHETYPES,
            "total": len(capabilities),
            "counts": counts,
            "moat_score": round(weighted / total, 4),
            "capabilities": [cap.to_dict() for cap in capabilities],
            "top_gaps": gaps[:10],
            "next_attack_plan": self.next_attack_plan(capabilities),
        }

    def to_markdown(self) -> str:
        audit = self.audit()
        lines = [
            "# NEXUS Competitive Moat Audit",
            "",
            "Generated from local repository evidence. This is a product pressure map, not a live market benchmark.",
            "",
            f"- Moat score: {audit['moat_score'] * 100:.1f}%",
            f"- Done: {audit['counts'].get('done', 0)}",
            f"- Partial: {audit['counts'].get('partial', 0)}",
            f"- Missing: {audit['counts'].get('missing', 0)}",
            "",
            "## Competitor Archetypes",
            "",
        ]
        lines.extend(f"- {name}" for name in audit["competitor_archetypes"])
        lines.extend(
            [
                "",
                "## Capability Map",
                "",
                "| Status | Priority | Area | Target | Evidence | Gaps |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for cap in audit["capabilities"]:
            lines.append(
                f"| {cap['status']} | P{cap['priority']} | {self._esc(cap['area'])} | "
                f"{self._esc(cap['target'])} | {self._esc(', '.join(cap['evidence']) or 'none')} | "
                f"{self._esc('; '.join(cap['gaps']) or 'none')} |"
            )
        lines.extend(["", "## Next Attack Plan", ""])
        lines.extend(f"{idx}. {item}" for idx, item in enumerate(audit["next_attack_plan"], start=1))
        lines.append("")
        return "\n".join(lines)

    def write_status(self, target: str = "docs/COMPETITIVE_MOAT.md") -> str:
        path = os.path.join(self.root, target)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())
        return path

    def next_attack_plan(self, capabilities: List[CompetitiveCapability] | None = None) -> List[str]:
        caps = capabilities or self._capabilities()
        missing_or_partial = [cap for cap in caps if cap.status != "done"]
        ranked = sorted(missing_or_partial, key=lambda cap: cap.priority)
        plan = []
        for cap in ranked[:8]:
            gap = cap.gaps[0] if cap.gaps else "Finish implementation and verification."
            plan.append(f"{cap.area}: {gap}")
        return plan or ["Maintain benchmark gates and keep evidence fresh."]

    def _capabilities(self) -> List[CompetitiveCapability]:
        return [
            self._cap(
                "Terminal coding loop",
                "Chat, code edits, shell commands, tests, and verification through one loop.",
                ["orchestrators/loop.py", "tools/nexus_tools/bash_tool.py", "tools/nexus_tools/file_edit_tool.py", "tests/test_unified_loop.py"],
                ["Improve native provider tool-calling support beyond JSON extraction."],
                priority=1,
            ),
            self._cap(
                "Codebase awareness",
                "Search, symbols, dependencies, agent context files, and code graph MCP.",
                ["core/code_intelligence/knowledge_graph.py", "mcp/server.py", "NEXUS.md", "tests/test_mcp_server.py"],
                ["Incremental graph refresh and IDE-grade symbol precision remain incomplete."],
                priority=1,
            ),
            self._cap(
                "Autonomous Hive work",
                "Spawn scoped Hive workers with contracts, handoffs, artifacts, and blackboard coordination.",
                ["hive/engine.py", "hive/workers.py", "tools/nexus_tools/hive_tool.py", "tests/test_hardening.py"],
                ["Conflict-aware merge workflows and active per-worker tool execution need more depth."],
                priority=1,
            ),
            self._cap(
                "Long-task durability",
                "Checkpoint missions, replay events, and resume context after interruption.",
                ["core/context/persistence.py", "optimization/mission_replay.py", "workspace/context_packets.json"],
                ["Resume is not fully wired into every loop/hive mission path."],
                priority=2,
            ),
            self._cap(
                "Memory and RAG",
                "Hybrid recall, cleanup, adaptive memory graph, and zero-token context packets.",
                ["rag/engine.py", "core/cognition/memory_graph.py", "core/cognition/context_engine.py", "tests/test_cognition.py"],
                ["GraphRAG multi-hop retrieval and answer-quality benchmark set need expansion."],
                priority=1,
            ),
            self._cap(
                "Safety without approval friction",
                "Risk scoring, permissions, law checks, rollback, patch ledger, and evidence logging.",
                ["core/autonomy/risk.py", "core/permissions.py", "core/os_power/rollback.py", "optimization/evidence_ledger.py"],
                ["High-risk action recovery needs stronger rollback drills, replay evidence, and post-failure repair flows."],
                priority=1,
            ),
            self._cap(
                "Provider routing",
                "Local/cloud provider selection, fallback, health tracking, and capability awareness.",
                ["providers/router.py", "providers/health.py", "tests/test_provider_routing.py"],
                ["Cost-aware routing, per-task model benchmarks, and richer gui status remain partial."],
                priority=2,
            ),
            self._cap(
                "gui control plane",
                "Operator gui for providers, tools, MCP, audit, graph, and vision surfaces.",
                ["gui/api.py", "gui/src/App.tsx", "tests/test_gui_security.py"],
                ["Needs stronger auth UX, timeline filters, replay controls, and memory provenance review."],
                priority=2,
            ),
            self._cap(
                "Browser and computer use",
                "Fetch pages, run browser sequences, capture screenshots, and integrate UI automation.",
                ["core/browser_automation/agent_browser.py", "integrations/nexus-browser-bridge", "docs/BROWSER_AUTOMATION.md"],
                ["Playwright-backed path is optional; desktop automation hardening remains incomplete."],
                priority=3,
            ),
            self._cap(
                "Self-improvement and benchmarks",
                "Failure vaccines, tool economy, benchmark history, and regression gates.",
                ["optimization/failure_vaccine.py", "optimization/tool_economy.py", "core/evaluation/benchmark.py", "tests/test_advanced_tools.py"],
                ["Automatic conversion of failures into production tests and prompt/tool changes is still guarded."],
                priority=2,
            ),
            self._cap(
                "Plugin and protocol ecosystem",
                "MCP server, tools, skills, and local extension surfaces.",
                ["mcp/server.py", "core/skills.py", "tools/nexus_tools/registry.py"],
                ["Full external plugin SDK packaging and examples are incomplete."],
                priority=3,
            ),
            self._cap(
                "Release and product polish",
                "Installable package, CI checks, docs, gui build, and honest status reports.",
                ["pyproject.toml", ".github/workflows/ci.yml", "README.md", "docs/ROADMAP_STATUS.md"],
                ["Release publishing, onboarding UX, and production hardening need more work."],
                priority=3,
            ),
        ]

    def _cap(self, area: str, target: str, evidence_paths: List[str], gaps: List[str], priority: int) -> CompetitiveCapability:
        evidence = [path for path in evidence_paths if self._exists(path)]
        if len(evidence) == len(evidence_paths) and not gaps:
            status = "done"
        elif evidence:
            status = "partial" if gaps else "done"
        else:
            status = "missing"
        return CompetitiveCapability(area, target, status, evidence=evidence, gaps=gaps, priority=priority)

    def _exists(self, rel_path: str) -> bool:
        return os.path.exists(os.path.join(self.root, rel_path))

    @staticmethod
    def _esc(text: str) -> str:
        return str(text).replace("|", "\\|").replace("\n", " ")


