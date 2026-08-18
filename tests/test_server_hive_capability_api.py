"""Integration tests for the main-agent <-> Hive HTTP boundary (§3).

These drive the real FastAPI app (`server.app`) through the new
``/api/hive/goal``, ``/api/hive/runs``, ``/api/hive/teams`` and
``/api/hive/runs/{id}/cancel`` endpoints, with a stubbed LLM so a goal can be
planned and executed end-to-end without a live model.
"""

import os
import sys
import types

import pytest


def _install_stub_llm(monkeypatch):
    """Force the Hive engine + capability to use a deterministic fake LLM."""
    import hive.capability as cap_mod

    async def fake_llm(messages):
        last = messages[-1]["content"] if messages else ""
        return "FINAL ANSWER: done for: " + last[:40]

    import apps.api as server_mod

    orig = server_mod._get_hive_capability

    def patched():
        cap = orig()
        cap._llm_call = fake_llm
        if cap._engine is not None:
            cap._engine.set_llm_call(fake_llm)
        return cap

    monkeypatch.setattr(server_mod, "_get_hive_capability", patched)


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Set auth env vars BEFORE importing server/authentication so the token is
    # picked up by the module-level _AUTH_TOKEN loader.
    monkeypatch.setenv("NEXUS_HIVE_ROOT", str(tmp_path / "hive_runs"))
    monkeypatch.setenv("NEXUS_DASHBOARD_TOKEN", "test-hive-token")
    import apps.api as server
    import security.core.auth as auth_mod
    # Override the cached token directly so the test is independent of the
    # order in which server/authentication were first imported in the session.
    monkeypatch.setattr(auth_mod, "_AUTH_TOKEN", "test-hive-token")

    from fastapi.testclient import TestClient

    # The server auth middleware gates every API route.  We authenticate the
    # TestClient with a dashboard bearer token (the same mechanism a real
    # local client uses) rather than disabling auth entirely.
    _install_stub_llm(monkeypatch)
    c = TestClient(server.app)
    c.headers["Authorization"] = "Bearer test-hive-token"
    return c


def test_hive_teams_endpoint_lists_templates(client):
    resp = client.get("/api/hive/teams")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["count"] >= 1
    names = [t["name"] for t in body["teams"]]
    assert any("Agent Team" in n for n in names)


def test_hive_goal_submit_then_list(client):
    resp = client.post("/api/hive/goal", json={
        "goal": "Build a small feature",
        "required_specializations": ["BACKEND_AGENT", "TESTER"],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    run = body["run"]
    assert run["status"] == "planned"
    run_id = run["hive_run_id"]

    # List runs should now include it.
    lst = client.get("/api/hive/runs").json()
    assert any(r["hive_run_id"] == run_id for r in lst["runs"])


def test_hive_goal_execute_end_to_end(client):
    resp = client.post("/api/hive/goal", json={
        "goal": "Research the API surface",
        "required_specializations": ["RESEARCHER"],
        "execute": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    run = body["run"]
    # The run should have actually executed and produced a verified result.
    assert run["status"] in ("completed", "failed")
    assert run["verification_result"]["agents"] >= 1
    assert run["verification_result"]["succeeded"] >= 1


def test_hive_run_cancel(client):
    resp = client.post("/api/hive/goal", json={
        "goal": "Long task",
        "required_specializations": ["RESEARCHER"],
    })
    run_id = resp.json()["run"]["hive_run_id"]
    cancel = client.post(f"/api/hive/runs/{run_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "success"
    # The canceled run must be retrievable as cancelled.
    lst = client.get("/api/hive/runs").json()
    matching = [r for r in lst["runs"] if r["hive_run_id"] == run_id]
    assert matching
    assert matching[0]["status"] == "cancelled"


def test_hive_goal_rejects_empty(client):
    resp = client.post("/api/hive/goal", json={"goal": ""})
    assert resp.status_code == 400
