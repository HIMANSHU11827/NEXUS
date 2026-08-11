import pytest

from nexus.commands import CommandContext, get_registry
from server import list_commands


def test_command_catalog_is_projected_from_central_registry():
    payload = list_commands()
    rows = payload["commands"]
    registry = get_registry()

    assert len(rows) == len(registry.list())
    assert [row["name"] for row in rows] == [f"/{command.name}" for command in registry.list()]
    assert all(row["name"].startswith("/") for row in rows)
    assert all(alias.startswith("/") for row in rows for alias in row["aliases"])

    status = next(row for row in rows if row["name"] == "/status")
    command = registry.get("status")
    assert command is not None
    assert status["description"] == command.description
    assert status["category"] == command.category


@pytest.mark.asyncio
async def test_client_control_commands_are_registered_and_aliases_execute():
    registry = get_registry()

    assert registry.get("commands") is registry.get("help")
    assert registry.get("cancel") is registry.get("stop")
    stop = await registry.execute("cancel", CommandContext())
    retry = await registry.execute("retry", CommandContext())

    assert stop.data == {"client_action": "stop"}
    assert retry.data == {"client_action": "retry"}
