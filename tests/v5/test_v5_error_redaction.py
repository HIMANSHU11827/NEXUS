import pytest

from nexus.main_agent.core import NexusLoopV5
from nexus.main_agent.parallel import V5ParallelExecutor


class _Call:
    name = "tool"


def test_parallel_exception_normalization_redacts_and_bounds_secrets():
    success, output, error = V5ParallelExecutor._normalise_result(
        RuntimeError("authorization token=sk-test-secret-value")
    )

    assert success is False
    assert output == ""
    assert "sk-test-secret-value" not in error
    assert "REDACTED" in error


@pytest.mark.asyncio
async def test_core_tool_observation_redacts_exception_text():
    class Host:
        async def _run_tool(self, call):
            raise RuntimeError("provider token=sk-test-secret-value")

    results = await NexusLoopV5._execute_tools(Host(), [_Call()])

    assert len(results) == 1
    assert "sk-test-secret-value" not in results[0]
    assert "REDACTED" in results[0]
