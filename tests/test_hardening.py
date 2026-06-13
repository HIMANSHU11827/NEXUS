import sys
import os
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSwarmEngine(unittest.TestCase):
    def test_mission_has_queue_progress_artifacts_and_cancel(self):
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            hive_id = engine.create_mission("fix code bug and verify tests", autostart=False)
            progress = engine.get_progress(hive_id)
            self.assertGreaterEqual(progress["total"], 4)

            engine.start_workers(count=2)
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = engine.get_progress(hive_id)
                if progress["by_status"].get("succeeded", 0) == progress["total"]:
                    break
                time.sleep(0.05)

            report = engine.consolidate_hive(hive_id)
            self.assertIn("NEXUS HIVE REPORT", report)
            self.assertIn("succeeded", str(engine.get_progress(hive_id)["by_status"]))
            self.assertEqual(engine.cancel_hive(hive_id), 0)
            engine.wait_idle()

    def test_hive_creates_contract_handoff_and_checkpoints(self):
        from hive.engine import NexusHiveEngine

        seen = {}

        def worker(task, context):
            seen[task.id] = context
            self.assertIn("contract", context)
            self.assertIn("handoff", context)
            self.assertEqual(context["handoff"]["task_id"], task.id)
            self.assertTrue(context["handoff"]["required_outputs"])
            return "ok"

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp, worker_fn=worker)
            hive_id = engine.create_mission("fix code bug and verify tests", autostart=True)
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = engine.get_progress(hive_id)
                if progress["total"] and progress["by_status"].get("succeeded") == progress["total"]:
                    break
                time.sleep(0.05)
            progress = engine.get_progress(hive_id)
            self.assertTrue(progress["contracts"])
            self.assertTrue(progress["handoffs"])
            self.assertTrue(seen)
            checkpoint_path = os.path.join(tmp, "workspace", "hive", f"{hive_id}_checkpoints.jsonl")
            self.assertTrue(os.path.exists(checkpoint_path))
            engine.wait_idle()

    def test_hive_creates_custom_specialist_persona(self):
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            result = engine.spawn_agent(
                "Find slow paths and propose benchmark checks",
                persona="performance engineer",
                hive_id="HIVE-CUSTOM",
                persona_description="Own latency, benchmark design, and performance regressions.",
            )
            self.assertIn("PERFORMANCE_ENGINEER", result)
            progress = engine.get_progress("HIVE-CUSTOM")
            self.assertEqual(progress["total"], 1)
            contract = progress["contracts"][0]
            self.assertEqual(contract["role"], "PERFORMANCE_ENGINEER")
            self.assertIn("latency", contract["persona"])
            self.assertIn("benchmark", contract["allowed_tools"])
            self.assertIn("PERFORMANCE_ENGINEER", engine.list_personas())
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = engine.get_progress("HIVE-CUSTOM")
                if progress["by_status"].get("succeeded", 0) == progress["total"]:
                    break
                time.sleep(0.05)
            engine.wait_idle()

    def test_unknown_specialist_gets_synthesized_contract(self):
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            task = engine._new_task("HIVE-X", "memory context architect", "Improve chat compaction and RAG continuity")
            contract = engine.get_progress("HIVE-X")["contracts"]
            self.assertEqual(len(contract), 1)
            self.assertEqual(task.role, "MEMORY_CONTEXT_ARCHITECT")
            self.assertIn("MEMORY_CONTEXT_ARCHITECT", engine.list_personas())
            self.assertIn("context", engine.persona_for_role(task.role).lower())
            self.assertIn("cognition", engine._allowed_tools(task.role))

    def test_hive_llm_worker_builds_role_specific_prompt(self):
        from hive.engine import NexusHiveEngine
        from hive.workers import HiveLLMWorker

        class FakeRouter:
            def __init__(self):
                self.messages = []

            def generate(self, messages, **kwargs):
                self.messages = messages
                return "Evidence: inspected handoff\nBlockers: none\nHandoff: ready"

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            task = engine._new_task("HIVE-LLM", "security hardening specialist", "Review tool risk controls")
            handoff = engine.create_handoff_packet(task)
            context = {
                "contract": engine.get_progress("HIVE-LLM")["contracts"][0],
                "handoff": handoff.to_worker_context(),
            }
            router = FakeRouter()
            worker = HiveLLMWorker(tmp, router=router, fallback_worker=engine._default_worker)
            result = worker(task, context)
            self.assertIn("SECURITY_HARDENING_SPECIALIST", result)
            self.assertIn("Persona:", router.messages[0]["content"])
            self.assertIn("allowed_tools", router.messages[1]["content"])

    def test_hive_llm_worker_falls_back_on_provider_error(self):
        from hive.engine import NexusHiveEngine
        from hive.workers import HiveLLMWorker

        class BadRouter:
            def generate(self, messages, **kwargs):
                return "[PROVIDER_ERROR]: offline"

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            task = engine._new_task("HIVE-LLM", "qa expert", "Verify loop checkpoints")
            worker = HiveLLMWorker(tmp, router=BadRouter(), fallback_worker=engine._default_worker)
            result = worker(task, {"contract": {}, "handoff": {}})
            self.assertIn("HIVE_LLM_FALLBACK", result)
            self.assertIn("Verification checklist", result)

    def test_hive_merge_plan_flags_overlapping_changed_files(self):
        from hive.engine import HiveArtifact, NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            engineer = engine._new_task("HIVE-MERGE", "engineer", "Update router")
            auditor = engine._new_task("HIVE-MERGE", "auditor", "Review router patch")
            engine._tasks[engineer.id] = engineer
            engine._tasks[auditor.id] = auditor
            engine._artifacts.append(
                HiveArtifact(
                    engineer.id,
                    engineer.role,
                    "changed_files: core/router.py, tests/test_router.py\nImplementation done.",
                )
            )
            engine._artifacts.append(
                HiveArtifact(
                    auditor.id,
                    auditor.role,
                    '{"changed_files": ["core/router.py"], "risk_level": "medium"}',
                )
            )

            plan = engine.merge_plan("HIVE-MERGE")
            self.assertEqual(plan["conflict_count"], 1)
            self.assertIn("core/router.py", plan["conflicts"])
            report = engine.consolidate_hive("HIVE-MERGE")
            self.assertIn("MERGE CONFLICTS", report)
            self.assertIn("ENGINEER", report)
            self.assertIn("AUDITOR", report)

    def test_hive_merge_plan_tool_exposes_conflicts(self):
        import json
        from hive.engine import HiveArtifact, NexusHiveEngine
        from tools.nexus_tools import hive_tool

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            engineer = engine._new_task("HIVE-TOOL", "engineer", "Change config")
            qa = engine._new_task("HIVE-TOOL", "qa expert", "Verify config")
            engine._tasks[engineer.id] = engineer
            engine._tasks[qa.id] = qa
            engine._artifacts.append(HiveArtifact(engineer.id, engineer.role, "changed_files=configs/nexus_config.yaml"))
            engine._artifacts.append(HiveArtifact(qa.id, qa.role, "files_touched: configs/nexus_config.yaml"))

            class Kernel:
                hive = engine

            previous = hive_tool.get_nexus_kernel
            hive_tool.get_nexus_kernel = lambda: Kernel
            try:
                result = hive_tool.HiveMergePlanTool(tmp).call(hive_id="HIVE-TOOL")
                data = json.loads(result.data)
            finally:
                hive_tool.get_nexus_kernel = previous

            self.assertEqual(data["conflict_count"], 1)
            self.assertIn("configs/nexus_config.yaml", data["conflicts"])

    def test_hive_artifact_quality_flags_missing_required_outputs(self):
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            task = engine._new_task("HIVE-QUALITY", "engineer", "Implement router change")
            complete = engine.evaluate_artifact_quality(
                task,
                "changed_files: core/router.py\nimplementation_notes: done\nverification_needed: pytest",
            )
            incomplete = engine.evaluate_artifact_quality(task, "done")

        self.assertEqual(complete["quality"], "complete")
        self.assertEqual(incomplete["quality"], "incomplete")
        self.assertIn("changed_files", incomplete["missing_outputs"])

    def test_hive_consolidation_reports_weak_artifacts(self):
        from hive.engine import HiveArtifact, NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            task = engine._new_task("HIVE-WEAK", "engineer", "Implement router change")
            engine._tasks[task.id] = task
            quality = engine.evaluate_artifact_quality(task, "done")
            engine._artifacts.append(HiveArtifact(task.id, task.role, "done", metadata=quality))
            report = engine.consolidate_hive("HIVE-WEAK")

        self.assertIn("ARTIFACT_WARNING", report)
        self.assertIn("changed_files", report)

    def test_hive_retries_incomplete_artifact_before_accepting(self):
        from hive.engine import NexusHiveEngine

        attempts = {"count": 0}

        def worker(task, context):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return "done"
            return "changed_files: core/router.py\nimplementation_notes: repaired\nverification_needed: pytest"

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp, worker_fn=worker)
            engine.spawn_agent("Implement router change", persona="engineer", hive_id="HIVE-RETRY")
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = engine.get_progress("HIVE-RETRY")
                if progress["by_status"].get("succeeded", 0) == progress["total"]:
                    break
                time.sleep(0.05)
            progress = engine.get_progress("HIVE-RETRY")
            report = engine.consolidate_hive("HIVE-RETRY")

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(progress["tasks"][0]["attempts"], 2)
        self.assertNotIn("ARTIFACT_WARNING", report)

    def test_hive_accepts_but_marks_weak_artifact_after_retry_budget(self):
        from hive.engine import NexusHiveEngine

        def worker(task, context):
            return "done"

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp, worker_fn=worker)
            engine.spawn_agent("Implement router change", persona="engineer", hive_id="HIVE-EXHAUST")
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = engine.get_progress("HIVE-EXHAUST")
                if progress["by_status"].get("succeeded", 0) == progress["total"]:
                    break
                time.sleep(0.05)
            report = engine.consolidate_hive("HIVE-EXHAUST")
            progress = engine.get_progress("HIVE-EXHAUST")

        self.assertEqual(progress["tasks"][0]["attempts"], 2)
        self.assertIn("ARTIFACT_WARNING", report)

    def test_hive_hydrates_manifest_on_restart(self):
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            hive_id = engine.create_mission("fix code bug and verify tests", autostart=False)
            original = engine.get_progress(hive_id)
            engine._persist_manifest()

            restored = NexusHiveEngine(tmp)
            progress = restored.get_progress(hive_id)

        self.assertEqual(progress["total"], original["total"])
        self.assertTrue(progress["contracts"])
        self.assertTrue(progress["tasks"])

    def test_hive_restart_requeues_stale_running_tasks(self):
        import json
        from hive.engine import NexusHiveEngine, TaskStatus

        with tempfile.TemporaryDirectory() as tmp:
            logs = os.path.join(tmp, "logs", "hive")
            os.makedirs(logs, exist_ok=True)
            with open(os.path.join(logs, "hive_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "tasks": [
                            {
                                "id": "TASK-STUCK",
                                "hive_id": "HIVE-RESTORE",
                                "role": "ENGINEER",
                                "objective": "Recover stale task",
                                "status": "running",
                                "required_outputs": ["changed_files"],
                            }
                        ],
                        "artifacts": [],
                        "contracts": [],
                        "handoffs": [],
                    },
                    f,
                )
            engine = NexusHiveEngine(tmp)
            progress = engine.get_progress("HIVE-RESTORE")

        self.assertEqual(progress["tasks"][0]["status"], TaskStatus.PENDING.value)

    def test_hive_resume_starts_pending_work(self):
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            engine.create_mission("fix code bug and verify tests", hive_id="HIVE-RESUME", autostart=False)
            result = engine.resume_hive("HIVE-RESUME")
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = engine.get_progress("HIVE-RESUME")
                if progress["by_status"].get("succeeded", 0) == progress["total"]:
                    break
                time.sleep(0.05)

            self.assertTrue(result["started_workers"])
            self.assertGreater(result["pending"], 0)
            self.assertEqual(progress["by_status"].get("succeeded", 0), progress["total"])
            engine.wait_idle()

    def test_hive_resume_tool_exposes_runtime_resume(self):
        import json
        from hive.engine import NexusHiveEngine
        from tools.nexus_tools import hive_tool

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            engine.create_mission("fix code bug and verify tests", hive_id="HIVE-TOOL-RESUME", autostart=False)

            class Kernel:
                hive = engine

            previous = hive_tool.get_nexus_kernel
            hive_tool.get_nexus_kernel = lambda: Kernel
            try:
                result = hive_tool.HiveResumeTool(tmp).call(hive_id="HIVE-TOOL-RESUME", workers=1)
                data = json.loads(result.data)
                deadline = time.time() + 5
                while time.time() < deadline:
                    progress = engine.get_progress("HIVE-TOOL-RESUME")
                    if progress["by_status"].get("succeeded", 0) == progress["total"]:
                        break
                    time.sleep(0.05)
                engine.wait_idle()
            finally:
                hive_tool.get_nexus_kernel = previous

        self.assertTrue(data["started_workers"])
        self.assertGreater(data["pending"], 0)

    def test_hive_persistence_uses_valid_json_outputs(self):
        import json
        from hive.engine import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = NexusHiveEngine(tmp)
            engine.create_persona("release captain", "Own release readiness.")
            engine.create_mission("fix code bug and verify tests", hive_id="HIVE-PERSIST", autostart=False)
            engine._persist_manifest()

            with open(os.path.join(tmp, "configs", "hive_personas.json"), "r", encoding="utf-8") as f:
                personas = json.load(f)
            with open(os.path.join(tmp, "logs", "hive", "hive_manifest.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)

        self.assertIn("RELEASE_CAPTAIN", personas)
        self.assertTrue(manifest["tasks"])


class TestWorldModel(unittest.TestCase):
    def test_world_model_flags_destructive_shell(self):
        from world_model import WorldModel

        with tempfile.TemporaryDirectory() as tmp:
            result = WorldModel(tmp).simulate("bash", {"cmd": "rm -rf /"})
            self.assertEqual(result.risk_level, "critical")
            self.assertFalse(result.reversible)
            self.assertIn("block", result.summary())


class TestProviderHealth(unittest.TestCase):
    def test_provider_health_normalizes_auth_errors(self):
        from providers.health import ProviderHealthRegistry

        registry = ProviderHealthRegistry()
        registry.mark_failure("openai", "401 invalid api key")
        health = registry.get("openai")
        self.assertFalse(health.healthy)
        self.assertIn("AUTH_ERROR", health.last_error)


class TestRagHybrid(unittest.TestCase):
    def test_hybrid_search_returns_metadata(self):
        from rag.engine import NexusAtlasRAG

        NexusAtlasRAG._reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            rag = NexusAtlasRAG(tmp)
            rag.store_document("pkg/sample.py", "def alpha_feature(): return 'needle'")
            results = rag.hybrid_search("alpha_feature needle")
            self.assertTrue(results)
            self.assertEqual(results[0]["file"], "pkg/sample.py")
            self.assertIn("metadata", results[0])
        NexusAtlasRAG._reset_instance()

    def test_cleanup_memory_removes_deleted_source_chunks(self):
        from rag.engine import NexusAtlasRAG

        NexusAtlasRAG._reset_instance()
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "project")
            vault = os.path.join(project, "knowledge")
            os.makedirs(os.path.join(project, "pkg"), exist_ok=True)
            path = os.path.join(project, "pkg", "gone.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write("def disappearing_symbol(): pass")
            rag = NexusAtlasRAG(vault)
            rag.index_workspace(file_path="pkg/gone.py")
            self.assertTrue(rag.hybrid_search("disappearing_symbol"))
            os.remove(path)
            self.assertGreater(rag.cleanup_memory(), 0)
            self.assertEqual([], rag.hybrid_search("disappearing_symbol"))
        NexusAtlasRAG._reset_instance()


class TestDiscoveryStatus(unittest.TestCase):
    def test_discovery_accepts_current_rag_index_version(self):
        from discovery import NexusAutoDiscover

        with tempfile.TemporaryDirectory() as tmp:
            knowledge = os.path.join(tmp, "knowledge")
            os.makedirs(knowledge, exist_ok=True)
            with open(os.path.join(knowledge, "_rag_index_3_3.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            status = NexusAutoDiscover(tmp).get_repo_status()
        self.assertIn("RAG-Store=READY", status)

    def test_discovery_reports_registry_tools_not_legacy_script_folders(self):
        from discovery import NexusAutoDiscover

        tools = NexusAutoDiscover(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).discover_tools()
        names = {tool["name"] for tool in tools}
        self.assertIn("bash", names)
        self.assertIn("file_edit", names)
        self.assertNotIn("terminal", names)
        self.assertNotIn("file_ops", names)


class TestDashboardSecurityHelpers(unittest.TestCase):
    def test_dashboard_upload_helper_blocks_unsafe_extension(self):
        from gui import api
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            api.safe_upload_path("../../payload.exe")

    def test_dashboard_mcp_endpoints(self):
        from gui.api import app, _ROOT
        from fastapi.testclient import TestClient
        from kernel import get_nexus_kernel
        import shutil

        config_path = os.path.join(_ROOT, "configs", "nexus_config.yaml")
        backup_path = config_path + ".bak"
        if os.path.exists(config_path):
            shutil.copy2(config_path, backup_path)
            
        try:
            kernel = get_nexus_kernel(_ROOT)
            # Ensure target key doesn't pre-exist
            if "mcp_servers" in kernel.config.data and "test_mcp" in kernel.config.data["mcp_servers"]:
                del kernel.config.data["mcp_servers"]["test_mcp"]
                kernel.config.save()

            client = TestClient(app)
            payload = {
                "name": "test_mcp",
                "config": {
                    "command": "python",
                    "args": ["-m", "http.server"],
                    "active": True
                }
            }
            response = client.post("/api/mcp/configure", json=payload)
            self.assertEqual(response.status_code, 200)
            
            # Verify directly
            self.assertIn("test_mcp", kernel.config.data.get("mcp_servers", {}))
            self.assertEqual(kernel.config.data["mcp_servers"]["test_mcp"]["command"], "python")
            
            # Delete
            response = client.delete("/api/mcp/delete/test_mcp")
            self.assertEqual(response.status_code, 200)
            
            # Verify deleted directly
            self.assertNotIn("test_mcp", kernel.config.data.get("mcp_servers", {}))
        finally:
            if os.path.exists(backup_path):
                shutil.move(backup_path, config_path)
            try:
                kernel.config.reload()
            except Exception:
                pass


class TestToolRegistryConfigControls(unittest.TestCase):
    def test_disabled_tool_is_not_executed(self):
        from config_loader import NexusConfigLoader
        from tools.nexus_tools.registry import ToolRegistry

        loader = NexusConfigLoader()
        previous_disabled = list(loader.data.get("disabled_tools", []))
        previous_deleted = list(loader.data.get("deleted_tools", []))
        try:
            loader.data["disabled_tools"] = list(set(previous_disabled + ["glob"]))
            loader.data["deleted_tools"] = previous_deleted
            result = ToolRegistry().execute("glob", pattern="*.py")
            self.assertIn("disabled", result)
        finally:
            loader.data["disabled_tools"] = previous_disabled
            loader.data["deleted_tools"] = previous_deleted


class TestWorldModelScenario(unittest.TestCase):
    def test_file_edit_path_escape_is_critical(self):
        from world_model import WorldModel

        with tempfile.TemporaryDirectory() as tmp:
            result = WorldModel(tmp).simulate("file_edit", {"command": "delete", "path": "../outside.txt"})
            self.assertEqual(result.risk_level, "critical")


if __name__ == "__main__":
    unittest.main()

