import os
import tempfile
import time
import unittest


class TestHyperReasoningEngine(unittest.TestCase):
    def test_plan_contains_verification_and_uncertainty(self):
        from core.reasoning.hyper_engine import HyperReasoningEngine

        plan = HyperReasoningEngine().plan("fix dashboard api upload bug and add tests")
        tools = [step.suggested_tool for step in plan.steps]
        self.assertIn("bash", tools)
        self.assertGreater(plan.uncertainty, 0)
        self.assertFalse(plan.should_replan if hasattr(plan, "should_replan") else False)

    def test_replan_on_failure_observation(self):
        from core.reasoning.hyper_engine import HyperReasoningEngine

        engine = HyperReasoningEngine()
        plan = engine.plan("fix test failure")
        self.assertTrue(engine.should_replan(plan, ["pytest failed with traceback"]))


class TestRollbackManager(unittest.TestCase):
    def test_snapshot_and_restore_file(self):
        from core.os_power.rollback import RollbackManager

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("before")
            manager = RollbackManager(tmp)
            snapshot = manager.snapshot_files(["a.txt"], "test")
            with open(path, "w", encoding="utf-8") as f:
                f.write("after")
            self.assertEqual(manager.restore(snapshot.id), 1)
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "before")


class TestProcessManager(unittest.TestCase):
    def test_start_poll_process(self):
        from core.os_power.process_manager import ProcessManager

        with tempfile.TemporaryDirectory() as tmp:
            manager = ProcessManager(tmp)
            proc = manager.start("python -c \"print('ok')\"")
            deadline = time.time() + 5
            result = {"status": "running"}
            while time.time() < deadline:
                result = manager.poll(proc.id)
                if result.get("returncode") is not None:
                    break
                time.sleep(0.05)
            self.assertEqual(result.get("returncode"), 0)
            self.assertIn("ok", result.get("stdout", ""))


class TestSideEffectAnalyzer(unittest.TestCase):
    def test_import_blast_radius(self):
        from core.code_intelligence.side_effects import SideEffectAnalyzer

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "pkg"), exist_ok=True)
            with open(os.path.join(tmp, "pkg", "core.py"), "w", encoding="utf-8") as f:
                f.write("def run(): return 1\n")
            with open(os.path.join(tmp, "pkg", "use.py"), "w", encoding="utf-8") as f:
                f.write("from pkg.core import run\nprint(run())\n")
            report = SideEffectAnalyzer(tmp).analyze("pkg/core.py")
            self.assertIn("pkg/use.py", report.impacted_files)


class TestDiagnosticsRunner(unittest.TestCase):
    def test_diagnostics_reports_python_syntax_failure(self):
        from core.code_intelligence.diagnostics import DiagnosticRunner

        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.py")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("def broken(:\n")
            report = DiagnosticRunner(tmp).run(paths=["bad.py"])
            self.assertFalse(report["ok"])
            self.assertEqual(report["failed"], 1)
            self.assertEqual(report["diagnostics"][0]["kind"], "python_compile")

    def test_diagnostics_tool_is_registered(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("diagnostics", registry.list_tools())


class TestEditPlanner(unittest.TestCase):
    def test_edit_plan_includes_symbols_and_impacted_files(self):
        from core.code_intelligence.edit_plan import EditPlanner

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "pkg"), exist_ok=True)
            with open(os.path.join(tmp, "pkg", "core.py"), "w", encoding="utf-8") as f:
                f.write("def run(): return 1\n")
            with open(os.path.join(tmp, "pkg", "use.py"), "w", encoding="utf-8") as f:
                f.write("from pkg.core import run\n")
            plan = EditPlanner(tmp).plan("pkg/core.py")
            self.assertIn("run", plan.symbols)
            self.assertIn("pkg/use.py", plan.impacted_files)
            self.assertIn("diagnostics", plan.recommended_checks)

    def test_edit_plan_tool_is_registered(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("edit_plan", registry.list_tools())


class TestTestSelector(unittest.TestCase):
    def test_selects_related_tests_for_changed_file(self):
        from core.aurora.test_selection import TestSelector

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "core", "foo"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "tests"), exist_ok=True)
            with open(os.path.join(tmp, "core", "foo", "engine.py"), "w", encoding="utf-8") as f:
                f.write("class FooEngine: pass\n")
            with open(os.path.join(tmp, "tests", "test_foo.py"), "w", encoding="utf-8") as f:
                f.write("from core.foo.engine import FooEngine\n")
            selection = TestSelector(tmp).select(["core/foo/engine.py"])
            self.assertIn("tests/test_foo.py", selection.tests)
            self.assertIn("python tests/test_foo.py", selection.commands)

    def test_test_select_tool_is_registered(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("test_select", registry.list_tools())


class TestFailureVaccineEngine(unittest.TestCase):
    def test_failure_vaccine_creates_memory_strategy_and_regression_plan(self):
        from core.aurora.failure_vaccine import FailureVaccineEngine

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "core", "aurora"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "tests"), exist_ok=True)
            with open(os.path.join(tmp, "core", "aurora", "engine.py"), "w", encoding="utf-8") as f:
                f.write("class AuroraEngine: pass\n")
            with open(os.path.join(tmp, "tests", "test_aurora.py"), "w", encoding="utf-8") as f:
                f.write("from core.aurora.engine import AuroraEngine\n")

            vaccine = FailureVaccineEngine(tmp).create(
                task="fix aurora syntax failure",
                tool="diagnostics",
                error="SyntaxError failed while compiling engine",
                fix_strategy="run diagnostics, patch the syntax, then run targeted aurora tests",
                affected_files=["core/aurora/engine.py"],
            )

            self.assertEqual(vaccine.severity, "high")
            self.assertTrue(vaccine.memory_node_id.startswith("failure:"))
            self.assertTrue(vaccine.strategy_id.startswith("strategy:"))
            self.assertIn("tests/test_aurora.py", vaccine.test_files)
            self.assertIn("python tests/test_aurora.py", vaccine.test_commands)

    def test_failure_vaccine_tool_is_registered(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("failure_vaccine", registry.list_tools())


class TestEvidenceLedger(unittest.TestCase):
    def test_evidence_ledger_records_verifies_and_summarizes_claims(self):
        from core.aurora.evidence_ledger import EvidenceLedger

        with tempfile.TemporaryDirectory() as tmp:
            ledger = EvidenceLedger(tmp)
            record = ledger.record_claim(
                "The test suite passed",
                evidence=[{"source": "pytest", "detail": "129 passed", "kind": "test"}],
                status="supported",
                confidence=0.9,
            )
            same = ledger.record_claim(
                "The test suite passed",
                evidence=[{"source": "pytest", "detail": "129 passed", "kind": "test"}],
                status="supported",
                confidence=0.5,
            )
            self.assertEqual(record.id, same.id)
            self.assertEqual(len(same.evidence), 1)

            verified = ledger.verify(record.id, status="contradicted", confidence=0.2)
            self.assertEqual(verified.status, "contradicted")
            summary = ledger.audit_summary()
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["by_status"]["contradicted"], 1)
            self.assertEqual(summary["unsupported_claims"][0]["id"], record.id)

    def test_evidence_ledger_tool_is_registered_and_callable(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("evidence_ledger", registry.list_tools())

        out = registry.execute(
            "evidence_ledger",
            command="record",
            claim="Evidence ledger tool works",
            evidence=[{"source": "unit-test", "detail": "record command returned JSON"}],
            status="supported",
            confidence=0.8,
            compress=False,
        )
        self.assertIn("Evidence ledger tool works", out)


class TestCodebaseKnowledgeGraph(unittest.TestCase):
    def test_code_graph_builds_import_call_and_dependent_edges(self):
        from core.code_intelligence.knowledge_graph import CodebaseKnowledgeGraph

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "pkg"), exist_ok=True)
            with open(os.path.join(tmp, "pkg", "core.py"), "w", encoding="utf-8") as f:
                f.write("def run():\n    return 1\n")
            with open(os.path.join(tmp, "pkg", "use.py"), "w", encoding="utf-8") as f:
                f.write("from pkg.core import run\n\ndef main():\n    return run()\n")

            graph = CodebaseKnowledgeGraph(tmp)
            built = graph.build()
            summary = graph.summary(built)
            self.assertGreaterEqual(summary["by_kind"]["file"], 2)
            self.assertGreaterEqual(summary["edge_kinds"]["imports"], 1)
            self.assertGreaterEqual(summary["edge_kinds"]["calls"], 1)

            dependents = graph.dependents("module:pkg.core")
            self.assertTrue(any(item["node"].get("path") == "pkg/use.py" for item in dependents))
            context = graph.symbol_context("run")
            self.assertTrue(context["matches"])

    def test_code_graph_tool_is_registered_and_callable(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("code_graph", registry.list_tools())
        out = registry.execute("code_graph", command="summary", compress=False)
        self.assertIn("nodes", out)


class TestAgentContextGenerator(unittest.TestCase):
    def test_agent_context_preview_uses_code_graph_and_commands(self):
        from core.code_intelligence.agent_context import AgentContextGenerator
        from core.code_intelligence.knowledge_graph import CodebaseKnowledgeGraph

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "nexus.py"), "w", encoding="utf-8") as f:
                f.write("def main():\n    return 'ok'\n")
            CodebaseKnowledgeGraph(tmp).build()

            content = AgentContextGenerator(tmp).generate()
            self.assertIn("NEXUS AI Agent Context", content)
            self.assertIn("code_graph", content)
            self.assertIn("python -m pytest -q", content)
            self.assertIn("MCP", content)

    def test_agent_context_write_creates_expected_files_without_overwrite(self):
        from core.code_intelligence.agent_context import AgentContextGenerator

        with tempfile.TemporaryDirectory() as tmp:
            generator = AgentContextGenerator(tmp)
            results = generator.write(["AGENTS.md", "CLAUDE.md"])
            self.assertEqual([item.status for item in results], ["written", "written"])
            self.assertTrue(os.path.exists(os.path.join(tmp, "AGENTS.md")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "CLAUDE.md")))

            with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as f:
                f.write("custom")
            skipped = generator.write(["AGENTS.md"], force=False)
            self.assertEqual(skipped[0].status, "skipped_exists")
            with open(os.path.join(tmp, "AGENTS.md"), "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "custom")

    def test_agent_context_tool_is_registered_and_callable(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("agent_context", registry.list_tools())

        out = registry.execute("agent_context", command="preview", target="AGENTS.md", compress=False)
        self.assertIn("NEXUS AI Agent Context", out)


class TestUnifiedNexusGraph(unittest.TestCase):
    def test_unified_graph_combines_code_memory_evidence_and_sessions(self):
        from core.aurora.evidence_ledger import EvidenceLedger
        from core.aurora.mission_replay import MissionReplay
        from core.aurora.unified_graph import UnifiedNexusGraph
        from core.code_intelligence.knowledge_graph import CodebaseKnowledgeGraph
        from core.cognition.memory_graph import AdaptiveMemoryGraph

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "app.py"), "w", encoding="utf-8") as f:
                f.write("def run():\n    return 1\n")
            CodebaseKnowledgeGraph(tmp).build()
            AdaptiveMemoryGraph(tmp).add("Run diagnostics before final answer", layer="project")
            EvidenceLedger(tmp).record_claim(
                "Unified graph test passed",
                evidence=[{"source": "unit-test", "detail": "build returned nodes"}],
                status="supported",
                confidence=0.9,
                mission_id="mission-a",
            )
            MissionReplay(tmp).record("tool_call", {"tool": "diagnostics", "success": True}, mission_id="mission-a")

            graph = UnifiedNexusGraph(tmp)
            built = graph.build(event_limit=20)
            summary = graph.summary(built)
            self.assertGreater(summary["nodes"], 8)
            self.assertIn("code_graph", summary["by_source"])
            self.assertIn("memory_graph", summary["by_source"])
            self.assertIn("evidence_ledger", summary["by_source"])
            self.assertIn("mission_replay", summary["by_source"])

            results = graph.search("diagnostics", limit=10)
            self.assertTrue(any(item["kind"] in {"memory", "tool", "event"} for item in results))
            neighborhood = graph.neighborhood("mission:mission-a", depth=1)
            self.assertTrue(neighborhood["nodes"])

    def test_unified_graph_tool_is_registered_and_can_close_session(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("unified_graph", registry.list_tools())

        out = registry.execute("unified_graph", command="close_session", mission_id="unit-test", note="closing", compress=False)
        self.assertIn("\"closed\": true", out)
        search = registry.execute("unified_graph", command="search", query="closing", compress=False)
        self.assertIn("session_closed", search)

    def test_unified_graph_includes_session_strategy_todo_and_context_files(self):
        from core.aurora.unified_graph import UnifiedNexusGraph

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "logs", "sessions"), exist_ok=True)
            with open(os.path.join(tmp, "logs", "sessions", "default.json"), "w", encoding="utf-8") as f:
                f.write('[{"role":"user","content":"remember session graph"}, {"role":"assistant","content":"done"}]')
            os.makedirs(os.path.join(tmp, "logs", "hive"), exist_ok=True)
            with open(os.path.join(tmp, "logs", "hive", "hive_blackboard.jsonl"), "w", encoding="utf-8") as f:
                f.write('{"type":"task","content":"hive graph event"}\n')
            with open(os.path.join(tmp, "logs", "hive", "hive_manifest.json"), "w", encoding="utf-8") as f:
                f.write(
                    '{"contracts":[{"id":"c1","role":"ENGINEER","objective":"fix handoff"}],'
                    '"handoffs":[{"id":"h1","role":"ENGINEER","objective":"scoped handoff"}]}'
                )
            os.makedirs(os.path.join(tmp, "workspace"), exist_ok=True)
            with open(os.path.join(tmp, "workspace", "failure_vaccines.jsonl"), "w", encoding="utf-8") as f:
                f.write('{"id":"v1","task":"repair graph","error":"broken session merge","affected_files":["core/x.py"],"created_at":1}\n')
            with open(os.path.join(tmp, "workspace", "self_improvement.json"), "w", encoding="utf-8") as f:
                f.write('{"strategy:1":{"strategy":"prefer unified graph search","trigger":"missing context","updated_at":2}}')
            with open(os.path.join(tmp, "workspace", "todos.json"), "w", encoding="utf-8") as f:
                f.write('[{"id":7,"content":"finish graph coverage","status":"pending","created":3}]')
            with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as f:
                f.write("# Agent Context\nUse unified graph.")

            graph = UnifiedNexusGraph(tmp)
            built = graph.build(event_limit=20, include_code=False)
            summary = graph.summary(built)
            for source in ["sessions", "hive_logs", "failure_vaccines", "self_improvement", "todos", "agent_context"]:
                self.assertIn(source, summary["by_source"])

            self.assertTrue(graph.search("session graph", limit=5))
            self.assertTrue(graph.search("finish graph coverage", limit=5))
            self.assertTrue(graph.search("Agent Context", limit=5))
            self.assertTrue(graph.search("scoped handoff", limit=5))


class TestRoadmapAuditor(unittest.TestCase):
    def test_roadmap_auditor_reports_real_completion_and_markdown(self):
        from core.aurora.roadmap import RoadmapAuditor

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "core", "aurora"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "core", "code_intelligence"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "tools", "nexus_tools"), exist_ok=True)
            os.makedirs(os.path.join(tmp, "workspace"), exist_ok=True)
            for path in [
                "core/aurora/failure_vaccine.py",
                "core/code_intelligence/knowledge_graph.py",
                "tools/nexus_tools/base_tool.py",
                "workspace/code_graph.json",
            ]:
                with open(os.path.join(tmp, path), "w", encoding="utf-8") as f:
                    f.write("{}")

            auditor = RoadmapAuditor(tmp)
            audit = auditor.audit()
            self.assertGreaterEqual(audit["total"], 28)
            self.assertGreater(audit["counts"]["partial"] + audit["counts"]["done"], 0)
            markdown = auditor.to_markdown()
            self.assertIn("NEXUS Roadmap Status", markdown)
            self.assertIn("Next Completion Gates", markdown)

    def test_roadmap_tool_is_registered_and_can_write_status(self):
        from tools.nexus_tools.registry import ToolRegistry

        ToolRegistry._reset_instance()
        ToolRegistry._initialized = False
        registry = ToolRegistry()
        self.assertIn("roadmap", registry.list_tools())
        out = registry.execute("roadmap", command="summary", compress=False)
        self.assertIn("completion_ratio", out)


if __name__ == "__main__":
    unittest.main()
