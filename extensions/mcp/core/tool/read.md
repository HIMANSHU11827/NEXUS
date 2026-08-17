# MCP Tool

Wraps an external MCP server tool as a NEXUS `BaseTool` so it can be used in the NEXUS tool ecosystem.

**Version:** 2.0.0

`MCPTool` extends `BaseTool` — it has no `call()` method; invocation goes through the async `execute(**kwargs)` interface.

## Methods
- `execute(**kwargs)` — async, returns `ToolResult`; the MCP call is offloaded off the event loop via `asyncio.to_thread(client.call_tool, ...)`
- `is_available()` — True while the client's subprocess is running
- `is_read_only()` — heuristic: returns True when the tool name contains `get`, `list`, `search`, `read`, `status`, `take_screenshot`, or `take_snapshot`
- `get_schema()` — `{"name", "description", "parameters": inputSchema}`

## Usage
```python
import asyncio
from mcp.tool import MCPTool
from mcp.client import MCPClient

async def main():
    client = MCPClient("npx", ["-y", "@modelcontextprotocol/server-filesystem", "."])
    client.start()
    for tdef in client.list_tools():
        tool = MCPTool(client, tdef)
        result = await tool.execute(path="/some/file.txt")
        print(result.output)
    client.stop()

asyncio.run(main())
```
