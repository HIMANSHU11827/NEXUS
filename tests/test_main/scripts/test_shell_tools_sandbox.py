import asyncio
import os

import pytest

import tools.terminal.scripts.terminal as terminal_module
from tools.terminal.scripts.terminal import TerminalTool


def _read_command(path: str) -> str:
    return f'type "{path}"' if os.name == "nt" else f'cat "{path}"'


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_cls", [TerminalTool])
async def test_shell_tools_use_normal_sandbox_for_outside_paths(tmp_path, monkeypatch, tool_cls):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "normal")

    result = await tool_cls(root_dir=str(workspace)).execute(_read_command(str(outside)))

    assert result.success is False
    assert "[SANDBOX_BLOCK]" in result.output


@pytest.mark.asyncio
async def test_normal_streaming_sandbox_does_not_expose_process_secrets(tmp_path, monkeypatch):
    from sandbox.sandbox_manager import SandboxTier, SovereignSandbox

    monkeypatch.setenv("NEXUS_FAKE_SECRET", "do-not-leak")
    sandbox = SovereignSandbox(str(tmp_path))
    sandbox.tier = SandboxTier.NORMAL
    command = "echo %NEXUS_FAKE_SECRET%" if os.name == "nt" else "printf \"$NEXUS_FAKE_SECRET\""

    output = "".join([chunk async for chunk in sandbox.stream_execute(command)])

    assert "do-not-leak" not in output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_cls", "module"),
    [(TerminalTool, terminal_module)],
)
async def test_shell_tools_forward_timeout_to_sandbox(tmp_path, monkeypatch, tool_cls, module):
    calls = []

    class FakeSandbox:
        last_exit_code = 0

        def __init__(self, root_dir):
            self.root_dir = root_dir

        async def stream_execute(self, command, workdir=None, timeout=None):
            calls.append({"command": command, "workdir": workdir, "timeout": timeout})
            yield "ok"

    monkeypatch.setattr(module, "SovereignSandbox", FakeSandbox)

    result = await tool_cls(root_dir=str(tmp_path)).execute("npm test", timeout=7)

    assert result.success is True
    assert calls == [{"command": "npm test", "workdir": str(tmp_path), "timeout": 7}]


@pytest.mark.asyncio
async def test_terminal_fails_closed_when_sandbox_does_not_report_exit_code(tmp_path, monkeypatch):
    class MissingExitSandbox:
        last_exit_code = None

        def __init__(self, root_dir):
            self.root_dir = root_dir

        async def stream_execute(self, command, workdir=None, timeout=None, shell=None):
            yield "completed output"

    monkeypatch.setattr(terminal_module, "SovereignSandbox", MissingExitSandbox)
    result = await TerminalTool(root_dir=str(tmp_path)).execute("npm test")
    assert result.success is False


@pytest.mark.asyncio
async def test_sandbox_reaps_child_when_stream_is_cancelled(tmp_path, monkeypatch):
    from sandbox.sandbox_manager import SandboxTier, SovereignSandbox

    class BlockingStdout:
        async def read(self, _size):
            await asyncio.Event().wait()

    class FakeProcess:
        def __init__(self):
            self.stdout = BlockingStdout()
            self.returncode = None
            self.killed = False

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_shell(*_args, **_kwargs):
        return process

    monkeypatch.setattr("sandbox.sandbox_manager.asyncio.create_subprocess_shell", fake_create_subprocess_shell)
    sandbox = SovereignSandbox(str(tmp_path))
    sandbox.tier = SandboxTier.NORMAL

    stream = sandbox.stream_execute("echo never-finishes")
    pending = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.02)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await stream.aclose()

    assert process.killed is True
    assert process.returncode == -9


@pytest.mark.asyncio
async def test_sandbox_launches_host_process_with_descendant_boundary(tmp_path, monkeypatch):
    from sandbox.sandbox_manager import SandboxTier, SovereignSandbox

    calls = []

    class ImmediateStdout:
        async def read(self, _size):
            return b""

    class FinishedProcess:
        pid = 4242
        returncode = 0
        stdout = ImmediateStdout()

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_shell(*args, **kwargs):
        calls.append((args, kwargs))
        return FinishedProcess()

    monkeypatch.setattr("sandbox.sandbox_manager.asyncio.create_subprocess_shell", fake_create_subprocess_shell)
    sandbox = SovereignSandbox(str(tmp_path))
    sandbox.tier = SandboxTier.NORMAL

    assert "".join([chunk async for chunk in sandbox.stream_execute("echo safe")]) == ""
    assert calls
    kwargs = calls[0][1]
    if os.name == "nt":
        assert kwargs["creationflags"]
    else:
        assert kwargs["start_new_session"] is True
