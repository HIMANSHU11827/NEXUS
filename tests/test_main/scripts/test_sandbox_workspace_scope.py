import os

import pytest

from sandbox.sandbox_manager import SandboxTier, SovereignSandbox


def _read_command(path: str) -> str:
    return f'type "{path}"' if os.name == "nt" else f'cat "{path}"'


def test_simple_sandbox_allows_workspace_command(tmp_path):
    target = tmp_path / "inside.txt"
    target.write_text("inside ok", encoding="utf-8")
    sandbox = SovereignSandbox(str(tmp_path))
    sandbox.tier = SandboxTier.NORMAL

    output = sandbox.execute(_read_command("inside.txt"))

    assert "inside ok" in output


def test_invalid_sandbox_tier_falls_back_to_normal(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_SANDBOX_TIER", "definitely-not-a-tier")

    sandbox = SovereignSandbox(str(tmp_path))

    assert sandbox.tier == SandboxTier.NORMAL


def test_simple_sandbox_blocks_workdir_outside_workspace(tmp_path):
    sandbox = SovereignSandbox(str(tmp_path / "workspace"))
    sandbox.tier = SandboxTier.NORMAL

    output = sandbox.execute("dir" if os.name == "nt" else "ls", workdir=str(tmp_path))

    assert output.startswith("[SANDBOX_BLOCK]")
    assert "workdir is outside workspace" in output


def test_simple_sandbox_blocks_parent_traversal(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    sandbox = SovereignSandbox(str(workspace))
    sandbox.tier = SandboxTier.NORMAL

    output = sandbox.execute(_read_command("..\\outside.txt" if os.name == "nt" else "../outside.txt"))

    assert output.startswith("[SANDBOX_BLOCK]")
    assert "path is outside workspace" in output


def test_simple_sandbox_blocks_absolute_outside_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    sandbox = SovereignSandbox(str(workspace))
    sandbox.tier = SandboxTier.NORMAL

    output = sandbox.execute(_read_command(str(outside)))

    assert output.startswith("[SANDBOX_BLOCK]")
    assert "path is outside workspace" in output


@pytest.mark.asyncio
async def test_simple_sandbox_stream_blocks_absolute_outside_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    sandbox = SovereignSandbox(str(workspace))
    sandbox.tier = SandboxTier.NORMAL

    chunks = [chunk async for chunk in sandbox.stream_execute(_read_command(str(outside)))]

    assert "".join(chunks).startswith("[SANDBOX_BLOCK]")


@pytest.mark.asyncio
async def test_docker_streaming_sandbox_rejects_outside_workdir_before_subprocess(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    sandbox = SovereignSandbox(str(workspace))
    sandbox.tier = SandboxTier.DOCKER

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("docker subprocess should not be started")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fail_if_called)

    output = "".join([chunk async for chunk in sandbox.stream_execute("echo hi", str(outside))])

    assert output.startswith("[SANDBOX_BLOCK]")
    assert "workdir is outside workspace" in output
