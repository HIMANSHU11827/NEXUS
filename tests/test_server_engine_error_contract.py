import pytest
from fastapi import HTTPException

import apps.api


def test_engine_status_returns_public_error_only(monkeypatch):
    import nexus.common.engine_manager as engine_manager

    secret_error = "local model path=C:\\private\\model.gguf token=sk-live-engine"
    monkeypatch.setattr(
        engine_manager,
        "get_engine_status",
        lambda: (_ for _ in ()).throw(RuntimeError(secret_error)),
    )

    with pytest.raises(HTTPException) as raised:
        server.engine_status()

    assert raised.value.status_code == 500
    assert raised.value.detail == "Engine status unavailable"
    assert secret_error not in raised.value.detail
