import sys
import os
import json
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGuiSecurityHelpers(unittest.TestCase):
    def test_session_id_is_sanitized(self):
        from gui.api import safe_session_id

        self.assertEqual(safe_session_id("../evil.json"), "evil")
        self.assertEqual(safe_session_id("..\\evil.json"), "evil")
        self.assertEqual(safe_session_id("bad id!"), "bad_id")
        self.assertEqual(safe_session_id(""), "default")

    def test_upload_path_blocks_unsafe_types_and_traversal(self):
        from gui.api import safe_upload_path

        allowed = safe_upload_path("../notes.md")
        self.assertTrue(allowed.endswith(os.path.join("uploads", "notes.md")))
        with self.assertRaises(Exception):
            safe_upload_path("../secret.exe")

    def test_hive_state_reads_real_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = os.path.join(tmp, "logs", "hive")
            os.makedirs(logs, exist_ok=True)
            with open(os.path.join(logs, "hive_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "tasks": [
                            {
                                "id": "TASK-A",
                                "hive_id": "HIVE-1",
                                "role": "ARCHITECT",
                                "status": "succeeded",
                                "updated_at": 10,
                            },
                            {
                                "id": "TASK-B",
                                "hive_id": "HIVE-1",
                                "role": "QA_EXPERT",
                                "status": "failed",
                                "updated_at": 11,
                            },
                        ],
                        "artifacts": [
                            {
                                "task_id": "TASK-A",
                                "role": "ARCHITECT",
                                "content": "changed_files: core/router.py",
                                "metadata": {"quality": "complete", "missing_outputs": [], "score": 1.0},
                            },
                            {
                                "task_id": "TASK-B",
                                "role": "QA_EXPERT",
                                "content": '{"files_touched": ["core/router.py"]}',
                                "metadata": {"quality": "incomplete", "missing_outputs": ["commands"], "score": 0.5},
                            },
                        ],
                    },
                    f,
                )
            with patch("gui.api._ROOT", tmp):
                from gui.api import load_hive_state

                state = load_hive_state()
        self.assertEqual(state[0]["id"], "HIVE-1")
        self.assertEqual(state[0]["by_status"]["succeeded"], 1)
        self.assertEqual(state[0]["by_status"]["failed"], 1)
        self.assertEqual(state[0]["conflict_count"], 1)
        self.assertIn("core/router.py", state[0]["conflicts"])
        self.assertEqual(state[0]["weak_artifact_count"], 1)

    def test_hive_merge_plan_endpoint_reads_manifest_conflicts(self):
        from fastapi.testclient import TestClient
        import gui.api as api

        with tempfile.TemporaryDirectory() as tmp:
            logs = os.path.join(tmp, "logs", "hive")
            os.makedirs(logs, exist_ok=True)
            with open(os.path.join(logs, "hive_manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "tasks": [
                            {"id": "TASK-1", "hive_id": "HIVE-M", "role": "ENGINEER", "status": "succeeded"},
                            {"id": "TASK-2", "hive_id": "HIVE-M", "role": "AUDITOR", "status": "succeeded"},
                        ],
                        "artifacts": [
                            {
                                "task_id": "TASK-1",
                                "role": "ENGINEER",
                                "content": "changed_files: hive/engine.py",
                                "metadata": {"quality": "complete", "missing_outputs": [], "score": 1.0},
                            },
                            {
                                "task_id": "TASK-2",
                                "role": "AUDITOR",
                                "content": "files_touched: hive/engine.py",
                                "metadata": {"quality": "incomplete", "missing_outputs": ["findings"], "score": 0.5},
                            },
                        ],
                    },
                    f,
                )
            with patch("gui.api._ROOT", tmp):
                client = TestClient(api.app)
                response = client.get("/api/hive/HIVE-M/merge-plan")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["conflict_count"], 1)
        self.assertIn("hive/engine.py", data["conflicts"])
        self.assertEqual(data["artifacts"][1]["quality"]["quality"], "incomplete")
        self.assertTrue(data["recommendations"])

    def test_hive_resume_endpoint_uses_kernel_hive(self):
        from fastapi.testclient import TestClient
        import gui.api as api

        class Hive:
            def __init__(self):
                self.seen = None

            def resume_hive(self, hive_id):
                self.seen = hive_id
                return {"hive_id": hive_id, "pending": 1, "started_workers": True}

        class Kernel:
            hive = Hive()

        with patch("kernel.get_nexus_kernel", return_value=Kernel):
            client = TestClient(api.app)
            response = client.post("/api/hive/HIVE-API/resume")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["started_workers"])

    def test_provider_state_does_not_mark_missing_cloud_key_active(self):
        from gui.api import build_provider_state

        class Config:
            data = {
                "providers": {
                    "cloud": {"openrouter": {"active": True, "api_key": "", "model": "m"}},
                    "local": {"ollama": {"active": True, "default_model": "llama3"}},
                }
            }

        class Kernel:
            config = Config()

        providers, instances = build_provider_state(Kernel())
        statuses = {p["id"]: p["status"] for p in providers}
        self.assertEqual(statuses["openrouter"], "AUTH_MISSING")
        self.assertEqual(statuses["ollama"], "ACTIVE")
        self.assertEqual(len(instances), 2)

    def test_local_only_allows_fastapi_testclient_smoke(self):
        from fastapi.testclient import TestClient
        from gui.api import app

        client = TestClient(app)
        response = client.get("/api/sessions")
        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 200)
        audit = client.get("/api/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertIn("roadmap", audit.json())
        self.assertIn("unified_graph", audit.json())

    def test_delete_session_endpoint_removes_file_and_blocks_default(self):
        from fastapi.testclient import TestClient
        import gui.api as api

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "logs", "sessions"), exist_ok=True)
            with open(os.path.join(tmp, "logs", "sessions", "session_x.json"), "w", encoding="utf-8") as f:
                f.write("[]")
            with patch("gui.api._ROOT", tmp):
                api._LOOPS.clear()
                client = TestClient(api.app)
                response = client.delete("/api/sessions/session_x")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["deleted"])
                self.assertFalse(os.path.exists(os.path.join(tmp, "logs", "sessions", "session_x.json")))
                with open(os.path.join(tmp, "logs", "sessions", "default.json"), "w", encoding="utf-8") as f:
                    f.write('[{"role":"user","content":"hello"}]')
                cleared = client.delete("/api/sessions/default")
                self.assertEqual(cleared.status_code, 200)
                self.assertTrue(cleared.json().get("cleared"))
                with open(os.path.join(tmp, "logs", "sessions", "default.json"), "r", encoding="utf-8") as f:
                    self.assertEqual(json.load(f), [])


if __name__ == "__main__":
    unittest.main()

