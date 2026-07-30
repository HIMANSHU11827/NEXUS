# Server

FastAPI HTTP server (v2.1.0) — standalone API for external/OpenAI-compatible requests. Powers the React GUI backend.

**Version:** 2.1.0

## Entry
```powershell
python -m nexus --server
```
Serves on 127.0.0.1:8000 by default.

## API Endpoints
- `/api/health`, `/api/state`, `/api/version` — System health & status
- `/api/sessions/` — Session CRUD
- `/api/chat/` — Chat with SSE streaming + canonical events
- `/api/history`, `/api/runs/` — Session history & run context
- `/api/work-events/` — Cursor replay for persisted canonical work events
- `/v1/chat/completions`, `/v1/models` — OpenAI-compatible endpoints
- `/api/providers/` — Provider health & listing
- `/api/tools/`, `/api/skills/`, `/api/plugins/`, `/api/mcp/` — Registry queries
- `/api/agents/`, `/api/features/` — Agent & feature management
- `/api/files/list` — Workspace file browser
- `/api/permissions/`, `/api/permissions/decisions` — Permission mode & decisions
- `/api/mode`, `/api/model`, `/api/provider`, `/api/agent`, `/api/goal` — Runtime settings
- `/api/sandbox` — Sandbox tier management
- `/api/command` — Slash command execution
- `/api/run` — Bash command execution (restricted)
- `/api/tasks` — Task CRUD
- `/api/auth/*` — Authentication (token + OAuth)
- `/api/voice/*` — Voice mode control
- `/api/engine/*` — Engine management (compile, reload, train)
