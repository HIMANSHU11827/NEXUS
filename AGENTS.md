# NEXUS AI — Agent Workspace

## Project
**C:\Users\himan\Desktop\NEXUS AI**

Custom local-first autonomous AI agent framework. Python backend + React/TypeScript GUI + Python TUI.

## Project Structure
- `nexus/` — Boot loader, canonical event system (`CanonicalEvent`, `EVENT_TYPES`)
- `server/` — FastAPI HTTP/SSE server (port 8000)
- `orchestrators/` — `loop.py` (main agent loop), `architect.py` (legacy)
- `providers/` — 30+ LLM provider implementations (OpenAI, Anthropic, Ollama, etc.)
- `tools/` — Tool registry with `.jsnol` metadata discovery (deep_research/, hive/ added)
- `hive/` — Sub-agent engine (`NexusHiveEngine`) — spawn_agent, spawn_hive, consolidate_hive
- `gui/` — React 19 + Vite + TypeScript GUI (port 5173)
- `tui/` — Ink-based TUI launched by default
- `shell/` — legacy Rich-based shell
- `mcp/` — MCP server integration
- `plugins/` — Plugin system with lifecycle hooks
- `skills/` — Skill system with SKILL.md format
- `memory/` — Multi-source MemoryManager
- `sandbox/` — 3-tier command sandbox + risk scoring
- `kernel/` — Central singleton with lazy-loaded subsystems

## Windows Setup
```powershell
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Run Commands
- **TUI** (default): `python -m nexus` — Ink TUI + backend
- **Rich shell**: `python -m nexus --shell` — legacy Rich shell, in-process
- **GUI** : `python -m nexus --gui` — React 19 + Vite + backend
- **Server**: `python -m nexus --server` — FastAPI on :8000
- **Gateway**: `python -m nexus --gateway` — Telegram, Discord, WhatsApp, Slack
- **Setup**: `python -m nexus --setup` — Setup wizard
- **Help**: `python -m nexus --help` — All options

## Test Commands
- `python -m pytest tests/ -v`
- `cd gui && npm run build`

## Event Model
Canonical events in `nexus/events.py`. ~50 event types covering run, message, plan, phase, tool, command, file, search, web, test, subagent lifecycles. Events flow via `work_event_sink` callback. Streamed to GUI via SSE.

## Security Notes
- Command risk scoring in `sandbox/risk.py`
- 3-tier sandbox: NO_SANDBOX / NORMAL / DOCKER
- Threat pattern detection in `tools/threat_patterns.py`
- Plugin trust model in `plugins/trust.py`
- No unsafe defaults; ask before destructive commands

## Fixed Issues (historical — most are now stable)
- `/api/files/list` endpoint, `kernel/__init__.py` subsystem loading, `orchestrators/architect.py` import stubs
- `gui/` — removed fake dino templates, connected TerminalPanel to SSE, added error states/retry to FileExplorer
- `server/` auth middleware — `/api/state` added to public skip list
- 4 silent try/except blocks now log warnings; 15 dev artifacts deleted
- 10 event model E2E smoke tests + 5 API smoke tests
- `orchestrators/loop.py` — SCAState enum + state machine references removed
- `shell/__init__.py` — interactive lists, tab completion, event icons, turn separator, Done panel, prompt improvements
- `hive/engine.py` — full sub-agent implementation (spawn, consolidate, blackboard, live signals, events)
- `tools/deep_research/` and `tools/hive/` tools created

## Known Limitations
- `orchestrators/architect.py` is legacy with stub imports for missing modules
- `kernel/__init__.py` references ~20 lazy-loaded subsystems that may not exist
- `hive/engine.py` sub-agents need a configured LLM provider to actually run (fallback chain: MoE router → direct provider → openai localhost)
- Some tools in `tools/<name>/` have metadata but no actual handler scripts
- `evolution/` subsystem is largely stubs — `ensemble` (hardcoded stub), `horizons`, `hyper_kernel`, `omni_kernel`, `researcher` (constructors only)
- No WebSocket yet — uses SSE + polling
