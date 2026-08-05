"""Tests for OpenAI-compatible API endpoints (/v1/models, /v1/chat/completions).

Mocks heavy dependencies at their source modules before importing server.
"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _global_mocks():
    """Patch heavy deps at their source before any server import."""
    patches = [
        patch("dotenv.load_dotenv"),
        patch("orchestrators.NexusLoop"),
        patch("authentication.check_auth", return_value=MagicMock()),
        patch("authentication.is_public_path", return_value=True),
        patch("authentication.AuthUser"),
        patch("authentication.validate_dashboard_token", return_value=True),
        patch("yaml.safe_load", return_value={}),
        patch("yaml.safe_dump"),
    ]
    for p in patches:
        p.start()
    # Prevent server module from being cached across tests
    for mod in list(sys.modules.keys()):
        if mod.startswith("server"):
            del sys.modules[mod]
    yield
    for p in patches:
        p.stop()


@pytest.fixture
def client():
    """Build a TestClient from the (now safely mockable) server app."""
    from server import app
    with TestClient(app) as c:
        yield c


class TestV1Models:
    def test_list_models_returns_list(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_list_models_has_deepseek_fallback(self, client):
        resp = client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        assert "deepseek-chat" in ids

    def test_list_models_no_auth_required(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200


class TestV1ChatCompletions:
    def test_missing_messages_returns_400(self, client):
        resp = client.post("/v1/chat/completions", json={})
        assert resp.status_code == 400

    def test_empty_messages_returns_400(self, client):
        resp = client.post("/v1/chat/completions", json={"messages": []})
        assert resp.status_code == 400

    def test_assistant_only_messages_work(self, client):
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "assistant", "content": "Hello"}]
        })
        assert resp.status_code == 200

    def test_system_only_messages_works(self, client):
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "system", "content": "You are a helpful assistant."}]
        })
        assert resp.status_code == 200

    def test_invalid_json_returns_400(self, client):
        resp = client.post("/v1/chat/completions", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 400

    def _setup_mock_loop(self, fake_stream_run):
        """Patch server.get_loop to return a mock with the given stream_run."""
        fake_loop = MagicMock()
        fake_loop.memory = []
        fake_loop.session_id = "test"
        fake_loop.stream_run = fake_stream_run
        self._get_loop_patch = patch("server.get_loop", return_value=fake_loop)
        self._get_loop_patch.start()
        return fake_loop

    def teardown_method(self):
        if hasattr(self, "_get_loop_patch"):
            self._get_loop_patch.stop()

    def test_valid_request_returns_openai_format(self, client):
        async def fake_stream_run(*args, **kwargs):
            yield {"type": "content", "data": "Hello from NEXUS!"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.session_id = "test"
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": False,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "chat.completion"
        assert "choices" in body
        assert len(body["choices"]) == 1
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["message"]["content"] == "Hello from NEXUS!"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert "usage" in body
        assert body["usage"]["prompt_tokens"] > 0
        assert body["usage"]["completion_tokens"] > 0

    def test_same_second_requests_get_unique_completion_and_session_ids(self, client):
        async def fake_stream_run(*args, **kwargs):
            yield {"type": "content", "data": "ok"}

        fake_loop = MagicMock()
        fake_loop.stream_run = fake_stream_run
        session_ids = []

        def capture_loop(session_id):
            session_ids.append(session_id)
            return fake_loop

        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        }
        with patch("server.get_loop", side_effect=capture_loop), patch("server.time.time", return_value=1_700_000_000):
            first = client.post("/v1/chat/completions", json=payload)
            second = client.post("/v1/chat/completions", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"].startswith("chatcmpl-")
        assert second.json()["id"].startswith("chatcmpl-")
        assert first.json()["id"] != second.json()["id"]
        assert len(session_ids) == 2
        assert all(session_id.startswith("openai_") for session_id in session_ids)
        assert session_ids[0] != session_ids[1]

    @pytest.mark.asyncio
    async def test_loop_eviction_closes_only_evicted_loop(self):
        import server

        evicted = MagicMock()
        evicted.aclose = AsyncMock()
        retained = MagicMock()
        retained.aclose = AsyncMock()

        with patch.object(server, "_MAX_LOOPS", 1), patch.dict(
            server._LOOPS,
            {"old": evicted, "new": retained},
            clear=True,
        ):
            server._trim_loops()
            await asyncio.sleep(0)

            assert list(server._LOOPS) == ["new"]
            evicted.aclose.assert_awaited_once_with()
            retained.aclose.assert_not_awaited()

    def test_model_routing_deepseek(self, client):
        async def fake_stream_run(prompt, provider, model, **kwargs):
            assert provider == "deepseek"
            assert model == "deepseek-chat"
            yield {"type": "content", "data": "ok"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })
        assert resp.status_code == 200

    def test_model_routing_gpt(self, client):
        async def fake_stream_run(prompt, provider, model, **kwargs):
            assert provider == "openai"
            yield {"type": "content", "data": "ok"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })
        assert resp.status_code == 200

    def test_model_routing_claude(self, client):
        async def fake_stream_run(prompt, provider, model, **kwargs):
            assert provider == "anthropic"
            yield {"type": "content", "data": "ok"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "model": "claude-sonnet-4-20250514",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })
        assert resp.status_code == 200

    def test_model_routing_gemini(self, client):
        async def fake_stream_run(prompt, provider, model, **kwargs):
            assert provider == "gemini"
            yield {"type": "content", "data": "ok"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "model": "gemini-2.0-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        })
        assert resp.status_code == 200

    def test_defaults_to_deepseek(self, client):
        async def fake_stream_run(prompt, provider, model, **kwargs):
            assert provider == "deepseek"
            yield {"type": "content", "data": "ok"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 200

    def test_max_tokens_passed_through(self, client):
        captured = {}

        async def fake_stream_run(*args, **kwargs):
            captured.update(kwargs)
            yield {"type": "content", "data": "ok"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 2048,
            "stream": False,
        })
        assert resp.status_code == 200
        assert captured["max_tokens"] == 2048

    def test_invalid_max_tokens_returns_400(self, client):
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": "many",
        })

        assert resp.status_code == 400

    def test_streaming_returns_sse(self, client):
        async def fake_stream_run(*args, **kwargs):
            yield {"type": "content", "data": "Hello"}
            yield {"type": "content", "data": " World"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Say hi"}],
            "stream": True,
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
        body = resp.text
        assert "data: " in body
        assert "[DONE]" in body

    def test_no_auth_required(self, client):
        async def fake_stream_run(*args, **kwargs):
            yield {"type": "content", "data": "ok"}

        fake_loop = self._setup_mock_loop(fake_stream_run)
        fake_loop.load_memory = MagicMock()

        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 200
