# MCP Client

Connects NEXUS as a client to external MCP servers over stdio JSON-RPC.

## Usage
```python
from mcp.client import MCPClient

client = MCPClient("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/path"])
client.start()
tools = client.list_tools()
result = client.call_tool("read_file", {"path": "/path/file.txt"})
client.stop()
```
