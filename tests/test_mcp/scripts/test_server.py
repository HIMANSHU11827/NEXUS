import pytest

from tools.nexus_tools.base_tool import ToolResult


@pytest.mark.asyncio
async def test_tools_call_awaits_async_tool():
    from mcp.server.scripts.server import NEXUSMCPServer

    class FakeInstance:
        async def execute(self, msg):
            return ToolResult(output=f"ok:{msg}")

    class FakeRegistry:
        def get(self, name):
            return type("Entry", (), {"instance": FakeInstance(), "schema": {"name": name}})()

    server = NEXUSMCPServer("root")
    server._tool_registry = FakeRegistry()

    response = await server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "demo", "arguments": {"msg": "hello"}},
    })

    assert response["result"]["content"][0]["text"] == "ok:hello"
    assert response["result"]["isError"] is False


def test_tools_list_converts_jsnol_params_to_input_schema():
    from mcp.server.scripts.server import NEXUSMCPServer

    class FakeRegistry:
        def list_tools(self):
            return {"demo": {}}

        def get(self, name):
            return type("Entry", (), {
                "schema": {
                    "name": name,
                    "description": "demo tool",
                    "params": {"path": {"type": "string", "required": True}},
                },
            })()

    server = NEXUSMCPServer("root")
    server._tool_registry = FakeRegistry()

    tool = server.list_tools()[0]

    assert tool["inputSchema"]["properties"]["path"]["type"] == "string"
    assert tool["inputSchema"]["required"] == ["path"]
