import asyncio
import logging

import pytest

from nexus.main_agent.tools import _TextToolCall, V5ToolExecutor


class _Runtime:
    permissions = None
    class _Sandbox:
        async def stream_execute(self, *args, **kwargs):
            if False:
                yield ""

    sandbox = _Sandbox()
    risk_scorer = None
    work_event_sink = None


class _Executor(V5ToolExecutor):
    def __init__(self):
        self.runtime = _Runtime()
        self.kernel = None
        self.tool_registry = None
        self.work_event_sink = None
        self.root_dir = "."
        self.session_id = "test"
        self._current_turn_id = "turn"
        self.events = []
        self.logger = logging.getLogger("test.v5.permissions")

    async def _emit_tool_event(self, call, **kwargs):
        self.events.append((call.name, kwargs))


def test_registry_tool_audit_denies_when_permission_system_missing():
    async def scenario():
        executor = _Executor()
        call = _TextToolCall("reading", {"path": "notes.txt"}, "c1")
        assert await executor._audit_tool_call(call) is False
        assert call._denied_reason == "permission system unavailable"

    asyncio.run(scenario())


def test_command_execution_denies_when_permission_system_missing():
    async def scenario():
        executor = _Executor()
        call = _TextToolCall("terminal", {"command": "echo unsafe"}, "c2")
        with pytest.raises(RuntimeError, match="Permission system unavailable"):
            await executor._run_tool(call)
        assert executor.events[-1][1]["status"] == "blocked"

    asyncio.run(scenario())


def test_command_sandbox_marker_is_a_failed_tool_result():
    class Granted:
        granted = True
        reason = "allowed"

    class FailingSandbox:
        last_exit_code = None

        async def stream_execute(self, *args, **kwargs):
            yield "[SANDBOX_BLOCK]: workspace-only path rejection"

    async def scenario():
        executor = _Executor()
        executor.runtime.permissions = type("Permissions", (), {"check": lambda *args, **kwargs: Granted()})()
        executor.runtime.sandbox = FailingSandbox()
        executor._emit_tool_chunk = lambda *args, **kwargs: asyncio.sleep(0)
        executor._fire_post_tool_hooks = lambda *args, **kwargs: asyncio.sleep(0)
        executor._mark_tool_lifecycle = lambda *args, **kwargs: asyncio.sleep(0)
        call = _TextToolCall("terminal", {"command": "echo test"}, "c3")
        with pytest.raises(RuntimeError, match="SANDBOX_BLOCK"):
            await executor._run_tool(call)
        assert executor.events[-1][1]["status"] == "error"

    asyncio.run(scenario())
