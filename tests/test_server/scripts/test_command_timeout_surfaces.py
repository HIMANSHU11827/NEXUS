import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_server_command_stream_forwards_timeout_and_matches_failed_status(monkeypatch, tmp_path):
    patches = [
        patch("dotenv.load_dotenv"),
        patch("security.core.auth.check_auth", return_value=MagicMock()),
        patch("security.core.auth.is_public_path", return_value=True),
        patch("security.core.auth.validate_dashboard_token", return_value=True),
        patch("yaml.safe_load", return_value={}),
    ]
    for item in patches:
        item.start()
    try:
        for mod in list(sys.modules):
            if mod.startswith("apps.api"):
                del sys.modules[mod]
        import apps.api as server

        monkeypatch.setattr(server, "_RUN_ROOT", str(tmp_path), raising=False)
        monkeypatch.setattr(server, "_WORK_EVENTS_DIR", str(tmp_path / "events"), raising=False)
        calls = []

        class FakeSandbox:
            last_exit_code = -1

            def __init__(self, root_dir):
                self.root_dir = root_dir

            async def stream_execute(self, command, workdir=None, timeout=None, shell=None):
                calls.append((timeout, shell))
                yield "[SANDBOX_TIMEOUT]: Execution exceeded 7 seconds."

        monkeypatch.setattr("sandbox.sandbox_manager.SovereignSandbox", FakeSandbox)
        with TestClient(server.app) as client:
            response = client.post(
                "/api/work-events/run-command-stream",
                json={"session_id": "server-timeout", "command": "slow", "timeout": 7},
            )

        assert response.status_code == 200
        assert calls == [(7, "powershell")]
        assert '"status": "failed"' in response.text
        assert '"stderr": "[SANDBOX_TIMEOUT]' in response.text
        assert '"type": "done", "status": "failed"' in response.text
        events = server.list_work_events("server-timeout", limit=100)
        assert len(events) == 1
        assert events[0]["status"] == "failed"
        assert events[0].get("event_id") == events[0].get("id")
    finally:
        for item in reversed(patches):
            item.stop()
