import json

import pytest
from fastapi import Request

from server import global_exception_handler


@pytest.mark.asyncio
async def test_global_exception_handler_does_not_reflect_exception_details():
    request = Request({"type": "http", "method": "GET", "path": "/"})

    response = await global_exception_handler(
        request,
        RuntimeError("token=super-secret path=C:\\private\\config.json"),
    )

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "Internal server error"}
