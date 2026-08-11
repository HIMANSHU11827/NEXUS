import asyncio

import pytest

from neural.nerve_center import NexusNerveCenter
from orchestrators.v5.tools import V5ToolExecutor


class _Call:
    name = "grep"


class _Executor(V5ToolExecutor):
    def __init__(self, root, result=None, error=None):
        self.root_dir = str(root)
        self.result = result
        self.error = error

    async def _run_tool_impl(self, call):
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_v5_tool_success_records_feedback_off_event_loop(tmp_path):
    executor = _Executor(tmp_path, result="ok")

    assert await executor._run_tool(_Call()) == "ok"
    rows = NexusNerveCenter(str(tmp_path)).snapshot()["reinforcement"]
    assert rows[0]["tool_name"] == "grep"
    assert rows[0]["total_delta"] == 1


@pytest.mark.asyncio
async def test_v5_tool_failure_records_negative_feedback_and_preserves_error(tmp_path):
    executor = _Executor(tmp_path, error=RuntimeError("tool failed"))

    with pytest.raises(RuntimeError, match="tool failed"):
        await executor._run_tool(_Call())
    rows = NexusNerveCenter(str(tmp_path)).snapshot()["reinforcement"]
    assert rows[0]["total_delta"] == -1
