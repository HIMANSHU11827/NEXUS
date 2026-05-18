import os
import tempfile
import time
import unittest


class TestSwarmEngine(unittest.TestCase):
    def test_mission_has_queue_progress_artifacts_and_cancel(self):
        from core.hive import NexusHiveEngine

        with tempfile.TemporaryDirectory() as tmp:
            hive = NexusHiveEngine(tmp)
            hive = hive.create_mission("fix code bug and verify tests", autostart=False)
            progress = hive.get_progress(hive)
            self.assertGreaterEqual(progress["total"], 4)

            hive.start_workers(count=2)
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = hive.get_progress(hive)
                if progress["by_status"].get("succeeded", 0) == progress["total"]:
                    break
                time.sleep(0.05)

            report = hive.consolidate_hive(hive)
            self.assertIn("NEXUS HIVE REPORT", report)
            self.assertIn("succeeded", str(hive.get_progress(hive)["by_status"]))
            self.assertEqual(hive.cancel_hive(hive), 0)

    def test_hive_creates_contract_handoff_and_checkpoints(self):
        from core.hive import NexusHiveEngine

        seen = {}

        def worker(task, context):
            seen[task.id] = context
            self.assertIn("contract", context)
            self.assertIn("handoff", context)
            self.assertEqual(context["handoff"]["task_id"], task.id)
            self.assertTrue(context["handoff"]["required_outputs"])
            return "ok"

        with tempfile.TemporaryDirectory() as tmp:
            hive = NexusHiveEngine(tmp, worker_fn=worker)
            hive = hive.create_mission("fix code bug and verify tests", autostart=True)
            deadline = time.time() + 5
            while time.time() < deadline:
                progress = hive.get_progress(hive)
                if progress["total"] and progress["by_status"].get("succeeded") == progress["total"]:
                    break
                time.sleep(0.05)
            progress = hive.get_progress(hive)
            self.assertTrue(progress["contracts"])
            self.assertTrue(progress["handoffs"])
            self.assertTrue(seen)
            checkpoint_path = os.path.join(tmp, "workspace", "hive", f"{hive}_checkpoints.jsonl")
            self.assertTrue(os.path.exists(checkpoint_path))


class TestWorldModel(unittest.TestCase):
    def test_world_model_flags_destructive_shell(self):
        from core.world_model import WorldModel

        with tempfile.TemporaryDirectory() as tmp:
            result = WorldModel(tmp).simulate("bash", {"cmd": "rm -rf /"})
            self.assertEqual(result.risk_level, "critical")
            self.assertFalse(result.reversible)
            self.assertIn("block", result.summary())


class TestProviderHealth(unittest.TestCase):
    def test_provider_health_normalizes_auth_errors(self):
        from core.providers.health import ProviderHealthRegistry

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
        from core.discovery import NexusAutoDiscover

        with tempfile.TemporaryDirectory() as tmp:
            knowledge = os.path.join(tmp, "knowledge")
            os.makedirs(knowledge, exist_ok=True)
            with open(os.path.join(knowledge, "_rag_index_3_3.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            status = NexusAutoDiscover(tmp).get_repo_status()
        self.assertIn("RAG-Store=READY", status)

    def test_discovery_reports_registry_tools_not_legacy_script_folders(self):
        from core.discovery import NexusAutoDiscover

        tools = NexusAutoDiscover(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).discover_tools()
        names = {tool["name"] for tool in tools}
        self.assertIn("bash", names)
        self.assertIn("file_edit", names)
        self.assertNotIn("terminal", names)
        self.assertNotIn("file_ops", names)


class TestDashboardSecurityHelpers(unittest.TestCase):
    def test_dashboard_upload_helper_blocks_unsafe_extension(self):
        from dashboard import api
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            api.safe_upload_path("../../payload.exe")


class TestWorldModelScenario(unittest.TestCase):
    def test_file_edit_path_escape_is_critical(self):
        from core.world_model import WorldModel

        with tempfile.TemporaryDirectory() as tmp:
            result = WorldModel(tmp).simulate("file_edit", {"command": "delete", "path": "../outside.txt"})
            self.assertEqual(result.risk_level, "critical")


if __name__ == "__main__":
    unittest.main()
