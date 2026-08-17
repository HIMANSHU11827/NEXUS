import asyncio
import logging

from nexus.main_agent.tools import _TextToolCall, V5ToolExecutor


class _Granted:
    granted = True
    reason = "allowed"


class _Sandbox:
    last_exit_code = None

    def __init__(self):
        self.calls = []

    @staticmethod
    def should_background_command(command):
        return "http.server" in command

    async def stream_execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        yield "[BACKGROUND_STARTED]: Process detached successfully (id=42)."


class _Permissions:
    @staticmethod
    def check(*args, **kwargs):
        return _Granted()


class _Runtime:
    risk_scorer = None
    work_event_sink = None

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.permissions = _Permissions()


class _Executor(V5ToolExecutor):
    def __init__(self, sandbox):
        self.runtime = _Runtime(sandbox)
        self.kernel = None
        self.tool_registry = None
        self.work_event_sink = None
        self.root_dir = "."
        self.session_id = "test"
        self._current_turn_id = "turn"
        self.events = []
        self.logger = logging.getLogger("test.v5.terminal.background")

    async def _emit_tool_event(self, call, **kwargs):
        self.events.append((call.name, kwargs))

    async def _emit_tool_chunk(self, *args, **kwargs):
        return None

    async def _fire_post_tool_hooks(self, *args, **kwargs):
        return None

    async def _mark_tool_lifecycle(self, *args, **kwargs):
        return None


def test_v5_auto_detaches_common_preview_server():
    async def scenario():
        sandbox = _Sandbox()
        executor = _Executor(sandbox)
        result = await executor._run_tool_impl(
            _TextToolCall("terminal", {"command": "python -m http.server 8001"}, "c1")
        )
        assert "BACKGROUND_STARTED" in result
        assert sandbox.calls[0][1]["background"] is True
        assert executor.events[-1][1]["background"] is True

    asyncio.run(scenario())


def test_v5_explicit_foreground_keeps_server_attached():
    async def scenario():
        sandbox = _Sandbox()
        executor = _Executor(sandbox)
        # The explicit false is useful for commands that only happen to
        # contain a server-like token in an argument or test fixture name.
        sandbox.stream_execute = _foreground_stream.__get__(sandbox, _Sandbox)
        await executor._run_tool_impl(
            _TextToolCall(
                "terminal",
                {"command": "python -m http.server 8001", "background": False},
                "c2",
            )
        )
        assert "background" not in sandbox.calls[0][1]

    asyncio.run(scenario())


async def _foreground_stream(self, *args, **kwargs):
    self.calls.append((args, kwargs))
    self.last_exit_code = 0
    yield "foreground complete"
