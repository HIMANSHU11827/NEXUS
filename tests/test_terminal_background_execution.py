"""Regression coverage for terminal-owned foreground and detached commands.

The terminal stream normally owns the child process: consuming the stream waits
for completion, and cancelling it reaps the child.  A background launch is the
explicit exception.  Once the child has been detached, closing or cancelling
the stream must only release the observer and must not terminate the child.
"""

import asyncio
import os

import pytest


class _BlockingStdout:
    def __init__(self):
        self.read_started = asyncio.Event()
        self.release = asyncio.Event()

    async def read(self, _size):
        self.read_started.set()
        await self.release.wait()
        return b""


class _FakeProcess:
    pid = 4242

    def __init__(self):
        self.stdout = _BlockingStdout()
        self.returncode = None
        self.kill_calls = 0
        self.wait_calls = 0

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9

    async def wait(self):
        self.wait_calls += 1
        return self.returncode


@pytest.fixture
def fake_process(monkeypatch):
    from sandbox.sandbox_manager import SandboxTier

    process = _FakeProcess()

    async def create_subprocess_shell(*_args, **_kwargs):
        return process

    monkeypatch.setattr(
        "sandbox.sandbox_manager.asyncio.create_subprocess_shell",
        create_subprocess_shell,
    )
    return process, SandboxTier


@pytest.mark.asyncio
async def test_background_launch_returns_promptly_without_waiting_for_server(
    fake_process
):
    from sandbox.sandbox_manager import SovereignSandbox

    process, sandbox_tier = fake_process
    sandbox = SovereignSandbox(os.getcwd())
    sandbox.tier = sandbox_tier.NORMAL

    stream = sandbox.stream_execute("python -m http.server 8001", background=True)

    async def consume():
        return [chunk async for chunk in stream]

    output = await asyncio.wait_for(consume(), timeout=1)

    assert output
    assert "background" in "".join(output).lower()
    assert process.kill_calls == 0
    assert process.wait_calls == 0


@pytest.mark.asyncio
async def test_foreground_command_still_waits_for_process_completion(fake_process):
    from sandbox.sandbox_manager import SovereignSandbox

    process, sandbox_tier = fake_process
    sandbox = SovereignSandbox(os.getcwd())
    sandbox.tier = sandbox_tier.NORMAL

    async def consume():
        return [chunk async for chunk in sandbox.stream_execute("python -m pytest")]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(process.stdout.read_started.wait(), timeout=1)
    assert task.done() is False

    process.returncode = 0
    process.stdout.release.set()
    await asyncio.wait_for(task, timeout=1)

    assert process.wait_calls == 1
    assert process.kill_calls == 0


@pytest.mark.asyncio
async def test_closing_background_stream_does_not_kill_detached_process(fake_process):
    from sandbox.sandbox_manager import SovereignSandbox

    process, sandbox_tier = fake_process
    sandbox = SovereignSandbox(os.getcwd())
    sandbox.tier = sandbox_tier.NORMAL

    stream = sandbox.stream_execute("python -m http.server 8001", background=True)
    assert "BACKGROUND_STARTED" in await stream.__anext__()
    await stream.aclose()

    assert process.kill_calls == 0
    assert process.wait_calls == 0
