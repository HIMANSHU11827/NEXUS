"""Advanced NEXUS power tools: rollback, processes, reasoning, memory, and side effects."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from tools.nexus_tools.base_tool import BaseTool, ToolResult


class RollbackTool(BaseTool):
    name = "rollback"
    description = "Create and restore project-local rollback snapshots for files."
    aliases = ["snapshot", "restore"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "snapshot", paths: List[str] | None = None, snapshot_id: str = "", reason: str = "", **kwargs) -> ToolResult:
        from os_power.rollback import RollbackManager

        manager = RollbackManager(self.root)
        if command == "snapshot":
            snapshot = manager.snapshot_files(paths or [], reason=reason)
            return ToolResult(data=json.dumps(snapshot.__dict__, indent=2))
        if command == "restore":
            if not snapshot_id:
                return ToolResult(error="snapshot_id is required for restore")
            restored = manager.restore(snapshot_id)
            return ToolResult(data=f"Restored {restored} file(s) from {snapshot_id}")
        return ToolResult(error=f"Unknown rollback command: {command}")

    def is_read_only(self, input_data=None):
        return False

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "enum": ["snapshot", "restore"]},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "snapshot_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["command"],
            },
        }


class PatchLedgerTool(BaseTool):
    name = "patch_ledger"
    description = "Create baselines and record inspectable patch diffs independent of Git."
    aliases = ["patches", "change_ledger"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(
        self,
        command: str = "recent",
        paths: List[str] | None = None,
        baseline_id: str = "",
        reason: str = "",
        rollback_id: str = "",
        limit: int = 20,
        **kwargs,
    ) -> ToolResult:
        from os_power.patch_ledger import PatchLedger

        ledger = PatchLedger(self.root)
        if command == "baseline":
            return ToolResult(data=json.dumps(ledger.baseline(paths or [], label=reason), indent=2))
        if command == "record":
            if not baseline_id:
                return ToolResult(error="baseline_id is required")
            record = ledger.record(baseline_id, paths or [], reason=reason, rollback_id=rollback_id)
            return ToolResult(data=json.dumps(record.__dict__ | {"files": [f.__dict__ for f in record.files]}, indent=2))
        if command == "recent":
            return ToolResult(data=json.dumps(ledger.recent(limit=limit), indent=2))
        return ToolResult(error=f"Unknown patch_ledger command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") == "recent")


class ProcessTool(BaseTool):
    name = "process"
    description = "Manage background processes: start, poll, and kill."
    aliases = ["jobs", "process_manager"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        from os_power.process_manager import ProcessManager

        self.manager = ProcessManager(self.root)

    def call(self, command: str = "poll", cmd: str = "", process_id: str = "", **kwargs) -> ToolResult:
        if command == "start":
            if not cmd:
                return ToolResult(error="cmd is required for start")
            try:
                meta = self.manager.start(cmd, process_id=process_id or None)
            except ValueError as exc:
                return ToolResult(error=str(exc))
            return ToolResult(data=json.dumps(meta.__dict__, indent=2))
        if command == "poll":
            if not process_id:
                return ToolResult(error="process_id is required for poll")
            return ToolResult(data=json.dumps(self.manager.poll(process_id), indent=2))
        if command == "kill":
            if not process_id:
                return ToolResult(error="process_id is required for kill")
            return ToolResult(data=f"killed={self.manager.kill(process_id)}")
        return ToolResult(error=f"Unknown process command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") == "poll")


class SideEffectTool(BaseTool):
    name = "side_effects"
    description = "Predict cross-file blast radius before editing a source file."
    aliases = ["blast_radius", "impact"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, path: str = "", **kwargs) -> ToolResult:
        if not path:
            return ToolResult(error="path is required")
        from code_intel.side_effects import SideEffectAnalyzer

        report = SideEffectAnalyzer(self.root).analyze(path)
        return ToolResult(data=json.dumps(report.__dict__, indent=2))

    def is_read_only(self, input_data=None):
        return True


class DiagnosticsTool(BaseTool):
    name = "diagnostics"
    description = "Run compile/parse diagnostics for Python, JSON, YAML, and optional gui build."
    aliases = ["diag", "check_project"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, paths: List[str] | None = None, include_gui: bool = False, **kwargs) -> ToolResult:
        from code_intel.diagnostics import DiagnosticRunner

        include_dashboard = bool(kwargs.get("include_dashboard", False))
        report = DiagnosticRunner(self.root).run(
            paths=paths or ["."],
            include_gui=include_gui or include_dashboard,
        )
        return ToolResult(data=json.dumps(report, indent=2))

    def is_read_only(self, input_data=None):
        return True


class EditPlanTool(BaseTool):
    name = "edit_plan"
    description = "Build a symbol-aware pre-edit plan with blast radius and recommended checks."
    aliases = ["plan_edit", "code_edit_plan"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, path: str = "", **kwargs) -> ToolResult:
        if not path:
            return ToolResult(error="path is required")
        from code_intel.edit_plan import EditPlanner

        plan = EditPlanner(self.root).plan(path)
        return ToolResult(data=json.dumps(plan.to_dict(), indent=2))

    def is_read_only(self, input_data=None):
        return True


class HyperPlanTool(BaseTool):
    name = "hyper_plan"
    description = "Create an explicit planner/critic/verifier plan with uncertainty scoring."
    aliases = ["reasoning_plan", "plan"]

    def call(self, task: str = "", observations: List[str] | None = None, **kwargs) -> ToolResult:
        if not task:
            return ToolResult(error="task is required")
        from reasoning.hyper_engine import HyperReasoningEngine

        engine = HyperReasoningEngine()
        plan = engine.plan(task)
        data = plan.to_dict()
        if observations:
            data["should_replan"] = engine.should_replan(plan, observations)
        return ToolResult(data=json.dumps(data, indent=2))

    def is_read_only(self, input_data=None):
        return True


class CognitionTool(BaseTool):
    name = "cognition"
    description = "Read/write adaptive memory graph and zero-token context packets."
    aliases = ["memory_graph", "context_packet"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "recall", text: str = "", layer: str = "project", query: str = "", **kwargs) -> ToolResult:
        from cognition.memory_graph import AdaptiveMemoryGraph
        from cognition.context_engine import ZeroTokenContextEngine

        graph = AdaptiveMemoryGraph(self.root)
        context = ZeroTokenContextEngine(self.root)
        if command == "remember":
            if not text:
                return ToolResult(error="text is required")
            node = graph.add(text, layer=layer)
            return ToolResult(data=json.dumps(node.__dict__, indent=2))
        if command == "recall":
            nodes = graph.recall(query or text, layer=None if layer == "*" else layer)
            return ToolResult(data=json.dumps([n.__dict__ for n in nodes], indent=2))
        if command == "packet":
            packet = graph.compressed_packet(query or text)
            ctx = context.create_packet("cognition_packet", "\n".join(packet["facts"]), packet["pointers"], {"layer": layer})
            return ToolResult(data=json.dumps(ctx.__dict__, indent=2))
        if command == "cleanup":
            return ToolResult(data=f"removed={graph.cleanup()}; duplicate_packets={context.purge_duplicates()}")
        return ToolResult(error=f"Unknown cognition command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") == "recall")


class SkillForgeTool(BaseTool):
    name = "skill_forge"
    description = "Create and search reusable workflow/macro definitions."
    aliases = ["forge_skill", "workflow_forge"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "search", name: str = "", description: str = "", steps: List[str] | None = None, query: str = "", **kwargs) -> ToolResult:
        from cognition.skill_forge import SkillForge

        forge = SkillForge(self.root)
        if command == "forge":
            if not name:
                return ToolResult(error="name is required")
            skill = forge.forge(name, description, steps or [])
            return ToolResult(data=json.dumps(skill.__dict__, indent=2))
        if command == "search":
            skills = forge.search(query or name or description)
            return ToolResult(data=json.dumps([s.__dict__ for s in skills], indent=2))
        return ToolResult(error=f"Unknown skill_forge command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") == "search")


class BenchmarkTool(BaseTool):
    name = "benchmark"
    description = "Run and inspect local NEXUS regression benchmarks."
    aliases = ["self_benchmark", "bench"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "run", limit: int = 20, **kwargs) -> ToolResult:
        from evaluation.benchmark import BenchmarkRunner

        runner = BenchmarkRunner(self.root)
        if command == "run":
            return ToolResult(data=json.dumps(runner.run(), indent=2))
        if command == "history":
            return ToolResult(data=json.dumps(runner.history(limit=limit), indent=2))
        return ToolResult(error=f"Unknown benchmark command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") == "history")


class CompetitiveMoatTool(BaseTool):
    name = "competitive_moat"
    description = "Audit NEXUS against competitor-style agent capability categories and produce an attack plan."
    aliases = ["moat", "competitor_audit", "market_moat"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "summary", target: str = "docs/COMPETITIVE_MOAT.md", **kwargs) -> ToolResult:
        from optimization.competitive import CompetitiveMoatAuditor

        auditor = CompetitiveMoatAuditor(self.root)
        if command == "summary":
            return ToolResult(data=json.dumps(auditor.audit(), indent=2))
        if command == "markdown":
            return ToolResult(data=auditor.to_markdown())
        if command == "write":
            path = auditor.write_status(target=target)
            return ToolResult(data=json.dumps({"written": path, "moat_score": auditor.audit()["moat_score"]}, indent=2))
        return ToolResult(error=f"Unknown competitive_moat command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") in {"summary", "markdown"})


class MissionReplayTool(BaseTool):
    name = "mission_replay"
    description = "Inspect the append-only mission replay event log."
    aliases = ["replay", "flight_recorder"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "recent", limit: int = 50, mission_id: str = "", **kwargs) -> ToolResult:
        from optimization.mission_replay import MissionReplay

        replay = MissionReplay(self.root)
        if command == "recent":
            return ToolResult(data=json.dumps(replay.recent(limit=limit, mission_id=mission_id), indent=2))
        return ToolResult(error=f"Unknown mission_replay command: {command}")

    def is_read_only(self, input_data=None):
        return True


class ToolEconomyTool(BaseTool):
    name = "tool_economy"
    description = "Inspect persistent tool success, latency, and reputation metrics."
    aliases = ["tool_market", "tool_reputation"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "rank", tool: str = "", **kwargs) -> ToolResult:
        from optimization.tool_economy import ToolEconomy

        economy = ToolEconomy(self.root)
        if command == "rank":
            return ToolResult(data=json.dumps(economy.rank(), indent=2))
        if command == "get":
            return ToolResult(data=json.dumps(economy.get(tool), indent=2))
        return ToolResult(error=f"Unknown tool_economy command: {command}")

    def is_read_only(self, input_data=None):
        return True


class TestSelectionTool(BaseTool):
    name = "test_select"
    description = "Select targeted tests and diagnostics for changed files."
    aliases = ["select_tests", "test_selection"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, changed_files: List[str] | None = None, path: str = "", **kwargs) -> ToolResult:
        from optimization.test_selection import TestSelector

        files = changed_files or ([path] if path else [])
        if not files:
            return ToolResult(error="changed_files or path is required")
        selection = TestSelector(self.root).select(files)
        return ToolResult(data=json.dumps(selection.to_dict(), indent=2))

    def is_read_only(self, input_data=None):
        return True


class FailureVaccineTool(BaseTool):
    name = "failure_vaccine"
    description = "Convert concrete failures into memory rules, fix strategies, and regression plans."
    aliases = ["vaccine", "failure_immunize", "regression_plan"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(
        self,
        command: str = "create",
        task: str = "",
        error: str = "",
        fix_strategy: str = "",
        tool: str = "",
        affected_files: List[str] | None = None,
        query: str = "",
        limit: int = 20,
        **kwargs,
    ) -> ToolResult:
        from optimization.failure_vaccine import FailureVaccineEngine

        engine = FailureVaccineEngine(self.root)
        try:
            if command == "create":
                vaccine = engine.create(
                    task=task,
                    error=error,
                    fix_strategy=fix_strategy,
                    tool=tool,
                    affected_files=affected_files or [],
                    context=kwargs.get("context"),
                )
                return ToolResult(data=json.dumps(vaccine.to_dict(), indent=2))
            if command == "recent":
                return ToolResult(data=json.dumps(engine.recent(limit=limit), indent=2))
            if command == "recall":
                return ToolResult(data=json.dumps(engine.recall(query or task or error, limit=limit), indent=2))
        except ValueError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(error=f"Unknown failure_vaccine command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") in {"recent", "recall"})


class EvidenceLedgerTool(BaseTool):
    name = "evidence_ledger"
    description = "Record and audit claims with supporting evidence, status, and confidence."
    aliases = ["evidence", "truth_ledger", "claim_audit"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(
        self,
        command: str = "summary",
        claim: str = "",
        evidence: List[Dict[str, Any]] | None = None,
        record_id: str = "",
        status: str = "unverified",
        confidence: float = 0.0,
        mission_id: str = "default",
        limit: int = 50,
        **kwargs,
    ) -> ToolResult:
        from optimization.evidence_ledger import EvidenceLedger

        ledger = EvidenceLedger(self.root)
        try:
            if command == "record":
                record = ledger.record_claim(
                    claim=claim,
                    evidence=evidence or [],
                    status=status,
                    confidence=confidence,
                    mission_id=mission_id,
                )
                return ToolResult(data=json.dumps(record.to_dict(), indent=2))
            if command == "verify":
                if not record_id:
                    return ToolResult(error="record_id is required")
                record = ledger.verify(record_id, status=status, confidence=confidence, evidence=evidence or [])
                return ToolResult(data=json.dumps(record.to_dict(), indent=2))
            if command == "recent":
                return ToolResult(data=json.dumps(ledger.recent(limit=limit, status=kwargs.get("filter_status", ""), mission_id=mission_id if mission_id != "default" else ""), indent=2))
            if command == "summary":
                return ToolResult(data=json.dumps(ledger.audit_summary(), indent=2))
        except ValueError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(error=f"Unknown evidence_ledger command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") in {"recent", "summary"})


class CodeGraphTool(BaseTool):
    name = "code_graph"
    description = "Build and query a persistent codebase knowledge graph of files, symbols, imports, and calls."
    aliases = ["knowledge_graph", "codebase_graph", "structural_graph"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(
        self,
        command: str = "summary",
        query: str = "",
        target: str = "",
        symbol: str = "",
        max_files: int = 5000,
        limit: int = 20,
        **kwargs,
    ) -> ToolResult:
        from code_intel.knowledge_graph import CodebaseKnowledgeGraph

        graph = CodebaseKnowledgeGraph(self.root)
        if command == "build":
            built = graph.build(max_files=max_files)
            return ToolResult(data=json.dumps(graph.summary(built, limit=limit), indent=2))
        if command == "summary":
            return ToolResult(data=json.dumps(graph.summary(limit=limit), indent=2))
        if command == "search":
            return ToolResult(data=json.dumps(graph.search(query or target or symbol, limit=limit), indent=2))
        if command == "dependencies":
            if not target:
                return ToolResult(error="target is required")
            return ToolResult(data=json.dumps(graph.dependencies(target), indent=2))
        if command == "dependents":
            if not target:
                return ToolResult(error="target is required")
            return ToolResult(data=json.dumps(graph.dependents(target), indent=2))
        if command == "symbol_context":
            if not symbol and target:
                symbol = target
            if not symbol:
                return ToolResult(error="symbol is required")
            return ToolResult(data=json.dumps(graph.symbol_context(symbol), indent=2))
        return ToolResult(error=f"Unknown code_graph command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") != "build")


class AgentContextTool(BaseTool):
    name = "agent_context"
    description = "Generate NEXUS.md from the live code graph for coding-agent structural awareness."
    aliases = ["agents_md", "nexus_md", "claude_md", "context_file"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(
        self,
        command: str = "preview",
        target: str = "NEXUS.md",
        targets: List[str] | None = None,
        force: bool = False,
        **kwargs,
    ) -> ToolResult:
        from code_intel.agent_context import AgentContextGenerator

        generator = AgentContextGenerator(self.root)
        try:
            if command == "preview":
                return ToolResult(data=generator.generate(target=target))
            if command == "write":
                selected = targets or ([target] if target else None)
                results = [item.to_dict() for item in generator.write(selected, force=force)]
                return ToolResult(data=json.dumps(results, indent=2))
        except ValueError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(error=f"Unknown agent_context command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") == "preview")


class UnifiedGraphTool(BaseTool):
    name = "unified_graph"
    description = "Build and query one NEXUS graph over code, memory, evidence, sessions, tools, and benchmarks."
    aliases = ["nexus_graph", "one_graph", "session_graph"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(
        self,
        command: str = "summary",
        query: str = "",
        node_id: str = "",
        mission_id: str = "default",
        note: str = "",
        event_limit: int = 1000,
        include_code: bool = True,
        depth: int = 1,
        limit: int = 25,
        kinds: List[str] | None = None,
        **kwargs,
    ) -> ToolResult:
        from optimization.unified_graph import UnifiedNexusGraph

        graph = UnifiedNexusGraph(self.root)
        if command == "build":
            built = graph.build(event_limit=event_limit, include_code=include_code)
            return ToolResult(data=json.dumps(graph.summary(built), indent=2))
        if command == "summary":
            loaded = graph.load()
            if not loaded.nodes:
                loaded = graph.build(event_limit=event_limit, include_code=include_code)
            return ToolResult(data=json.dumps(graph.summary(loaded), indent=2))
        if command == "search":
            return ToolResult(data=json.dumps(graph.search(query, kinds=kinds, limit=limit), indent=2))
        if command == "neighborhood":
            if not node_id:
                return ToolResult(error="node_id is required")
            return ToolResult(data=json.dumps(graph.neighborhood(node_id, depth=depth, limit=limit), indent=2))
        if command == "close_session":
            return ToolResult(data=json.dumps(graph.close_session(mission_id=mission_id, note=note), indent=2))
        return ToolResult(error=f"Unknown unified_graph command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") in {"summary", "search", "neighborhood"})


class RoadmapTool(BaseTool):
    name = "roadmap"
    description = "Audit roadmap completion from real project files and write docs/ROADMAP_STATUS.md."
    aliases = ["roadmap_status", "roadmap_audit", "remaining_work"]

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)

    def call(self, command: str = "summary", target: str = "docs/ROADMAP_STATUS.md", **kwargs) -> ToolResult:
        from optimization.roadmap import RoadmapAuditor

        auditor = RoadmapAuditor(self.root)
        if command == "summary":
            return ToolResult(data=json.dumps(auditor.audit(), indent=2))
        if command == "markdown":
            return ToolResult(data=auditor.to_markdown())
        if command == "write":
            path = auditor.write_status(target=target)
            return ToolResult(data=json.dumps({"written": path, "summary": auditor.audit()["counts"]}, indent=2))
        return ToolResult(error=f"Unknown roadmap command: {command}")

    def is_read_only(self, input_data=None):
        return bool(input_data and input_data.get("command") in {"summary", "markdown"})


