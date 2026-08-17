"""Integration tests for the dedicated Gateway application (apps/gateway).

These exercise the application layer (lifecycle, command-bus adapter, health)
without requiring live gateway credentials — discovery degrades gracefully.
"""

import asyncio

import pytest

from apps.gateway.nexus_gateway_app.application import GatewayApplication
from apps.gateway.nexus_gateway_app.gateway_runner import CommandBusGatewayRunner
from apps.gateway.nexus_gateway_app.health import aggregate_health
from apps.gateway.nexus_gateway_app.lifecycle import GatewayAppState


@pytest.mark.asyncio
async def test_gateway_app_degrades_without_credentials():
    app = GatewayApplication()
    await app.start()
    # No platform env vars -> degraded, never crashes.
    assert app.state == GatewayAppState.DEGRADED
    assert app.enabled_platforms == []
    await app.stop()
    assert app.state == GatewayAppState.STOPPED


@pytest.mark.asyncio
async def test_gateway_app_health_without_supervisor():
    health = aggregate_health(None)
    assert health["__overall__"]["status"] == "no_gateways"


@pytest.mark.asyncio
async def test_command_runner_falls_back_when_no_bus_command():
    # No 'gateway.message' command is registered, so the adapter must NOT
    # invent one — it reports the bus is unused and falls back gracefully.
    runner = CommandBusGatewayRunner(engine_runner=None)
    assert runner.uses_command_bus is False

    class _Ev:
        platform = "telegram"
        text = "hi"
        chat_id = "c1"

    result = await runner.handle_message(_Ev())
    assert result is None  # graceful no-op, not an exception


def test_gateway_app_importable():
    import importlib

    for mod in (
        "apps.gateway.nexus_gateway_app",
        "apps.gateway.nexus_gateway_app.main",
        "apps.gateway.nexus_gateway_app.application",
        "apps.gateway.nexus_gateway_app.bootstrap",
        "apps.gateway.nexus_gateway_app.gateway_supervisor",
        "apps.gateway.nexus_gateway_app.gateway_runner",
        "apps.gateway.nexus_gateway_app.connection_manager",
        "apps.gateway.nexus_gateway_app.health",
        "apps.gateway.nexus_gateway_app.shutdown",
        "apps.gateway.nexus_gateway_app.lifecycle",
    ):
        importlib.import_module(mod)
