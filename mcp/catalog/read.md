# MCP Server Catalog

Discovers, registers, and manages MCP servers that extend NEXUS capabilities.

## Usage
```python
from mcp.catalog import MCPServerCatalog, MCPServerDef

cat = MCPServerCatalog()
for srv in cat.builtin_servers():
    cat.register(srv)
print(cat.list_servers())
```
