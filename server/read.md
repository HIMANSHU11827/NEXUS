# Server

FastAPI HTTP server — serves the GUI API and handles external requests.

**Version:** 1.0.0

## Entry
`powershell
python -m server
`
Serves on 127.0.0.1:8000 by default.

## API Endpoints
- /api/sessions/ — Session management
- /api/chat/ — Chat and streaming
- /api/providers/ — Provider health
- /api/tools/ — Tool execution
- /api/graph/ — Unified graph queries
