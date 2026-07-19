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
cd gui
npm install
```

### TUI (Ink) Setup

```powershell
cd tui
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

Starts the GUI API backend on port 8000 and Vite on port 5173. For manual GUI development, run `python -m uvicorn gui.api:app --host 127.0.0.1 --port 8000` and `cd gui && npm run dev`.

### TUI

```powershell
python -m nexus
```

Default Ink TUI with GUI API backend. Use `python -m nexus --shell` for the legacy Rich shell.

### Full Stack

```powershell
python -m nexus
```

Boots `gui.api` as subprocess when needed, then starts the Ink TUI.

### TUI (Ink)

```powershell
cd tui && npm run build && npm test
```

Development checks for the TypeScript Ink TUI.

### Gateway

```powershell
python -m nexus --gateway
```

### Voice

```powershell
pip install -e ".[voice]"
python -m voice_chat --warmup
```

## Configuration

Copy and edit:

```powershell
copy config\.env.template config\.env
```

Set at minimum:

```
DEEPSEEK_API_KEY=<set-in-local-env>
```

Key config files:

| File | Purpose |
|------|---------|
| `config/.env` | API keys and secrets |
| `config/provider.yml` | LLM provider definitions; use `${ENV_VAR}` references, not raw secrets |
| `config/settings.yml` | Runtime settings |
| `config/nexus_config.yaml` | Runtime preferences persisted by API/TUI |
| `config/mcp_servers.json` | MCP server definitions |

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
cd gui
npm run build      # TypeScript compilation + Vite build
npm run lint       # ESLint
```

### TUI Tests

```powershell
cd tui
npx tsc --noEmit   # TypeScript compilation check
```

## Project Structure

```
NEXUS AI/
  nexus/              # Boot loader, events
  server/             # FastAPI backend
  orchestrators/      # Agent loop, workflow engine
  providers/          # LLM provider implementations
  tools/              # Tool registry and implementations
  gui/                # React frontend + GUI API
  shell/              # Legacy Rich shell
  mcp/                # MCP integration
  plugins/            # Plugin system
  prompts/            # Prompt templates
  skills/             # Skill registry
  memory/             # Memory manager
  sandbox/            # Command sandbox
  kernel/             # Runtime singleton
  voice/              # Voice mode
  gateway/            # Multi-platform gateway
  config/             # Configuration files
  evolution/          # Self-improvement modules
  external/           # External integrations
  reasoning/          # Hyper-reasoning engine
  rag/                # Retrieval engine
  knowledge/          # Knowledge store
  context/            # Context compression
  safety/             # Safety policies
  security/           # Secret scanner
  permissions/        # Permission modes
  lifecycle/          # Lifecycle hooks
  tasks/              # Task scheduler
  telemetry/          # Telemetry database
  hive/               # Multi-agent orchestration
  router/             # Intent router
  intelligence/       # Local brain, NATE
  authentication/     # OAuth + token auth
  cognition/          # Cognitive models
  commands/           # CLI command definitions
  neural/             # Nerve center, trainer
  optimization/       # Performance optimization
  hardware/           # Hardware manager
  indexer/            # Indexer
  integrations/       # Third-party integrations
  utils/              # Utilities
  scripts/            # Helper scripts
  deploy/             # Docker deployment
  tests/              # Test suite
```

## Notes

- The kernel is lazily initialized on first access. Some subsystems referenced in `kernel/__init__.py` may not exist yet.
- `orchestrators/architect.py` is legacy code with stub imports.
- Some tools have metadata (`.jsnol`) without handler scripts.
- Event system supports ~50 event types but not all have production emitters.
- No WebSocket yet - uses SSE + polling for real-time updates.
