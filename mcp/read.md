# MCP (Model Context Protocol)

MCP stdio client/server integration — bridges NEXUS with MCP-compatible tools and clients.

**Version:** 2.0.0

## Subdirectories
- `server/` — NEXUSMCPServer: exposes NEXUS tools via MCP stdio protocol (JSON-RPC)
- `client/` — MCPClient: subprocess-based MCP client with init handshake, liveness checks, thread-safe JSON-RPC calls
- `tool/` — MCPTool: wraps MCPClient + tool_def as BaseTool-compatible adapter (v2.0.0)
- `catalog/` — MCP tool catalog with ${ENV_NAME} reference support

## Features
- Full MCP stdio protocol: initialize, list_tools, call_tool, notifications
- Client liveness checks with auto-restart on death; dead servers hidden from tool registry
- Server lazy-loads ToolRegistry on first tool listing
- `security.py` — secret redaction, bounded line reader, workspace escape prevention, parameter bounds
- Legacy compat shims: `server.py` (code graph), `client.py` (9-line re-export)
