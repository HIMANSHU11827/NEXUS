# MCP Server Catalog

Discovers, registers, and manages MCP servers that extend NEXUS capabilities.

**Version:** 1.0.0

## Environment References
- `env` values may be written verbatim as `${ENV_NAME}` references; they are stored as-is in config and resolved from the process environment only when the server starts (`start_server()`)
- Literal secrets in config are rejected: env keys matching `api_key`/`token`/`secret`/`password`/`credential` or values matching known secret patterns raise a `ValueError` — store them in the process environment instead

## Persistence
- Servers persist to `mcp_config.json` (schema version `"2.0"`) in the nexus home directory

## Built-in Servers
- `nexus-ai` — all local NEXUS tools via `sys.executable -m mcp.server` (category `development`)
- `filesystem` — `npx @modelcontextprotocol/server-filesystem` with the current working directory
- `github` — `npx @modelcontextprotocol/server-github`, requires `GITHUB_TOKEN` via `requires_env`

## Methods
- `register(server)` — validate env, add, persist
- `unregister(name)` — remove a server from the catalog
- `get_enabled_servers()` — enabled servers whose `requires_env` vars are all present (disabled or env-starved servers skipped)
- `start_server(name)` — spawn the server process with resolved env references
- `list_servers()` — status summary including `ready` and `missing_env`

## Usage
```python
from mcp.catalog import MCPServerCatalog, MCPServerDef

cat = MCPServerCatalog()
for srv in cat.builtin_servers():
    cat.register(srv)
print(cat.list_servers())
```
