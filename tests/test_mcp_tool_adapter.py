import pytest

from extensions.tools.built_in.nexus_tools.mcp_adapter import MCPToolAdapter
from extensions.tools.built_in.nexus_tools.result import STATUS_ERROR, STATUS_TIMEOUT


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


@pytest.mark.asyncio
async def test_mcp_standard_is_error_result_remains_failure():
    class ErrorClient:
        def call_tool(self, name, arguments):
            return {"content": [{"type": "text", "text": "boom"}], "isError": True}

    result = await MCPToolAdapter("broken", ErrorClient()).execute()

    assert result.status == STATUS_ERROR
    assert result.success is False
    assert result.error == "boom"
