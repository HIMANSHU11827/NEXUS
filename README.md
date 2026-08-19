# NEXUS AI v2.1.0

**Provider-agnostic autonomous AI agent framework & multi-agent runtime** — *"The Operating System of Intelligence"*

NEXUS is an AI agent system — local-first but **not local-only**. It runs on local models (Ollama, LM Studio, llama.cpp), cloud APIs (OpenAI, Anthropic, Gemini, DeepSeek, … 20+ vendors), and authenticated (OAuth) providers (Claude, Codex, Copilot, Gemini, Grok, OpenRouter, Qwen, MiniMax, Chutes, OpenCode CLI). Its built-in **Hive** engine spawns parallel / sequential / specialist / sub / team agents, like OpenCode and Hermes Agent but with full multi-agent orchestration.

> **Status**: Active Development | **License**: MIT | **Python**: 3.12+ | **Node**: 20+

---

## Installation

NEXUS uses [`uv`](https://docs.astral.sh/uv/) (fast Python package manager). Python 3.12+ is required.

```powershell
# 1. Install uv (if you don't have it)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Clone and set up the environment
git clone <your-nexus-repo-url> NEXUS-AI
cd NEXUS-AI
uv sync                 # creates .venv and installs NEXUS + dependencies

# 3. (optional) Node deps for the GUI / TUI
uv run pnpm --dir apps/web install
uv run pnpm --dir apps/tui install
```

`uv sync` installs the `nexus` package and console command, so both of these now work from anywhere inside the repo:

```powershell
nexus --version                 # console command (after uv sync)
python -m nexus --version       # equivalent
uv run nexus --version          # runs inside the managed environment
```

> **Note**: The project is a *src-layout* package and is **not** installed with `pip install -e .` — use `uv sync` (it builds and installs the `nexus` package and all console scripts). Plain `python -m nexus` only works after `uv sync` (or with `src` on `PYTHONPATH`). The setup wizard (`nexus --setup`) runs a **provider-aware** connection test that uses each provider's real wire format (OpenAI-compatible, Anthropic, Gemini, and local Ollama/LM Studio), so it won't report false failures for non-OpenAI providers.

## Quick Start

```powershell
nexus                  # TUI (default)
nexus --gui            # React GUI + backend
nexus --server         # FastAPI server on :8000
nexus --gateway        # Multi-platform gateway (Telegram, Discord, …)
nexus --v5             # V5 interactive agent REPL
nexus --autonomous     # 24/7 durable task-queue driver (runs queued tasks forever)
nexus --mission "ship the API"   # long-horizon mission (survives restart)
nexus --setup          # Setup wizard
nexus --help           # All options
```

Set provider keys via environment variables or `configure/.env`:

```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:DEEPSEEK_API_KEY = "..."
```

For local models, point NEXUS at your Ollama/LM Studio endpoint in `.env`
(`OLLAMA_ENDPOINT=http://127.0.0.1:11434/api/chat`) — no API key required.

---

## Interfaces

| Interface | Command | Technology | Status |
|-----------|---------|------------|--------|
| TUI | `nexus` | Ink (React) + backend | **Stable** |
| GUI | `nexus --gui` | React 18 + Vite + FastAPI | **Stable** |
| Shell | `nexus --shell` | Rich (legacy compat shim) | **Legacy** |
| Server API | `nexus --server` | FastAPI on port 8000 | **Stable** |
| Gateway | `nexus --gateway` | 21 platform adapters (Telegram, Discord, WhatsApp, Slack, Signal, Matrix + more) | **Beta** |
| Autonomous driver | `nexus --autonomous` | 24/7 durable queue driver (reliable/queues) | **Stable** |
| Mission | `nexus --mission "GOAL"` | long-horizon goal decomposition + recovery | **Stable** |

### GUI chat output

The React GUI renders assistant responses as readable Markdown in both live chats and restored history. Headings, bold text, lists, links, inline code, fenced code blocks, and GitHub-style tables are displayed as native UI elements; raw Markdown markers are not shown as plain chat text. Tables scroll horizontally when a result is wider than the chat panel.

See [`docs/GUI_ARCHITECTURE.md`](docs/GUI_ARCHITECTURE.md#chat-rendering) for the rendering and history behavior.

---

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for full details.

| Layer | Components | Status |
|-------|-----------|--------|
| **Boot** | `src/nexus/` (boot, events, commands, runtime) | **Stable** |
| **Agent Loop** | `src/nexus/main_agent/core.py` — V5 `NexusLoop` with the direct model/tool loop | **Stable** |
| **Kernel** | `src/nexus/runtime/kernel/` — thread-safe singleton, 20 lazy-loaded subsystems | **Stable** |
| **API** | `apps/api/` (FastAPI v2.1.0), `apps/web/api.py` (GUI backend) | **Stable** |
| **Providers** | 3-tier provider stack — local (Ollama/LM Studio/llama.cpp), API (20+ cloud vendors), auth/OAuth (Claude, Codex, Copilot, Gemini, Grok, OpenRouter, Qwen, MiniMax, Chutes, OpenCode CLI) — provider-agnostic, not local-only | **Stable** |
| **Tools** | Registry-discovered tools and skills (BaseTool + ToolRegistry + `.jsnol` metadata) | **Stable** |
| **Intelligence** | `src/nexus/capabilities/intelligence/` — MoE Router + NATE 5-layer fused tool engine | **Beta** |
| **Reasoning** | `src/nexus/capabilities/reasoning/` — HyperReasoningEngine (planner/critic/verifier) | **Beta** |
| **Memory** | `memory/` — multi-source MemoryManager with parallel prefetch/sync | **Stable** |
| **RAG** | `knowledge/rag/` — BM25 + SimHash hybrid + Atlas deep indexing | **Beta** |
| **Sandbox** | `sandbox/` — 3-tier command sandbox + risk scoring + failure memory | **Stable** |
| **Safety** | `security/policies/` — sovereign laws + logic prover | **Stable** |
| **Security** | `security/` — secret scanner, threat patterns, MCP security | **Stable** |
| **Authentication** | `security/core/auth.py` — OAuth 2.0 (Google, GitHub) + token auth | **Stable** |
| **Plugins** | `extensions/plugins/built_in/` — plugin system with hooks, trust model, tool registration | **Beta** |
| **Skills** | `extensions/skills/built_in/` — skill registry with SKILL.md format (69 files, 14 categories) | **Stable** |
| **MCP** | `extensions/mcp/core/` — MCP stdio client/server/tool integration | **Beta** |
| **Voice** | `apps/voice/` — 4 STT backends + KittenTTS + VAD | **Beta** |
| **Hive (multi-agent)** | `hive/` — multi-agent orchestration engine. Agent types: **parallel** (concurrent hive), **sequential** (staged plan), **specialist** (specialization registry), **sub** (isolated persona sub-agent), **team** (reusable `AgentTeamSpec`). Spawn, consolidate, blackboard, checkpoints, dead-agent replacement, per-agent budgets, crash-resume via SQLite. | **Beta** |
| **Gateway** | `gateways/` — 21-platform messaging gateway | **Beta** |
| **Evolution** | `evolution/` — self-improvement (6 forges + VersionManager) | **Beta** |
| **GUI** | `apps/web/` — React 18 + Vite + TypeScript (rebuilt from scratch) | **Stable** |
| **TUI** | `apps/tui/` — Ink (React 19) TUI backed by the canonical 152-command registry | **Stable** |

---

## Provider Setup

Providers are configured in `configure/provider.yml`. Keys use `${ENV_VAR}` references:

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

Environment variables take precedence. See `configure/provider.yml` for all configured providers.

---

## Tool Execution

Tools are discovered from `extensions/tools/built_in/<name>/` directories via `.jsnol` metadata files and registered by `ToolRegistry`. Each tool exposes JSON schema for LLM function calling and extends `BaseTool`.

**Tools are discovered at runtime** from `extensions/tools/built_in/<name>/<name>.jsnol` metadata and active local skills. The model receives the current executable registry, including available MCP tools, rather than a hardcoded tool list.

**Security model**:
- **3-tier sandbox**: `NO_SANDBOX` / `NORMAL` / `DOCKER`
- **Risk scoring**: `CommandRiskScorer` (8 regex rules, 16 safe prefixes, block threshold 80)
- **Permission modes**: auto, ai_decide, ask_all, checklist
- **Threat detection**: `extensions/tools/built_in/threat_patterns.py` — 41 regex patterns across 3 scopes
- **Failure memory**: `sandbox/failure_memory.py` — append-only JSONL failure log

---

## Configuration

| File | Purpose |
|------|---------|
| `configure/provider.yml` | Provider definitions, model endpoints, API keys |
| `configure/settings.yml` | Runtime settings (theme, temperature, safety, etc.) |
| `configure/settings.yml` | Runtime settings and preferences (theme, permissions, sandbox, security, etc.) |
| `configure/mcp_servers.json` | MCP server definitions |
| `configure/.env` | Provider API keys (loaded by python-dotenv) |

Environment variables take precedence: `NEXUS_API_HOST`, `NEXUS_API_PORT`, `NEXUS_DASHBOARD_TOKEN`.

---

## Project Structure

```
src/nexus/          Boot loader, events, commands, runtime, run context
apps/api/           FastAPI HTTP/SSE server (port 8000, v2.1.0)
apps/tui/           Ink-based TUI (React 19, v3.0 redesign, canonical 152-command registry)
apps/web/           React 18 + Vite + TypeScript frontend (port 5173, rebuilt)
apps/gateway/       Dedicated gateway app (engine lives in gateways/)
src/nexus/main_agent/  V5 NexusLoop agent loop (src/nexus/main_agent/core.py)
src/nexus/runtime/kernel/  Central singleton (20 lazy-loaded subsystems)
src/nexus/capabilities/   MoE router + NATE tool engine, HyperReasoningEngine, intent router
src/nexus/common/   Shared utilities (session bus, engine manager, helpers)
src/nexus/context/  Context persistence and compression
src/nexus/tasks/    Task scheduler
models/providers/   40+ LLM provider implementations (core/api/local/auth) + OAuth
extensions/tools/built_in/  Registry-discovered tools with .jsnol metadata + BaseTool
extensions/skills/built_in/ Skill registry with SKILL.md format
extensions/plugins/built_in/ Plugin system with hooks + trust model
extensions/mcp/core/  MCP stdio client/server/tool integration
hive/               Multi-agent orchestration engine — parallel / sequential / specialist / sub / team agents (spawn, consolidate, blackboard, checkpoints)
gateways/           21-platform messaging gateway
memory/             Multi-source MemoryManager (parallel prefetch/sync)
knowledge/rag/      BM25 + SimHash hybrid + Atlas deep indexing
sandbox/            3-tier sandbox + risk scoring + failure memory
security/           Secret scanners + release hygiene
security/policies/  Sovereign laws + logic prover
security/permissions/  Permission modes
security/core/auth.py  OAuth 2.0 (Google, GitHub) + token auth
observability/      Telemetry + mission replay + tool economy + unified graph
evaluation/         Evidence ledger + test selection
maintenance/        Roadmap maintenance
evolution/          Self-improvement (6 forges + VersionManager)
apps/voice/         Voice pipeline (4 STT backends + KittenTTS)
configure/          YAML/JSON/env configuration loader
tests/              150+ test files
scripts/            Helper scripts
scripts/launchers/  .cmd/.ps1 launchers
docs/               Documentation
deployment/         Docker deployment (Dockerfile; docker-compose.yml at repo root)
```

---

## Testing

```powershell
python -m pytest tests/ -v
cd apps/web && npm run build  # TypeScript + Vite build
cd apps/tui && npm run build  # Ink TUI type check
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
- **GUI**: `cd apps/web && npm run dev` (Vite dev server)
- **TUI**: `cd apps/tui && npx tsx nexus-tui.tsx`

---

## Known Limitations

- Legacy `architect.py` and `mission_control.py` — removed, planning uses `todo.md` + `planning` tool
- `src/nexus/capabilities/intelligence/moa.py` provides the hybrid provider-mesh facade and
  `src/nexus/capabilities/intelligence/local_brain.py` provides lazy local-provider routing; true
  multi-model ensemble and local vision inference remain optional capabilities
- The 13 stale unimplemented stub tool directories were permanently deleted from the source tree — the model only ever sees executable tools
- `bash` tool is retired — `terminal` is the only command-execution tool
- No WebSocket — SSE + polling used for streaming

---

## License

MIT — see LICENSE file for details.
