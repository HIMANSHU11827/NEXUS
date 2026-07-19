# Server

FastAPI HTTP server — standalone API for external/OpenAI-compatible requests. The GUI and default Ink TUI use `gui.api`.

**Version:** 1.0.0

## Entry
```powershell
python -m nexus --server
```
Serves on 127.0.0.1:8000 by default.

## API Endpoints
- /api/sessions/ — Session management
- /api/chat/ — Chat and streaming
- /api/runs/ — Durable run-context inspection with public work-event summaries
- /api/work-events/ — Cursor replay for persisted public canonical work events
- /api/providers/ — Provider health
- /api/tools/ — Tool execution
- /api/permissions/ — Permission mode, allowlist, and recent decisions
- /api/permissions/decisions — Scrubbed permission decision log
- /api/graph/ — Unified graph queries
