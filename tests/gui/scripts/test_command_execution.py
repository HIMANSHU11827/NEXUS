import json

from fastapi.testclient import TestClient

import security.core.auth
from apps.web import api
from security.permissions import PermissionMode, PermissionSystem


_TEST_DASHBOARD_TOKEN = "test-dashboard-token-command-execution"


def _authed_client(monkeypatch) -> TestClient:
    """Return a TestClient that authenticates like a real dashboard client.

    The API is protected by ``server.auth_middleware`` -> ``authentication.check_auth``.
    Rather than disabling that protection, the tests present a valid bearer token,
    exercising the same code path a real authenticated caller uses.
    """
    monkeypatch.setattr(authentication, "_AUTH_TOKEN", _TEST_DASHBOARD_TOKEN)
    client = TestClient(api.app)
    client.headers.update({"Authorization": f"Bearer {_TEST_DASHBOARD_TOKEN}"})
    return client


def _clean_permissions():
    permissions = PermissionSystem()
    old_mode = permissions.mode
    old_rules = list(permissions._rules)
    old_allowlist = list(permissions._pre_authorized_list)
    old_decisions = permissions.get_decision_log(limit=200)
    permissions.set_mode(PermissionMode.DEFAULT)
    permissions._pre_authorized_list = []
    permissions._decision_log = []
    return permissions, old_mode, old_rules, old_allowlist, old_decisions


def test_command_stream_uses_real_executor_and_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._LOOPS.clear()
    client = _authed_client(monkeypatch)

    response = client.post(
        "/api/work-events/run-command-stream",
        json={
            "session_id": "command-proof",
            "command": 'python -c "print(\'REAL_COMMAND_STREAM_OK\')"',
            "timeout": 30,
        },
    )

    assert response.status_code == 200
    assert "REAL_COMMAND_STREAM_OK" in response.text
    assert '"exit_code": 0' in response.text
    assert "tools.nexus_tools.bash_tool" not in response.text


def test_command_stream_terminal_event_replaces_started_sequence(tmp_path, monkeypatch):
    """A terminal event copied from start must not deadlock sequence allocation."""
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._LOOPS.clear()
    client = _authed_client(monkeypatch)

    response = client.post(
        "/api/work-events/run-command-stream",
        json={
            "session_id": "command-sequence-regression",
            "command": 'python -c "print(\'SEQUENCE_OK\')"',
            "timeout": 5,
        },
    )

    assert response.status_code == 200
    assert '"type": "done"' in response.text
    assert "SEQUENCE_OK" in response.text
    events = [
        json.loads(line)
        for line in (tmp_path / "command-sequence-regression.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["status"] for event in events] == ["running", "success"]
    assert events[0]["sequence"] < events[1]["sequence"]
    assert events[1]["source_sequence"] == events[0]["sequence"]


def test_command_stream_uses_shared_permission_decision_log(tmp_path, monkeypatch):
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _clean_permissions()
    try:
        monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
        api._LOOPS.clear()
        client = _authed_client(monkeypatch)

        response = client.post(
            "/api/work-events/run-command-stream",
            json={
                "session_id": "permission-proof",
                "turn_id": "turn-1",
                "command": "rm -rf important",
                "timeout": 30,
            },
        )

        assert response.status_code == 200
        assert "Command blocked by permission policy" in response.text
        decisions = permissions.get_decision_log(limit=5)
        assert decisions[-1]["tool"] == "terminal"
        assert decisions[-1]["surface"] == "gui"
        assert decisions[-1]["session_id"] == "permission-proof"
        assert decisions[-1]["turn_id"] == "turn-1"
        assert decisions[-1]["granted"] is False
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions
        api._LOOPS.clear()


def test_command_stream_forwards_requested_timeout_and_surfaces_timeout_error(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
    api._LOOPS.clear()
    calls = []

    class FakeSandbox:
        last_exit_code = -1

        def __init__(self, root_dir):
            self.root_dir = root_dir

        async def stream_execute(self, command, workdir=None, timeout=None, shell=None):
            calls.append(timeout)
            yield "[SANDBOX_TIMEOUT]: Execution exceeded 5 seconds."

    monkeypatch.setattr("sandbox.sandbox_manager.SovereignSandbox", FakeSandbox)
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _clean_permissions()
    try:
        permissions.set_mode(PermissionMode.BYPASS)
        client = _authed_client(monkeypatch)
        response = client.post(
            "/api/work-events/run-command-stream",
            json={"session_id": "timeout-proof", "command": "slow", "timeout": 5},
        )
        assert response.status_code == 200
        assert calls == [5]
        assert '"exit_code": -1' in response.text
        assert '"stderr": "[SANDBOX_TIMEOUT]' in response.text
    finally:
        permissions.set_mode(old_mode)
        permissions._rules = old_rules
        permissions._pre_authorized_list = old_allowlist
        permissions._decision_log = old_decisions
        api._LOOPS.clear()
