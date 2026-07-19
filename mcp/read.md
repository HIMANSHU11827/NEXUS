# MCP (Model Context Protocol)

MCP stdio server for code graph — bridges NEXUS with Claude/Cursor/Windsurf-style clients.

**Version:** 1.0.0

## Subdirectories
- server/ — MCP stdio server
- client/ — MCP client
- tool/ — MCP tool integration
- catalog/ — MCP tool catalog

## Features
- Code-graph-backed NEXUS.md generation
- Tool exposure via MCP protocol
- Client startup validates initialize; failed initialization terminates the child process instead of leaving an ambiguous running server.
- Client calls check subprocess liveness before reuse; exited MCP servers are cleared and restarted instead of being treated as healthy.
- MCP-backed tools report client liveness to the tool registry, so dead servers are hidden from normal tool availability and shown as unavailable in diagnostics.
- Catalog env values support `${ENV_NAME}` references. Secret-looking literal env values are rejected at registration and resolved only when starting the server process.
