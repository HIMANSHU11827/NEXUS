# NEXUS AI v1.0.0

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
| TUI | `python -m nexus` | Ink + `gui.api` backend | **Stable** |
| GUI | `python -m nexus --gui` | React 19 + Vite + `gui.api` | **Beta** |
| Shell | `python -m nexus --shell` | Rich (legacy) | **Stable** |
| Server API | `python -m nexus --server` | FastAPI on port 8000 | **Stable** |
| Gateway | `python -m nexus --gateway` | Telegram, Discord, WhatsApp, Slack | **Beta** |

---

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for full details.

| Layer | Components | Status |
|-------|-----------|--------|
| **Core** | `nexus/` (boot, events), `orchestrators/loop.py` (agent loop), `kernel/` (singleton) | **Stable** |
| **API** | `server/` (FastAPI), `gui/api.py` (GUI backend) | **Stable** |
| **Providers** | 30+ LLM providers (OpenAI, Anthropic, DeepSeek, Ollama, etc.) | **Stable** |
| **Tools** | 19 tool types (bash, reading, creating, modifying, deleting, code_search, web_search, hive, deep_research, etc.) | **Stable** |
| **Memory** | `memory/` — persistent JSON memory manager | **Stable** |
| **RAG** | `rag/` — BM25 + hybrid vector retrieval (FAISS) | **Beta** |
| **Sandbox** | `sandbox/` — 3-tier command sandbox + risk scoring | **Stable** |
| **Safety** | `safety/` — safety policies, threat pattern detection | **Stable** |
| **Plugins** | `plugins/` — plugin system with trust model | **Beta** |
| **Skills** | `skills/` — skill registry with SKILL.md format | **Stable** |
| **MCP** | `mcp/` — MCP stdio client/server integration | **Beta** |
| **Voice** | `voice/` — whisper.cpp + KittenTTS | **Beta** |
| **Evolution** | `evolution/` — self-improvement modules (tool_forge, skill_forge, memory_forge, etc.) | **Experimental** |
| **Hive** | `hive/` — multi-agent sub-engine (spawn_agent, spawn_hive, consolidate_hive) | **Beta** |
| **Gateway** | `gateway/` — Telegram, Discord, WhatsApp, Slack bots | **Beta** |
| **Security** | `security/` — secret scanner, `authentication/` — OAuth + token auth | **Stable** |

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

Tools are discovered from `tools/<name>/` directories via `.jsnol` metadata files and registered by `ToolRegistry`. Each tool exposes JSON schema for LLM function calling.

**19 available tools**: bash, code_search, creating, deep_research, deleting, git_ops, hive, knowledge, memory, modifying, planning, reading, reasoning, shortcuts, system, task, terminal, test_runner, web_search

**Security model**:
- **3-tier sandbox**: `NO_SANDBOX` / `NORMAL` / `DOCKER`
- **Risk scoring**: `CommandRiskScorer` evaluates each command before execution
- **Permission modes**: auto, ai_decide, ask_all, checklist
- **Threat detection**: `tools/threat_patterns.py` blocks dangerous patterns

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
nexus/              Boot loader, canonical event system (~50 event types)
server/             FastAPI HTTP/SSE server (port 8000)
orchestrators/      Agent loop, workflow engine, legacy architect
providers/          30+ LLM provider implementations
tools/              19 tool types with .jsnol metadata + handler scripts
gui/                React 19 + Vite + TypeScript frontend (port 5173)
tui/                Ink-based TUI (v2.0.0)
shell/              Legacy Rich-based shell
hive/               Sub-agent engine (spawn_agent, spawn_hive, consolidate_hive)
kernel/             Central singleton with lazy-loaded subsystems
memory/             Persistent memory manager
rag/                BM25 + hybrid vector retrieval
sandbox/            3-tier command sandbox + risk scoring
safety/             Safety policy evaluation
plugins/            Plugin system with trust model
skills/             Skill registry
mcp/                MCP stdio client/server
voice/              Voice mode (whisper.cpp + KittenTTS)
gateway/            Multi-platform gateway bots
evolution/          Self-improvement modules
intelligence/       MoE router, local brain, NATE tool engine
reasoning/          Hyper-reasoning engine
authentication/     OAuth 2.0 / PKCE / Device Code + token auth
config/             YAML/JSON configuration loader
tests/              Test suite
scripts/            Helper scripts (GUI launcher, export, training)
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

- `orchestrators/architect.py` is legacy with stub imports
- `evolution/` has partial implementations: `ensemble`, `horizons`, `hyper_kernel`, `omni_kernel`, `researcher` are stubs (constructor-only classes)
- No WebSocket — SSE + polling is used for streaming
- GUI panel status is **Beta** — some panels may show placeholder content
- Gateway adapters (Telegram, Discord, WhatsApp, Slack) are functional but under active iteration

---

## License

MIT — see LICENSE file for details.
