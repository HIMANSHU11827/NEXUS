# NEXUS AI — Agent Workspace

## Project
**C:\Users\himan\Desktop\NEXUS AI**

Custom local-first autonomous AI agent framework. Python backend + React/TypeScript GUI + Ink TUI.

## Project Structure
- `src/nexus/` — Boot loader, canonical event system (`CanonicalEvent`, ~50 `EVENT_TYPES`)
- `apps/api/` — FastAPI HTTP/SSE server (port 8000, v2.1.0)
- `src/nexus/main_agent/` — `src/nexus/main_agent/core.py` (V5 `NexusLoop` — direct model/tool loop, stable)
- `models/providers/` — 40+ LLM provider implementations (core/api/local/auth) with OAuth and fallback
- `extensions/tools/built_in/` — implemented tools, `.jsnol`/`.json` metadata discovery (BaseTool + ToolRegistry)
- `hive/` — Sub-agent engine (`NexusHiveEngine`) — spawn, consolidate, blackboard
- `apps/web/` — React 18 + Vite + TypeScript GUI (port 5173) — rebuilt from scratch
- `apps/tui/` — Ink-based TUI (React 19, v3.0 redesign, 133 slash commands) launched by default
- `extensions/mcp/core/` — MCP stdio client/server integration (NEXUSMCPServer + MCPClient + MCPTool)
- `extensions/plugins/built_in/` — Plugin system with lifecycle hooks, trust model, tool registration
- `extensions/skills/built_in/` — Skill registry with SKILL.md frontmatter format (69 skills, 14 categories)
- `memory/` — Multi-source MemoryManager with parallel prefetch + sync
- `sandbox/` — 3-tier command sandbox (NO_SANDBOX/NORMAL/DOCKER) + risk scoring
- `src/nexus/runtime/kernel/` — Central singleton with 20 lazy-loaded subsystems
- `knowledge/rag/` — BM25 + SimHash hybrid retrieval with Atlas deep indexing
- `security/policies/` — Sovereign laws + logic prover + threat pattern scanning
- `apps/voice/` — Full voice pipeline (STT with 4 backends + KittenTTS + VAD)
- `gateways/` — 21-platform messaging gateway (Telegram, Discord, WhatsApp, Slack, etc.)
- `evolution/` — Self-improvement system with 6 forges + VersionManager
- `src/nexus/capabilities/intelligence/` — MoE Router + NATE 5-layer fused tool engine
- `src/nexus/capabilities/reasoning/` — HyperReasoningEngine (planner/critic/verifier)
- `security/core/auth.py` — OAuth 2.0 (Google, GitHub) + token auth + gateway auth
- `security/` — Secret scanner + release hygiene
- `configure/` — YAML/JSON/env configuration with NexusConfigLoader
- `tests/` — 150+ test files

## Windows Setup
```powershell
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Run Commands
- **TUI** (default): `python -m nexus` — Ink TUI + backend
- **Rich shell**: `python -m nexus --shell` — legacy Rich shell (compat shim)
- **GUI** : `python -m nexus --gui` — React 18 + Vite + backend
- **Server**: `python -m nexus --server` — FastAPI on :8000
- **Gateway**: `python -m nexus --gateway` — Telegram, Discord, WhatsApp, Slack, Signal, etc.
- **Setup**: `python -m nexus --setup` — Setup wizard
- **Quick**: `python -m nexus --quick` — Quick start with defaults
- **Help**: `python -m nexus --help` — All options

## Test Commands
- `python -m pytest tests/ -v`
- `cd apps/web && npm run build`
- `cd apps/tui && npx tsx nexus-tui.tsx`

## Event Model
Canonical events in `src/nexus/events.py`. ~50 event types covering run, message, plan, phase, tool, command, file, search, web, test, subagent lifecycles. Events flow via `work_event_sink` callback. Streamed to GUI via SSE.

## Security Notes
- Command risk scoring in `sandbox/risk.py`
- 3-tier sandbox: NO_SANDBOX / NORMAL / DOCKER
- Threat pattern detection in `extensions/tools/built_in/threat_patterns.py` (41 regex patterns, 3 scopes)
- Plugin trust model in `extensions/plugins/built_in/trust.py`
- Sovereign safety laws in `security/policies/laws.py` + LogicProver
- No unsafe defaults; ask before destructive commands

## Known Limitations
- Legacy `architect.py` and `mission_control.py` removed — planning uses `todo.md` + `planning` tool
- `src/nexus/capabilities/intelligence/moa.py` (MixtureOfArchitects) and `src/nexus/capabilities/intelligence/local_brain.py` (NexusLocalBrain) are stubs
- 13 tool directories are unimplemented stubs — registered but marked `unavailable` by `ToolRegistry`
- `bash` tool is retired — `terminal` is the only command-execution tool
- No WebSocket yet — uses SSE + polling

## Permanent Multi-Agent Workflow Rule

For **every meaningful task**, use a multi-agent workflow — never solve a complex task with a single agent.

1. **Understand & inspect** — read the full request and all relevant project files, docs, logs, configs, errors, and existing implementation.
2. **Plan** — objectives, subtasks, dependencies, risks, completion criteria. Track in `docs/MULTI_AGENT_TASKS.md`.
3. **Assign specialists** — Coordinator, Research, Repository Analyst, Architecture, Implementation, Debugging, Testing, Security, Performance, UI/UX, Documentation, Critical Reviewer. Only create the agents the task needs; every agent must do real work.
4. **Execute in parallel** when tasks are independent; sequential when dependent. Give each agent clear file/module ownership to avoid concurrent writes to the same file.
5. **Communicate & verify** — agents share findings, file paths, conflicts; a reviewer verifies accuracy via inspection, execution, and testing.
6. **Integrate** — combine approved work into one complete result; preserve working features.
7. **Test & iterate** — run tests, inspect failures, fix root causes, repeat until completion criteria met.

**Quality gate:** task is complete only when Critical Reviewer + Testing Agent confirm: outcome implemented, root problem addressed, relevant tests pass, no regression, security/performance checked where relevant, docs updated, no placeholders/fakes.

**Hard rules:** never claim something works without evidence; never stop at a plan or first error; never hide failures; never use fake/placeholder/simulated output; never delete important files, expose secrets, publish, spend money, or do irreversible/destructive/security-sensitive actions without explicit authorization.

Full rule: see skill `multi-agent-workflow`.
