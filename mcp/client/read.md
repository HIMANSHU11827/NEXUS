# MCP Client

Connects NEXUS as a client to external MCP servers over stdio JSON-RPC.

**Version:** 1.0.0

## Lifecycle & Health
- `health_probe()` returns tri-state health: `healthy` | `degraded` | `unavailable`
- Lazy reconnect: on transport failure the session is marked `degraded`, tools are parked via `degraded_cb`, and a bounded exponential-backoff reconnect (1s, 2s, 4s … capped at 60s) re-probes `tools/list` (`MAX_RECONNECT_ATTEMPTS = 3`); success restores tools via `recover_cb` and flips state to `healthy`
- After exhausting attempts the server is declared `unavailable`
- `degraded_cb` / `recover_cb` hooks are wired by `ToolRegistry.init_mcp_tools()` so a dead server's tools are hidden and later re-registered — no phantom calls to a dead transport

## Transport
- Subprocess (`shell=False`) with bounded, secret-redacted stdout + stderr reader threads (`read_bounded_line` + `redact_secret_text`)
- Thread-safe JSON-RPC calls; errors returned as `{"error": ..., "code": ...}`

## Usage
```python
from mcp.client import MCPClient

client = MCPClient("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/path"])
client.start()
tools = client.list_tools()
result = client.call_tool("read_file", {"path": "/path/file.txt"})
client.stop()
```

`start()` performs the initialize handshake and sends `notifications/initialized` before reporting success.
