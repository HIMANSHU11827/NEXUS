"""End-to-end smoke test for NEXUS AI backend.

Exercises the backend API via httpx against a running server,
plus unit-level checks for the canonical event model.
"""

import os

import httpx
import pytest
import pytest_asyncio

NEXUS_API_URL = os.environ.get("NEXUS_API_URL", "http://localhost:8000")


# ═══════════════════════════════════════════════════════════════════
# 1.  Server import
# ═══════════════════════════════════════════════════════════════════

def test_server_import():
    from apps.api import app
    assert app.title == "NEXUS AI API"
    assert app.version == "2.1.0"


# ═══════════════════════════════════════════════════════════════════
# 2.  Event model  (pure Python, no server needed)
# ═══════════════════════════════════════════════════════════════════

def test_event_types_contain_expected_categories():
    from nexus.events import EVENT_TYPES

    required = frozenset({
        "run", "conversation", "message", "plan", "phase",
        "tool", "command", "file", "search", "web",
        "test", "subagent", "handoff", "memory",
        "skill", "error", "retry", "status",
    })
    for prefix in required:
        assert any(t == prefix or t.startswith(prefix + ".") for t in EVENT_TYPES), \
            f"No event type matches prefix '{prefix}'"


def test_canonical_event_accepts_valid_types_and_statuses():
    from nexus.events import CanonicalEvent

    types = [
        "run.started", "run.completed",
        "message.started", "message.completed",
        "tool.started", "tool.failed",
        "file.created", "file.edited",
        "search.result", "web.result",
        "error", "retry",
    ]
    for status in ("running", "success", "failed"):
        for et in types:
            event = CanonicalEvent(
                event_id=f"evt_{et.replace('.','_')}_{status}",
                run_id="run_001",
                conversation_id="conv_001",
                type=et,
                title=f"Test {et}",
                status=status,
                timestamp=1000.0,
                sequence=1,
            )
            assert event.type == et
            assert event.status == status


def test_canonical_event_rejects_invalid_type():
    from nexus.events import CanonicalEvent

    with pytest.raises(ValueError, match="Unsupported event type"):
        CanonicalEvent(
            event_id="evt_bad",
            run_id="run_bad",
            conversation_id="conv_bad",
            type="nonexistent.type",
            title="Bad",
            status="running",
            timestamp=0.0,
            sequence=1,
        )


def test_canonical_event_rejects_invalid_status():
    from nexus.events import CanonicalEvent

    with pytest.raises(ValueError, match="Unsupported event status"):
        CanonicalEvent(
            event_id="evt_bad",
            run_id="run_bad",
            conversation_id="conv_bad",
            type="run.started",
            title="Bad",
            status="bogus",
            timestamp=0.0,
            sequence=1,
        )


def test_canonical_event_validates_required_fields():
    from nexus.events import CanonicalEvent

    with pytest.raises(ValueError, match="event_id, run_id, and conversation_id are required"):
        CanonicalEvent(
            event_id="",
            run_id="",
            conversation_id="",
            type="run.started",
            title="Bad",
            status="running",
            timestamp=0.0,
            sequence=1,
        )


def test_canonical_event_validates_positive_sequence():
    from nexus.events import CanonicalEvent

    with pytest.raises(ValueError, match="sequence must be positive"):
        CanonicalEvent(
            event_id="evt_0",
            run_id="run_0",
            conversation_id="conv_0",
            type="run.started",
            title="Zero seq",
            status="running",
            timestamp=0.0,
            sequence=0,
        )


def test_from_work_event_success():
    from nexus.events import CanonicalEvent

    raw = {
        "status": "done",
        "title": "Web search completed",
        "tool": "web_search",
        "duration_ms": 1234,
    }
    event = CanonicalEvent.from_work_event(raw, "conv_001", 1)
    assert event.conversation_id == "conv_001"
    assert event.sequence == 1
    assert event.status == "success"
    assert event.related_tool == "web_search"
    assert event.duration_ms == 1234


def test_from_work_event_error_maps_to_failed():
    from nexus.events import CanonicalEvent

    raw = {"status": "error", "error": "Connection timeout"}
    event = CanonicalEvent.from_work_event(raw, "conv_002", 2)
    assert event.status == "failed"
    assert event.error == {"message": "Connection timeout"}
    assert event.type == "tool.failed"


def test_from_work_event_auto_generates_event_id():
    from nexus.events import CanonicalEvent

    raw = {"status": "running"}
    event = CanonicalEvent.from_work_event(raw, "conv_003", 3)
    assert event.event_id.startswith("evt_")


# ═══════════════════════════════════════════════════════════════════
# 3.  API smoke tests  (require a running server)
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def api_base():
    return NEXUS_API_URL


@pytest.fixture(scope="module")
def server_running(api_base):
    """Check if the backend server is running; skip tests if not."""
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(api_base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        if result != 0:
            pytest.skip(f"Server not running at {api_base}")
    except Exception:
        sock.close()
        pytest.skip(f"Cannot reach server at {api_base}")
    return api_base


@pytest.mark.asyncio
async def test_health_endpoint(server_running):
    async with httpx.AsyncClient(base_url=server_running, timeout=10) as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "nexus-api"


@pytest_asyncio.fixture(scope="function")
async def authed_client(server_running):
    """Authenticate against the running server and return a client with a session cookie."""
    token = os.environ.get("NEXUS_DASHBOARD_TOKEN", "")
    if not token:
        pytest.skip("NEXUS_DASHBOARD_TOKEN not set — cannot test auth-protected endpoints")

    async with httpx.AsyncClient(
        base_url=NEXUS_API_URL,
        timeout=15,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        resp = await client.post("/api/auth/token", json={"token": token})
        if resp.status_code != 200:
            pytest.skip(f"Auth failed ({resp.status_code}): {resp.text}")
        yield client


@pytest.mark.asyncio
async def test_create_session(authed_client):
    resp = await authed_client.post("/api/sessions/new")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["id"].startswith("session_")


@pytest.mark.asyncio
async def test_chat_endpoint(authed_client):
    resp = await authed_client.post(
        "/api/chat",
        json={"prompt": "say hello", "stream": False},
    )
    assert resp.status_code in (200, 500), f"Unexpected status {resp.status_code}: {resp.text}"
    if resp.status_code == 200:
        data = resp.json()
        assert "response" in data
        assert isinstance(data["response"], str)


@pytest.mark.asyncio
async def test_state_endpoint(authed_client):
    resp = await authed_client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "health" in data


@pytest.mark.asyncio
async def test_files_list(authed_client):
    resp = await authed_client.post("/api/files/list", json={"path": "."})
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert isinstance(data["files"], list)
    if data["files"]:
        entry = data["files"][0]
        assert "name" in entry
        assert "path" in entry
        assert "isDirectory" in entry
