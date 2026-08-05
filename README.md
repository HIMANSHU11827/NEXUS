# NEXUS AI v2.1.0

**Local-first autonomous AI agent framework** — *"The Operating System of Intelligence"*

> **Status**: Active Development | **License**: MIT | **Python**: 3.13+ | **Node**: 20+

---

## Quick Start

```powershell
pip install -e .
python -m nexus             # TUI (default)
python -m nexus --gui       # React GUI
python -m nexus --server    # FastAPI server on :8000
python -m nexus --gateway   # Multi-platform gateway
python -m nexus --setup     # Setup wizard
python -m nexus --shell     # Legacy Rich shell
python -m nexus --help      # All options
```

Set provider keys via environment variables or `config/.env`:

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:DEEPSEEK_API_KEY = "..."
```

---

## Interfaces

| Interface | Command | Technology | Status |
|-----------|---------|------------|--------|
| TUI | `python -m nexus` | Ink (React 19) + backend | **Stable** |
| GUI | `python -m nexus --gui` | React 18 + Vite + FastAPI | **Stable** |
| Shell | `python -m nexus --shell` | Rich (legacy compat shim) | **Legacy** |
| Server API | `python -m nexus --server` | FastAPI on port 8000 (v2.1.0) | **Stable** |
| Gateway | `python -m nexus --gateway` | Telegram, Discord, WhatsApp, Slack, Signal, Matrix + more | **Beta** |

### GUI chat output

The React GUI renders assistant responses as readable Markdown in both live chats and restored history. Headings, bold text, lists, links, inline code, fenced code blocks, and GitHub-style tables are displayed as native UI elements; raw Markdown markers are not shown as plain chat text. Tables scroll horizontally when a result is wider than the chat panel.

See [`docs/GUI_ARCHITECTURE.md`](docs/GUI_ARCHITECTURE.md#chat-rendering) for the rendering and history behavior.

---

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for full details.

| Layer | Components | Status |
|-------|-----------|--------|
| **Boot** | `nexus/` (boot, events, commands, runtime) | **Stable** |
| **Agent Loop** | `orchestrators/v5/core.py` — V5 `NexusLoop` with the direct model/tool loop | **Stable** |
| **Kernel** | `kernel/` — thread-safe singleton, 19 lazy-loaded subsystems | **Stable** |
| **API** | `server/` (FastAPI v2.1.0), `gui/api.py` (GUI backend) | **Stable** |
| **Providers** | 45+ LLM providers with OAuth, health, auto-heal, fallback chains | **Stable** |
| **Tools** | Registry-discovered tools and skills (BaseTool + ToolRegistry + `.jsnol` metadata) | **Stable** |
| **Intelligence** | `intelligence/` — MoE Router + NATE 5-layer fused tool engine | **Beta** |
| **Reasoning** | `reasoning/` — HyperReasoningEngine (planner/critic/verifier) | **Beta** |
| **Memory** | `memory/` — multi-source MemoryManager with parallel prefetch/sync | **Stable** |
| **RAG** | `rag/` — BM25 + SimHash hybrid + Atlas deep indexing | **Beta** |
| **Sandbox** | `sandbox/` — 3-tier command sandbox + risk scoring + failure memory | **Stable** |
| **Safety** | `safety/` — sovereign laws + logic prover | **Stable** |
| **Security** | `security/` — secret scanner, threat patterns, MCP security | **Stable** |
| **Authentication** | `authentication/` — OAuth 2.0 (Google, GitHub) + token auth | **Stable** |
| **Plugins** | `plugins/` — plugin system with hooks, trust model, tool registration | **Beta** |
| **Skills** | `skills/` — skill registry with SKILL.md format (6 installed) | **Stable** |
| **MCP** | `mcp/` — MCP stdio client/server/tool integration | **Beta** |
| **Voice** | `voice/` — 4 STT backends + KittenTTS + VAD | **Beta** |
| **Hive** | `hive/` — multi-agent sub-engine (spawn, consolidate, blackboard) | **Beta** |
| **Gateway** | `gateway/` — 10-platform messaging gateway | **Beta** |
| **Evolution** | `evolution/` — self-improvement (6 forges + VersionManager) | **Beta** |
| **GUI** | `gui/` — React 18 + Vite + TypeScript (rebuilt from scratch) | **Stable** |
| **TUI** | `tui/` — Ink (React 19) TUI with 130+ slash commands | **Stable** |

---

## Provider Setup

Providers are configured in `config/provider.yml`. Keys use `${ENV_VAR}` references:

```yaml
openai:
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o

anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-sonnet-4-20250514

ollama:
  base_url: http://localhost:11434
  model: llama3

deepseek:
  api_key: ${DEEPSEEK_API_KEY}
  model: deepseek-chat
```

Environment variables take precedence. See `config/provider.yml` for all configured providers.

---

## Tool Execution

Tools are discovered from `tools/<name>/` directories via `.jsnol` metadata files and registered by `ToolRegistry`. Each tool exposes JSON schema for LLM function calling and extends `BaseTool`.

**Tools are discovered at runtime** from `tools/<name>/<name>.jsnol` metadata and active local skills. The model receives the current executable registry, including available MCP tools, rather than a hardcoded tool list.

**Security model**:
- **3-tier sandbox**: `NO_SANDBOX` / `NORMAL` / `DOCKER`
- **Risk scoring**: `CommandRiskScorer` (8 regex rules, 16 safe prefixes, block threshold 80)
- **Permission modes**: auto, ai_decide, ask_all, checklist
- **Threat detection**: `tools/threat_patterns.py` — 55 regex patterns across 3 scopes
- **Failure memory**: `sandbox/failure_memory.py` — append-only JSONL failure log

---

## Configuration

| File | Purpose |
|------|---------|
| `config/provider.yml` | Provider definitions, model endpoints, API keys |
| `config/settings.yml` | Runtime settings (theme, temperature, safety, etc.) |
| `config/nexus_config.yaml` | Runtime preferences (permission mode, sandbox tier) |
| `config/mcp_servers.json` | MCP server definitions |
| `config/.env` | Provider API keys (loaded by python-dotenv) |

Environment variables take precedence: `NEXUS_API_HOST`, `NEXUS_API_PORT`, `NEXUS_DASHBOARD_TOKEN`.

---

## Project Structure

```
nexus/              Boot loader, events, commands, runtime, run context
server/             FastAPI HTTP/SSE server (port 8000, v2.1.0)
orchestrators/      NexusLoop agent loop (3555 lines, rebuilt)
providers/          45+ LLM provider implementations + OAuth
tools/              Registry-discovered tools with .jsnol metadata + BaseTool
gui/                React 18 + Vite + TypeScript frontend (port 5173, rebuilt)
tui/                Ink-based TUI (React 19, 5000+ lines)
shell/              Legacy Rich-based compat shim
hive/               Sub-agent engine (spawn, consolidate, blackboard)
kernel/             Central singleton (19 lazy-loaded subsystems)
memory/             Multi-source MemoryManager (parallel prefetch/sync)
rag/                BM25 + SimHash hybrid + Atlas deep indexing
sandbox/            3-tier sandbox + risk scoring + failure memory
safety/             Sovereign laws + logic prover
security/           Secret scanner + release hygiene
authentication/     OAuth 2.0 (Google, GitHub) + token auth
plugins/            Plugin system with hooks + trust model
skills/             Skill registry with SKILL.md format
mcp/                MCP stdio client/server/tool integration
voice/              Voice pipeline (4 STT backends + KittenTTS)
gateway/            10-platform messaging gateway
evolution/          Self-improvement (6 forges + VersionManager)
intelligence/       MoE router + NATE 5-layer tool engine
reasoning/          HyperReasoningEngine
config/             YAML/JSON/env configuration loader
tests/              42+ test files (126/127 passing)
scripts/            Helper scripts
deploy/             Docker deployment
```

---

## Testing

```powershell
python -m pytest tests/ -v
cd gui && npm run build       # TypeScript + Vite build
cd tui && npm run build       # Ink TUI type check
```

---

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

- **Linting**: `ruff` (select E, F, I; ignore E501)
- **Type checking**: `pyright` (basic mode)
- **GUI**: `cd gui && npm run dev` (Vite dev server)
- **TUI**: `cd tui && npx tsx nexus-tui.tsx`

---

## Known Limitations

- `orchestrators/architect.py` and `mission_control.py` — removed (legacy), planning uses `todo.md` + `planning` tool
- `intelligence/moa.py` (MixtureOfArchitects) and `intelligence/local_brain.py` (NexusLocalBrain) are stubs
- `tools/reasoning/` handler is a template stub — needs real LLM-based chain-of-thought
- `tools/system/` is partial — `disk` and `process` actions not implemented
- `evolution/` has stub modules: `ensemble`, `omni_kernel`, `researcher` (constructors only)
- No WebSocket — SSE + polling used for streaming

---

## License

MIT — see LICENSE file for details.
