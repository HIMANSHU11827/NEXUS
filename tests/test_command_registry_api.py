import pytest

from nexus.commands import CommandContext, get_registry
from apps.api import list_commands


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
    assert all(row["execution"] in {"shared", "client"} for row in rows)


def test_catalog_contains_the_interactive_commands_that_clients_dispatch():
    registry = get_registry()
    expected = {
        "usage", "health", "pwd", "where", "files", "ls", "tree", "cat",
        "doctor", "build", "provider", "permissions", "sandbox", "voice",
        "open-gui", "ide", "scheduler", "goal", "todo", "batch", "fork",
        "multi-agent", "security-review", "deep-research", "git", "diff",
        "branch", "log", "theme", "keybindings", "setup-bedrock", "setup-vertex",
    }
    assert expected.issubset({command.name for command in registry.list()})
    assert len(registry.list()) >= 100

    client_entry = registry.get("usage")
    assert client_entry is not None
    assert client_entry.execution == "client"


@pytest.mark.asyncio
async def test_client_control_commands_are_registered_and_aliases_execute():
    registry = get_registry()

    assert registry.get("commands") is registry.get("help")
    assert registry.get("cancel") is registry.get("stop")
    stop = await registry.execute("cancel", CommandContext())
    retry = await registry.execute("retry", CommandContext())

    assert stop.data == {"client_action": "stop"}
    assert retry.data == {"client_action": "retry"}


@pytest.mark.asyncio
async def test_client_catalog_entries_keep_the_requested_command_identity():
    registry = get_registry()
    result = await registry.execute(
        "usage",
        CommandContext(extra={"command": "/usage", "args": "/usage"}),
    )
    assert result.success
    assert "/usage" in result.output
    assert result.data == {"client_action": "interactive", "command": "/usage"}
    assert registry.get("reload-plugins") is registry.get("reload")


@pytest.mark.asyncio
async def test_shared_runtime_commands_change_real_runtime_state():
    registry = get_registry()
    runtime = {
        "mode": "auto",
        "sandbox_tier": "normal",
        "provider": "",
        "model": "",
        "effort": "medium",
        "thinking": True,
        "permission_allowlist": [],
    }
    persisted = []
    applied = []
    synced = []

    async def persist():
        persisted.append(dict(runtime))

    def apply():
        applied.append(dict(runtime))

    async def run(raw: str):
        command = raw.split()[0].lstrip("/")
        return await registry.execute(
            command,
            CommandContext(
                mode=runtime["mode"],
                provider=runtime["provider"],
                model=runtime["model"],
                thinking=runtime["thinking"],
                extra={
                    "args": raw,
                    "runtime_settings": runtime,
                    "persist_runtime": persist,
                    "apply_runtime": apply,
                    "sync_permission_mode": lambda value: synced.append(("permission", value)),
                    "sync_sandbox_tier": lambda value: synced.append(("sandbox", value)),
                },
            ),
        )

    assert (await run("/mode ask")).success
    assert (await run("/permissions add terminal")).success
    assert (await run("/sandbox docker")).success
    assert (await run("/provider deepseek")).success
    assert (await run("/model set deepseek deepseek-chat")).success
    assert (await run("/effort extra_high")).success
    assert (await run("/thinking")).success

    assert runtime["mode"] == "ask"
    assert runtime["permission_allowlist"] == ["terminal"]
    assert runtime["sandbox_tier"] == "docker"
    assert runtime["provider"] == "deepseek"
    assert runtime["model"] == "deepseek-chat"
    assert runtime["effort"] == "xhigh"
    assert runtime["thinking"] is False
    assert persisted
    assert applied
    assert ("permission", "ask") in synced
    assert ("sandbox", "docker") in synced


@pytest.mark.asyncio
async def test_shared_session_commands_use_attached_callbacks():
    registry = get_registry()
    calls = []

    def new_session():
        calls.append("new")
        return {"id": "session_new"}

    def load_session(session_id):
        calls.append(("load", session_id))
        return {"id": session_id}

    def list_sessions():
        return [{"id": "session_a", "title": "A"}]

    def load_history(session_id):
        return [{"role": "user", "content": f"history for {session_id}"}]

    async def run(raw: str):
        return await registry.execute(
            raw.split()[0].lstrip("/"),
            CommandContext(
                session_id="session_current",
                extra={
                    "args": raw,
                    "new_session": new_session,
                    "load_session": load_session,
                    "list_sessions": list_sessions,
                    "load_history": load_history,
                },
            ),
        )

    assert (await run("/new")).data == {"session_id": "session_new"}
    assert (await run("/session session_a")).data == {"session_id": "session_a"}
    assert "session_a: A" in (await run("/sessions")).output
    assert "history for session_current" in (await run("/history")).output
    assert calls == ["new", ("load", "session_a")]
