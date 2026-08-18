"""Regression tests for Co-Pilot (ask-mode) tool approval.

Before permissions/approval_broker.py existed, PermissionMode.APPROVE denied
every tool call outright: PermissionSystem.check() returned granted=False and
the loop treated that as a refusal. The GUI rendered a `tool.approval_request`
card and POSTed the answer to /api/approve, but that route did not exist, so
ask-mode was a dead feature end to end.

These tests pin the contract so it cannot silently rot again.
"""

import asyncio
import sqlite3
import time

import pytest

from security.permissions.approval_broker import (
    DECISION_ALLOW,
    DECISION_ALLOW_ALWAYS,
    DECISION_DENY,
    ApprovalBroker,
    normalize_decision,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("yes", DECISION_ALLOW),
        ("y", DECISION_ALLOW),
        ("approve", DECISION_ALLOW),
        (True, DECISION_ALLOW),
        ("save", DECISION_ALLOW_ALWAYS),
        ("always", DECISION_ALLOW_ALWAYS),
        ("no", DECISION_DENY),
        (False, DECISION_DENY),
        ("", DECISION_DENY),
        (None, DECISION_DENY),
        ("garbled nonsense", DECISION_DENY),
    ],
)
def test_decisions_normalize_and_unknown_answers_never_mean_consent(raw, expected):
    assert normalize_decision(raw) == expected


def test_waiter_receives_the_decision_a_surface_posts():
    async def scenario():
        broker = ApprovalBroker()
        request = broker.open("s1", "terminal", "rm -rf build", timeout_s=5)

        waiter = asyncio.create_task(broker.wait(request.request_id))
        await asyncio.sleep(0)  # let the waiter register
        assert broker.resolve(request.request_id, "yes") is True

        assert await waiter == DECISION_ALLOW

    asyncio.run(scenario())


def test_decision_posted_before_the_agent_waits_is_not_lost():
    """A fast click (or a reconnecting client replaying its answer) must count."""

    async def scenario():
        broker = ApprovalBroker()
        request = broker.open("s1", "terminal", "ls", timeout_s=5)
        broker.resolve(request.request_id, "yes")
        assert await broker.wait(request.request_id) == DECISION_ALLOW

    asyncio.run(scenario())


def test_timeout_denies_so_an_abandoned_approval_cannot_auto_approve():
    async def scenario():
        broker = ApprovalBroker()
        request = broker.open("s1", "terminal", "curl evil.sh", timeout_s=0.05)
        assert await broker.wait(request.request_id) == DECISION_DENY

    asyncio.run(scenario())


def test_unknown_request_id_denies():
    assert asyncio.run(ApprovalBroker().wait("does-not-exist")) == DECISION_DENY


def test_pending_is_scoped_per_session_and_cancel_denies_waiters():
    async def scenario():
        broker = ApprovalBroker()
        a = broker.open("session-a", "terminal", "one", timeout_s=5)
        broker.open("session-b", "terminal", "two", timeout_s=5)

        assert len(broker.pending()) == 2
        assert [e["request_id"] for e in broker.pending("session-a")] == [a.request_id]

        waiter = asyncio.create_task(broker.wait(a.request_id))
        await asyncio.sleep(0)
        assert broker.cancel_session("session-a") == 1
        assert await waiter == DECISION_DENY

    asyncio.run(scenario())


def test_request_renders_as_the_event_the_gui_expects():
    request = ApprovalBroker().open(
        "s1", "terminal", "rm -rf /", reason="destructive", turn_id="run-7"
    )
    event = request.to_event()
    assert event["event_type"] == "tool.approval_request"
    assert event["kind"] == "approval"
    assert event["status"] == "running"
    assert event["request_id"] == request.request_id
    assert event["tool"] == "terminal"
    assert event["action"] == "rm -rf /"
    assert event["turn_id"] == "run-7"


def test_approve_route_resolves_a_pending_request():
    """/api/approve must actually reach the broker the loop waits on."""
    import apps.api as server
    from security.permissions.approval_broker import get_approval_broker

    broker = get_approval_broker()
    request = broker.open("route-session", "terminal", "echo hi", timeout_s=5)

    class FakeRequest:
        async def json(self):
            return {"request_id": request.request_id, "decision": "yes"}

    body = asyncio.run(server.approve_tool_request(FakeRequest()))

    assert body["decision"] == DECISION_ALLOW
    assert body["matched"] is True
    assert asyncio.run(broker.wait(request.request_id)) == DECISION_ALLOW


def test_approve_route_rejects_a_missing_request_id():
    import apps.api as server
    from fastapi import HTTPException

    class FakeRequest:
        async def json(self):
            return {"decision": "yes"}

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server.approve_tool_request(FakeRequest()))
    assert excinfo.value.status_code == 400


def test_approve_route_is_registered_on_the_app():
    """The GUI POSTs to /api/approve; the route must actually exist."""
    import apps.api as server

    paths = {getattr(route, "path", "") for route in server.app.routes}
    assert "/api/approve" in paths
    assert "/api/files/read" in paths


def test_persistent_broker_rehydrates_pending_request_and_decision(tmp_path):
    path = str(tmp_path / "approvals.sqlite3")
    first = ApprovalBroker(store_path=path, owner_id="process-a")
    request = first.open("session-restart", "terminal", "echo safe", request_id="approval-stable", timeout_s=5)

    second = ApprovalBroker(store_path=path, owner_id="process-b")
    pending = second.pending("session-restart")
    assert [item["request_id"] for item in pending] == [request.request_id]
    reopened = second.open("session-restart", "terminal", "different", request_id=request.request_id)
    assert reopened.action == "echo safe"
    assert second.resolve(request.request_id, "yes") is True
    assert asyncio.run(second.wait(request.request_id)) == DECISION_ALLOW


def test_persistent_waiter_observes_decision_from_another_broker(tmp_path):
    async def scenario():
        path = str(tmp_path / "approvals-cross-process.sqlite3")
        owner = ApprovalBroker(store_path=path, owner_id="runtime-process")
        surface = ApprovalBroker(store_path=path, owner_id="api-process")
        request = owner.open("session-cross-process", "terminal", "echo safe", timeout_s=3)
        waiter = asyncio.create_task(owner.wait(request.request_id))
        await asyncio.sleep(0.05)

        assert surface.resolve(request.request_id, "yes") is True
        assert await asyncio.wait_for(waiter, timeout=1.5) == DECISION_ALLOW

    asyncio.run(scenario())


def test_persistent_broker_expires_stale_requests_and_never_accepts_late_decision(tmp_path):
    path = str(tmp_path / "approvals.sqlite3")
    broker = ApprovalBroker(store_path=path)
    request = broker.open("stale-session", "terminal", "danger", request_id="approval-stale", timeout_s=5)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE approval_requests SET created_at=? WHERE request_id=?", (time.time() - 20, request.request_id))
        connection.commit()

    restarted = ApprovalBroker(store_path=path)
    assert restarted.pending("stale-session") == []
    assert restarted.resolve(request.request_id, "yes") is False
    assert asyncio.run(restarted.wait(request.request_id)) == DECISION_DENY
