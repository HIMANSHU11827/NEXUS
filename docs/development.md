# Development Guide

## Setup

### Prerequisites

- Python 3.13+
- Node 20+
- PowerShell 7+ (Windows)

### Python Environment

```powershell
cd C:\Users\himan\Desktop\NEXUS AI
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

Optional extras:

```powershell
pip install -e ".[dev]"      # dev tools (pytest)
pip install -e ".[browser]"  # browser automation (playwright)
pip install -e ".[vision]"   # vision (mediapipe, opencv)
pip install -e ".[voice]"    # voice (torch, transformers, whisper, TTS)
```

### GUI Setup

```powershell
cd apps/web
npm install
```

### TUI (Ink) Setup

```powershell
cd apps/tui
npm install
```

## Running

### Backend API (port 8000)

```powershell
python -m nexus --server
```

Options via environment variables:

- `NEXUS_API_HOST` (default: `127.0.0.1`)
- `NEXUS_API_PORT` (default: `8000`)
- `NEXUS_DASHBOARD_TOKEN` - Token for dashboard auth
- `NEXUS_API_BASE` - Base URL for OAuth redirects

### GUI (port 5173)

```powershell
python -m nexus --gui
```

Starts the GUI API backend on port 8000 and Vite on port 5173. For manual GUI development, run `python -m uvicorn apps.web.api:app --host 127.0.0.1 --port 8000` and `cd apps/web && npm run dev`.

### TUI

```powershell
python -m nexus
```

Default Ink TUI with GUI API backend. Use `python -m nexus --shell` for the legacy Rich shell.

### Full Stack

```powershell
python -m nexus
```

Boots `apps.web.api` as subprocess when needed, then starts the Ink TUI.

### TUI (Ink)

```powershell
cd apps/tui && npm run build && npm test
```

Development checks for the TypeScript Ink TUI.

### Gateway

```powershell
python -m nexus --gateway
```

### Voice

```powershell
pip install -e ".[voice]"
nexus-voice --warmup
```

## Configuration

Copy and edit:

```powershell
copy configure\.env.template configure\.env
```

Set at minimum:

```
DEEPSEEK_API_KEY=<set-in-local-env>
```

Key config files:

| File | Purpose |
|------|---------|
| `configure/.env` | API keys and secrets |
| `configure/provider.yml` | LLM provider definitions; use `${ENV_VAR}` references, not raw secrets |
| `configure/settings.yml` | Runtime settings |
| `configure/settings.yml` | Runtime settings and preferences persisted by API/TUI |
| `configure/mcp_servers.json` | MCP server definitions |

## Testing

### Python Tests

```powershell
python -m pytest tests/ -v
python -m pytest tests/test_shell_tui.py -v           # TUI tests
python -m pytest tests/test_mcp/ -v                   # MCP tests
python -m pytest tests/test_plugin_manager/ -v         # Plugin tests
python -m pytest tests/test_skill_curator/ -v          # Skill tests
python -m pytest tests/test_tool_registry/ -v          # Tool registry tests
python -m pytest tests/test_server/ -v                 # Server tests
python -m pytest tests/test_authentication/ -v          # Auth tests
python -m pytest tests/test_memory_manager/ -v          # Memory tests
python -m pytest tests/gui/ -v                          # GUI API tests
```

### GUI Tests

```powershell
cd apps/web
npm run build      # TypeScript compilation + Vite build
npm run lint       # ESLint
```

### TUI Tests

```powershell
cd apps/tui
npx tsc --noEmit   # TypeScript compilation check
```

## Project Structure

```
NEXUS AI/
  src/nexus/              # Boot loader, events, commands, runtime
  src/nexus/main_agent/   # V5 NexusLoop agent loop (core.py)
  src/nexus/runtime/kernel/  # Runtime singleton (20 lazy-loaded subsystems)
  src/nexus/capabilities/    # MoE router, NATE, HyperReasoningEngine, intent router
  src/nexus/common/       # Shared utilities
  src/nexus/context/      # Context persistence/compression
  src/nexus/lifecycle/    # Lifecycle hooks
  src/nexus/tasks/        # Task scheduler
  apps/api/               # FastAPI backend
  apps/web/               # React frontend + GUI API
  apps/tui/               # Ink TUI
  apps/voice/             # Voice mode
  models/providers/       # LLM provider implementations (core/api/local/auth)
  extensions/tools/built_in/  # Tool registry and implementations
  extensions/skills/built_in/ # Skill registry
  extensions/plugins/built_in/ # Plugin system
  extensions/mcp/core/    # MCP integration
  hive/                   # Multi-agent orchestration
  gateways/               # Multi-platform gateway
  memory/                 # Memory manager
  sandbox/                # Command sandbox
  security/               # Secret scanner
  security/policies/      # Safety policies
  security/permissions/   # Permission modes
  security/core/auth.py   # OAuth + token auth
  knowledge/rag/          # Retrieval engine
  knowledge/              # Knowledge store
  observability/telemetry/ # Telemetry database
  evaluation/             # Evaluation ledger
  maintenance/            # Roadmap maintenance
  evolution/              # Self-improvement modules
  configure/              # Configuration files
  scripts/                # Helper scripts
  deployment/             # Docker deployment
  tests/                  # Test suite
```

## Notes

- The kernel is lazily initialized on first access. Some subsystems referenced in `src/nexus/runtime/kernel/__init__.py` may not exist yet.
- The legacy `architect.py` module is removed — planning uses `todo.md` + the `planning` tool.
- Some tools have metadata (`.jsnol`) without handler scripts.
- Event system supports ~50 event types but not all have production emitters.
- No WebSocket yet - uses SSE + polling for real-time updates.
