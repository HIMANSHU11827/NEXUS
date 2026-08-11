import pytest

from tools.nexus_tools.mcp_adapter import MCPToolAdapter
from tools.nexus_tools.result import STATUS_TIMEOUT


@pytest.mark.asyncio
async def test_mcp_client_timeout_preserves_retryable_timeout_status():
    class TimeoutClient:
        def call_tool(self, name, arguments):
            return {"error": f"Timeout calling tools/call: {name}"}

    tool = MCPToolAdapter(
        "slow_tool",
        TimeoutClient(),
        {"name": "slow_tool", "timeout": 1},
    )

    result = await tool.execute(value="x")

    assert result.status == STATUS_TIMEOUT
    assert result.error_info["type"] == "TimeoutError"
    assert result.error_info["retryable"] is True
