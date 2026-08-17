import asyncio

from extensions.tools.built_in.nexus_tools.registry import _is_cancelled


def test_asyncio_event_is_a_supported_cancellation_token():
    event = asyncio.Event()
    assert _is_cancelled(event) is False
    event.set()
    assert _is_cancelled(event) is True
