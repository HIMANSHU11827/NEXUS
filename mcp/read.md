# MCP (Model Context Protocol)

MCP stdio client/server integration — bridges NEXUS with MCP-compatible tools and clients.

**Version:** 2.0.0

## Subdirectories
- `server/` — NEXUSMCPServer (v1.0.0): exposes NEXUS tools via MCP stdio protocol (JSON-RPC)
- `client/` — MCPClient (v1.0.0): subprocess-based MCP client with init handshake, tri-state health, lazy reconnect
- `tool/` — MCPTool (v2.0.0): wraps MCPClient + tool_def as a BaseTool-compatible adapter
- `catalog/` — MCPServerCatalog (v1.0.0): MCP server catalog with `${ENV_NAME}` reference support

## Runtime Wiring
- `tools/nexus_tools/mcp_adapter.py` — `MCPToolAdapter(BaseTool)`: runs remote MCP tools through the standard ToolRegistry `execute()`/`stream_execute()` pipeline
- `ToolRegistry.init_mcp_tools()` — reads `config/mcp_servers.json` at startup, starts each server, registers its tools under category `"mcp"` (source = server name), and wires `degraded_cb`/`recover_cb` so a dead server's tools are parked and restored on lazy reconnect

## HTTP Management API
- `GET /api/mcp` — list configured MCP servers
- `POST /api/mcp` — create or replace an MCP server (name + command required)
- `DELETE /api/mcp/{name}` — remove a server from both config stores

## Console Script
- `nexus-mcp` (pyproject.toml → `mcp.server:main`) — run NEXUS as an MCP stdio server

## Built-in Catalog Servers
- `nexus-ai` — all local NEXUS tools via MCP (current Python + `-m mcp.server`)
- `filesystem` — `npx @modelcontextprotocol/server-filesystem`
- `github` — `npx @modelcontextprotocol/server-github`, requires `GITHUB_TOKEN`

## Features
- Full MCP stdio protocol: initialize, tools/list, tools/call, notifications/initialized (protocol `2024-11-05`)
- Client liveness checks with auto-restart on death; dead servers hidden from tool registry
- Server lazy-loads ToolRegistry on first tool listing
- `security.py` — secret redaction, bounded line reader, workspace escape prevention, parameter bounds
- Legacy compat shims: `server.py` (code graph), `client.py` (9-line re-export)
