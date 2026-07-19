"""Tests for MCPTool and MCP integration in the main loop."""
from unittest.mock import MagicMock

import pytest

from mcp.tool.scripts.tool import MCPTool, _run_mcp_call
from tools.nexus_tools.base_tool import ToolResult
from tools.nexus_tools.registry import ToolEntry, ToolRegistry


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.is_running.return_value = True
    client.call_tool.return_value = {
        "content": [{"type": "text", "text": "hello world"}],
        "isError": False,
    }
    return client


@pytest.fixture
def tool_def():
    return {
        "name": "test_mcp_tool",
        "description": "A test MCP tool",
        "inputSchema": {
            "type": "object",
            "properties": {
                "msg": {"type": "string", "description": "A message"},
            },
            "required": ["msg"],
        },
    }


class TestMCPTool:
    def test_init(self, mock_client, tool_def):
        tool = MCPTool(mock_client, tool_def)
        assert tool.name == "test_mcp_tool"
        assert tool.description == "A test MCP tool"
        assert tool.aliases == []

    def test_init_with_root_dir(self, mock_client, tool_def):
        tool = MCPTool(mock_client, tool_def, root_dir="/tmp")
        assert tool.root_dir == "/tmp"

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_client, tool_def):
        mock_client.is_running.return_value = True
        tool = MCPTool(mock_client, tool_def)
        result = await tool.execute(msg="hello")
        assert isinstance(result, ToolResult)
        assert result.output == "hello world"
        assert result.error == ""
        mock_client.call_tool.assert_called_once_with("test_mcp_tool", {"msg": "hello"})

    @pytest.mark.asyncio
    async def test_execute_error_flag(self, mock_client, tool_def):
        mock_client.is_running.return_value = True
        mock_client.call_tool.return_value = {
            "content": [{"type": "text", "text": "something broke"}],
            "isError": True,
        }
        tool = MCPTool(mock_client, tool_def)
        result = await tool.execute(msg="fail")
        assert result.error == "something broke"
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_execute_no_result(self, mock_client, tool_def):
        mock_client.is_running.return_value = True
        mock_client.call_tool.return_value = None
        tool = MCPTool(mock_client, tool_def)
        result = await tool.execute(msg="noop")
        assert result.output == ""
        assert "returned no result" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_exception(self, mock_client, tool_def):
        mock_client.is_running.return_value = True
        mock_client.call_tool.side_effect = RuntimeError("boom")
        tool = MCPTool(mock_client, tool_def)
        result = await tool.execute(msg="crash")
        assert result.output == ""
        assert "boom" in (result.error or "")

    def test_get_schema(self, mock_client, tool_def):
        tool = MCPTool(mock_client, tool_def)
        schema = tool.get_schema()
        assert schema["name"] == "test_mcp_tool"
        assert schema["description"] == "A test MCP tool"
        assert schema["parameters"] == tool_def["inputSchema"]

    def test_is_read_only_get(self, mock_client, tool_def):
        read_tool_def = {**tool_def, "name": "get_file"}
        tool = MCPTool(mock_client, read_tool_def)
        assert tool.is_read_only() is True

    def test_is_read_only_list(self, mock_client, tool_def):
        list_tool_def = {**tool_def, "name": "list_files"}
        tool = MCPTool(mock_client, list_tool_def)
        assert tool.is_read_only() is True

    def test_is_read_only_search(self, mock_client, tool_def):
        search_tool_def = {**tool_def, "name": "search_code"}
        tool = MCPTool(mock_client, search_tool_def)
        assert tool.is_read_only() is True

    def test_is_read_only_write(self, mock_client, tool_def):
        write_tool_def = {**tool_def, "name": "write_file"}
        tool = MCPTool(mock_client, write_tool_def)
        assert tool.is_read_only() is False

    def test_is_read_only_execute(self, mock_client, tool_def):
        exec_tool_def = {**tool_def, "name": "bash_exec"}
        tool = MCPTool(mock_client, exec_tool_def)
        assert tool.is_read_only() is False

    def test_is_read_only_screenshot(self, mock_client, tool_def):
        ss_tool_def = {**tool_def, "name": "take_screenshot"}
        tool = MCPTool(mock_client, ss_tool_def)
        assert tool.is_read_only() is True

    @pytest.mark.asyncio
    async def test_multiple_text_blocks(self, mock_client, tool_def):
        mock_client.is_running.return_value = True
        mock_client.call_tool.return_value = {
            "content": [
                {"type": "text", "text": "line 1"},
                {"type": "text", "text": "line 2"},
                {"type": "image", "text": ""},
            ],
            "isError": False,
        }
        tool = MCPTool(mock_client, tool_def)
        result = await tool.execute(msg="multi")
        assert result.output == "line 1\nline 2"

    @pytest.mark.asyncio
    async def test_execute_unavailable_client(self, mock_client, tool_def):
        mock_client.is_running.return_value = False
        tool = MCPTool(mock_client, tool_def)

        result = await tool.execute(msg="hello")

        assert result.output == ""
        assert "not running" in result.error
        mock_client.call_tool.assert_not_called()

    def test_is_available_uses_client_liveness(self, mock_client, tool_def):
        mock_client.is_running.return_value = False
        tool = MCPTool(mock_client, tool_def)

        assert tool.is_available() is False

    def test_dead_client_is_hidden_from_available_registry(self, mock_client, tool_def):
        mock_client.is_running.return_value = False
        tool = MCPTool(mock_client, tool_def)
        registry = object.__new__(ToolRegistry)
        registry.root = ""
        registry._tools = {
            "test_mcp_tool": ToolEntry(
                "test_mcp_tool",
                tool_def,
                tool,
                check_fn=tool.is_available,
            )
        }

        assert registry.list_tools() == {}
        unavailable = registry.list_tools(include_unavailable=True)["test_mcp_tool"]
        assert unavailable["available"] is False
        assert unavailable["availability_reason"] == "check_failed"


@pytest.mark.asyncio
async def test_run_mcp_call():
    """Test the _run_mcp_call helper uses asyncio.to_thread."""
    client = MagicMock()
    client.call_tool.return_value = {"content": [{"type": "text", "text": "ok"}]}
    result = await _run_mcp_call(client, "some_tool", {"key": "val"})
    assert result["content"][0]["text"] == "ok"
