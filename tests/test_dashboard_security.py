import json
import os
import tempfile
import unittest
from unittest.mock import patch


class TestDashboardSecurityHelpers(unittest.TestCase):
    def test_session_id_is_sanitized(self):
        from dashboard.api import safe_session_id

        self.assertEqual(safe_session_id("../evil.json"), "evil")
        self.assertEqual(safe_session_id("..\\evil.json"), "evil")
        self.assertEqual(safe_session_id("bad id!"), "bad_id")
        self.assertEqual(safe_session_id(""), "default")

    def test_upload_path_blocks_unsafe_types_and_traversal(self):
        from dashboard.api import safe_upload_path

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
                                "hive_id": "HIVE-1",
                                "role": "ARCHITECT",
                                "status": "succeeded",
                                "updated_at": 10,
                            },
                            {
                                "hive_id": "HIVE-1",
                                "role": "QA_EXPERT",
                                "status": "failed",
                                "updated_at": 11,
                            },
                        ]
                    },
                    f,
                )
            with patch("dashboard.api._ROOT", tmp):
                from dashboard.api import load_hive_state

                state = load_hive_state()
        self.assertEqual(state[0]["id"], "HIVE-1")
        self.assertEqual(state[0]["by_status"]["succeeded"], 1)
        self.assertEqual(state[0]["by_status"]["failed"], 1)

    def test_provider_state_does_not_mark_missing_cloud_key_active(self):
        from dashboard.api import build_provider_state

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
        from dashboard.api import app

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
        import dashboard.api as api

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "logs", "sessions"), exist_ok=True)
            with open(os.path.join(tmp, "logs", "sessions", "session_x.json"), "w", encoding="utf-8") as f:
                f.write("[]")
            with patch("dashboard.api._ROOT", tmp):
                api._LOOPS.clear()
                client = TestClient(api.app)
                response = client.delete("/api/sessions/session_x")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["deleted"])
                self.assertFalse(os.path.exists(os.path.join(tmp, "logs", "sessions", "session_x.json")))
                blocked = client.delete("/api/sessions/default")
                self.assertEqual(blocked.status_code, 400)


if __name__ == "__main__":
    unittest.main()
