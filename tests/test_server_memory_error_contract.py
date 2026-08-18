"""Memory API must keep internal storage/provider errors out of responses."""

from fastapi.testclient import TestClient

import security.core.auth as authentication
import memory
import apps.api as server


def _client(monkeypatch):
    token = "memory-error-test-token"
    monkeypatch.setattr(authentication, "_AUTH_TOKEN", token)
    client = TestClient(server.app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


class _BrokenMemory:
    def __init__(self, _root):
        pass

    def search_memory(self, _query, _memory_types):
        raise RuntimeError("database C:\\private\\memory.sqlite token=sk-live-memory")


def test_memory_search_returns_public_error_only(monkeypatch):
    monkeypatch.setattr(memory, "MemoryManager", _BrokenMemory)

    with _client(monkeypatch) as client:
        response = client.post("/api/memory/search", json={"query": "nexus"})

    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "Memory search unavailable"}
    assert "memory.sqlite" not in response.text
    assert "sk-live-memory" not in response.text
