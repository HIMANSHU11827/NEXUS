import json

import pytest

import tools.test_runner.scripts.test_runner as test_runner_module
from tools.creating.scripts.creating import CreatingTool
from tools.modifying.scripts.modifying import ModifyingTool
from tools.test_runner.scripts.test_runner import TestRunnerTool


def test_test_runner_auto_detects_node_test_script(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
    )

    assert TestRunnerTool()._detect_command(tmp_path, "auto", None) == "npm test"


@pytest.mark.asyncio
async def test_test_runner_forwards_timeout_and_reports_execution_metadata(tmp_path, monkeypatch):
    calls = []

    class FakeSandbox:
        last_exit_code = 0

        def __init__(self, root_dir):
            self.root_dir = root_dir

        async def stream_execute(self, command, workdir=None, timeout=None):
            calls.append((command, workdir, timeout))
            yield "passed"

    monkeypatch.setattr(test_runner_module, "SovereignSandbox", FakeSandbox)
    result = await TestRunnerTool(root_dir=str(tmp_path)).execute(
        command="npm run build", timeout=9
    )

    assert result.success is True
    assert calls == [("npm run build", str(tmp_path), 9)]
    assert result.metadata == {
        "exit_code": 0,
        "command": "npm run build",
        "workdir": str(tmp_path),
        "timeout": 9,
    }


@pytest.mark.asyncio
async def test_test_runner_fails_closed_when_exit_code_is_missing(tmp_path, monkeypatch):
    class MissingExitSandbox:
        last_exit_code = None

        def __init__(self, root_dir):
            self.root_dir = root_dir

        async def stream_execute(self, command, workdir=None, timeout=None):
            yield "completed output"

    monkeypatch.setattr(test_runner_module, "SovereignSandbox", MissingExitSandbox)
    result = await TestRunnerTool(root_dir=str(tmp_path)).execute(command="pytest -q")
    assert result.success is False


@pytest.mark.asyncio
async def test_file_tools_reject_sibling_prefix_traversal(tmp_path):
    workspace = tmp_path / "app"
    sibling = tmp_path / "app-copy"
    workspace.mkdir()
    sibling.mkdir()

    create_result = await CreatingTool(root_dir=str(workspace)).execute(
        path="../app-copy/escape.txt", content="blocked"
    )
    modify_result = await ModifyingTool(root_dir=str(workspace)).execute(
        path="../app-copy/escape.txt", old_string="x", new_string="y"
    )

    assert create_result.success is False
    assert modify_result.success is False
    assert not (sibling / "escape.txt").exists()
