from fastapi.testclient import TestClient

from gui import api
from permissions import PermissionMode, PermissionSystem


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
    client = TestClient(api.app)

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


def test_command_stream_uses_shared_permission_decision_log(tmp_path, monkeypatch):
    permissions, old_mode, old_rules, old_allowlist, old_decisions = _clean_permissions()
    try:
        monkeypatch.setattr(api, "_WORK_EVENTS_DIR", str(tmp_path))
        api._LOOPS.clear()
        client = TestClient(api.app)

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
