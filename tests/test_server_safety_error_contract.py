import pytest
from fastapi import HTTPException

import server


@pytest.mark.asyncio
async def test_safety_settings_does_not_reflect_store_exception(monkeypatch):
    secret_error = "sqlite path=C:\\private\\safety.db token=sk-live-safety"
    import safety.safety_store as safety_store

    monkeypatch.setattr(
        safety_store,
        "get_state",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(secret_error)),
    )

    with pytest.raises(HTTPException) as raised:
        await server.safety_settings()

    assert raised.value.status_code == 503
    assert raised.value.detail == "Safety store is unavailable"
    assert secret_error not in raised.value.detail
