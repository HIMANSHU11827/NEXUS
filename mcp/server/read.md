# MCP Server

Runs NEXUS as an MCP stdio server so external clients can discover and call NEXUS tools.

**Version:** 1.0.0

## NEXUSMCPServer
- `NEXUSMCPServer(root_dir="")` — root_dir defaults to the current working directory
- Lazy ToolRegistry load: the registry is constructed on first tool listing, not at startup
- Protocol version `"2024-11-05"`; server name `nexus-ai`
- Schema conversion: tool schemas use `parameters` (or `params`) keys, normalized to MCP `inputSchema` (`type: object`, `properties`, with `required` derived from params flagged required)

## JSON-RPC Surface
- `initialize` — protocol version, tool capabilities, server info
- `tools/list` — all registered NEXUS tools as MCP tool definitions
- `tools/call` — invokes a tool via `tool.execute(**arguments)`; failures returned as `isError` content
- `notifications/initialized` — acknowledged, no response
- Unknown methods → error `-32601`; internal errors → `-32000`

## serve_stdio()
Synchronous stdin loop reading one JSON-RPC request per line via `read_bounded_line`, writing single-line JSON responses to stdout. Oversized messages → `-32600`; malformed JSON → `-32700`.

## Usage
```bash
python -m mcp.server
# or
python -c "from mcp.server import serve; serve()"
```

`main()` honors the `NEXUS_ROOT` environment variable as the root directory (falls back to the current working directory).
