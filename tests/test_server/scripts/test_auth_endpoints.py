"""Tests for auth-protected endpoints and public endpoints.

Mocks heavy dependencies at their source modules before importing server.
"""
import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _global_mocks():
    """Patch heavy deps at their source before any server import."""
    patches = [
        patch("dotenv.load_dotenv"),
        patch("orchestrators.loop.NexusLoop"),
        patch("authentication.check_auth", return_value=MagicMock()),
        patch("authentication.is_public_path", return_value=True),
        patch("authentication.AuthUser"),
        patch("authentication.validate_dashboard_token", return_value=True),
        patch("yaml.safe_load", return_value={}),
        patch("yaml.safe_dump"),
    ]
    for p in patches:
        p.start()
    for mod in list(sys.modules.keys()):
        if mod.startswith("server"):
            del sys.modules[mod]
    yield
    for p in patches:
        p.stop()


@pytest.fixture
def client():
    from server import app
    with TestClient(app) as c:
        yield c


class TestPublicEndpoints:
    def test_shutdown_accepts_non_awaitable_loop_test_double(self):
        from server import _drain_loop_finalizers

        loop = MagicMock()
        loop.aclose.return_value = None
        asyncio.run(_drain_loop_finalizers([loop]))

        loop.aclose.assert_called_once_with()

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_features_returns_200_with_feature_flags(self, client):
        resp = client.get("/api/features")
        assert resp.status_code == 200
        data = resp.json()
        assert "features" in data
        assert isinstance(data["features"], dict)

    def test_version_returns_200(self, client):
        resp = client.get("/api/version")
        assert resp.status_code == 200

    def test_auth_status_returns_unauthenticated(self, client):
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    def test_set_agent_returns_success_payload(self, client):
        resp = client.post("/api/agent", json={"agent": "researcher"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "success", "agent": "researcher"}

    def test_permission_decisions_endpoint_returns_scrubbed_log(self, client):
        from permissions import PermissionMode, PermissionSystem

        permissions = PermissionSystem()
        old_mode = permissions.mode
        old_rules = list(permissions._rules)
        old_decisions = permissions.get_decision_log(limit=200)
        try:
            permissions._decision_log = []
            permissions.set_mode(PermissionMode.DEFAULT)
            permissions.add_rule("terminal", "*", False)
            permissions.check("terminal", "echo token=super-secret sk-proj-abc123456789")

            resp = client.get("/api/permissions/decisions?limit=5")

            assert resp.status_code == 200
            payload = resp.json()
            assert payload["status"] == "success"
            assert payload["decisions"][-1]["source"] == "rule:deny"
            assert "super-secret" not in payload["decisions"][-1]["action_preview"]
            assert "sk-proj-abc123456789" not in payload["decisions"][-1]["action_preview"]
            assert "[REDACTED]" in payload["decisions"][-1]["action_preview"]
        finally:
            permissions.set_mode(old_mode)
            permissions._rules = old_rules
            permissions._decision_log = old_decisions


class TestAuthRequiredEndpoints:
    @pytest.fixture(autouse=True)
    def _no_auth(self):
        for mod in list(sys.modules.keys()):
            if mod.startswith("server"):
                del sys.modules[mod]
        patcher = patch("authentication.check_auth", return_value=None)
        patcher.start()
        yield
        patcher.stop()

    def test_sessions_returns_401_without_token(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 401

    def test_engine_status_returns_401_without_token(self, client):
        resp = client.get("/api/engine/status")
        assert resp.status_code == 401

    def test_openai_compatible_chat_requires_auth_by_default(self, client):
        resp = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        assert resp.status_code == 401
