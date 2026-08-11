import pytest
from fastapi import HTTPException

import server


def test_session_creation_returns_public_error_only(monkeypatch):
    secret_error = "sqlite path=C:\\private\\sessions.db token=sk-live-session"
    monkeypatch.setattr(
        server,
        "get_loop",
        lambda _session_id: (_ for _ in ()).throw(RuntimeError(secret_error)),
    )

    with pytest.raises(HTTPException) as raised:
        server.create_session()

    assert raised.value.status_code == 500
    assert raised.value.detail == "Session creation unavailable"
    assert secret_error not in raised.value.detail


def test_history_retrieval_returns_public_error_only(monkeypatch):
    secret_error = "provider response path=C:\\private\\history.json"
    monkeypatch.setattr(
        server,
        "get_loop",
        lambda _session_id: (_ for _ in ()).throw(RuntimeError(secret_error)),
    )

    with pytest.raises(HTTPException) as raised:
        server.get_history("session-test")

    assert raised.value.status_code == 500
    assert raised.value.detail == "History retrieval unavailable"
    assert secret_error not in raised.value.detail
