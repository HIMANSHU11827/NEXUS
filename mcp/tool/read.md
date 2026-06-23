# MCP Tool

Wraps an external MCP server tool as a NEXUS `BaseTool` so it can be used in the NEXUS tool ecosystem.

## Usage
```python
from mcp.tool import MCPTool
from mcp.client import MCPClient

client = MCPClient("npx", ["-y", "@modelcontextprotocol/server-filesystem", "."])
client.start()
for tdef in client.list_tools():
    tool = MCPTool(client, tdef)
    result = tool.call(path="/some/file.txt")
```
