import os

import pytest

import tools.bash.scripts.bash as bash_module
import tools.terminal.scripts.terminal as terminal_module
from tools.bash.scripts.bash import BashTool
from tools.terminal.scripts.terminal import TerminalTool


def _read_command(path: str) -> str:
    return f'type "{path}"' if os.name == "nt" else f'cat "{path}"'


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_cls", [BashTool, TerminalTool])
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
    [(BashTool, bash_module), (TerminalTool, terminal_module)],
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
