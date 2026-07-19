from fastapi.testclient import TestClient


def test_active_session_endpoint_uses_current_session_bus_contract():
    from gui.api import app

    with TestClient(app) as client:
        response = client.get("/api/sessions/active")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["session_id"], str)
    assert isinstance(payload["history"], list)
