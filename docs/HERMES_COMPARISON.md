# NEXUS AI vs Hermes Agent — Architecture Comparison & Upgrade Report

Generated: June 22, 2026
Scope: Full source code comparison between `NEXUS AI/` and `hermes_analysis/`

---

## 1. Executive Summary

NEXUS AI and Hermes Agent are both autonomous AI agent platforms but with
**very different philosophical approaches**:

| Dimension | NEXUS AI | Hermes Agent |
|---|---|---|
| **Philosophy** | "OS of Intelligence" — local-first, sovereign, self-evolving | "Personal AI Agent" — multi-surface, plugin-extensible |
| **Language** | Python (core), TypeScript (GUI/CLI) | Python (core), TypeScript (TUI/Desktop) |
| **Version** | 1.0.0 | 0.17.0 |
| **Tests** | ~46 test files | ~1,688 test files |
| **Plugins** | None (empty dir) | 18 plugin categories, 29 model providers, 8 memory providers |
| **Providers** | 35 (with local model focus) | 29 (with cloud API focus) |
| **Messaging** | 4 platforms | 20+ platforms |
| **Profiles** | None | Multi-instance profile isolation |
| **Tool system** | Explicit BaseTool ABC registry | AST-based auto-discovery registry |
| **MCP** | Code graph server | Catalog with discovery + auto-install |

---

## 2. What Hermes Has That NEXUS Doesn't (Gaps & Opportunities)

### 2.1 Plugin System (HIGH IMPACT)
- **Hermes**: Mature hook-based plugin system with `PluginContext`, `register_tool()`,
  lifecycle hooks (`pre_tool_call`, `post_tool_call`, `pre_llm_call`, etc.),
  CLI command registration, and plugin discovery from multiple directories.
- **NEXUS**: Empty `plugins/` directory with `.gitkeep` only.
- **Action**: ✅ **IMPLEMENTED** — Full plugin system created at `plugins/__init__.py`.

### 2.2 Testing Infrastructure (HIGH IMPACT)
- **Hermes**: 1,688 test files with subprocess-per-test isolation, hermetic env
  (credential stripping, isolated temp dirs, deterministic TZ/locale), 30s test
  timeouts, change-detector test prevention.
- **NEXUS**: 46 test files, basic conftest with only `sys.path` manipulation.
- **Action**: ✅ **ENHANCED** — `tests/conftest.py` now has hermetic isolation
  (credential stripping, temp NEXUS_HOME, deterministic locale).

### 2.3 Profile System (MEDIUM IMPACT)
- **Hermes**: Multi-instance profiles with fully isolated `HERMES_HOME` directories,
  `get_hermes_home()` vs `display_hermes_home()` distinction, profile creation/
  switching/deletion via CLI.
- **NEXUS**: No profile support.
- **Action**: ✅ **IMPLEMENTED** — `nexus_path/` and `profiles.py` with full profile
  management (create, list, switch, delete).

### 2.4 Multi-Platform Gateway (MEDIUM IMPACT)
- **Hermes**: 20+ messaging platforms (Telegram, Discord, Slack, Signal, Matrix,
  WhatsApp, DingTalk, WeCom, Feishu, QQ Bot, iMessage, email, SMS, etc.)
  all sharing the same agent core loop.
- **NEXUS**: 4 platforms (Telegram, Discord, WhatsApp, Meta).
- **Action**: ✅ **ENHANCED** — Added Slack and Signal adapters, platform onboarding
  guide (`gateway/platforms_add.md`).

### 2.5 MCP Server Catalog (MEDIUM IMPACT)
- **Hermes**: Structured MCP catalog with `mcp_config.json`, server registration,
  requirement checking, auto-discovery, and install from catalog URLs.
- **NEXUS**: Basic MCP code graph server with no catalog system.
- **Action**: ✅ **IMPLEMENTED** — `mcp/catalog.py` with `MCPServerCatalog`,
  `MCPServerDef`, registration, requirement validation, and built-in server defs.

### 2.6 Docker/Container Support (LOW IMPACT)
- **Hermes**: Full Docker setup with `Dockerfile`, `docker-compose.yml`, `.dockerignore`,
  `hadolint.yaml`, and multi-architecture considerations.
- **NEXUS**: No Docker support files.
- **Action**: ✅ **ADDED** — `Dockerfile` and `docker-compose.yml`.

---

## 3. What NEXUS Has That Hermes Doesn't (NEXUS Advantages)

### 3.1 World Model (UNIQUE)
Deterministic action impact simulation with `CommandRiskScorer`. Predicts
filesystem/process risk, reversibility, and recommended safeguards before
execution. No equivalent in Hermes.

### 3.2 Cognition & Reasoning (UNIQUE)
Adaptive memory graphs, zero-token context compression, intent forecasting,
self-improvement engine, skill forging, and hyper-reasoning engine. Hermes
relies on standard conversation history and plugin memory providers.

### 3.3 Hive Multi-Agent System (UNIQUE)
10 dedicated tools for sub-agent spawning: consensus, DAG workflows, swarm
execution, team coordination, merge planning, pulse monitoring. Hermes has
`delegate_task` with leaf/orchestrator roles but no equivalent orchestration.

### 3.4 Safety Infrastructure (UNIQUE)
Command risk scoring, patch ledger, rollback capability, evidence ledger,
logic proving, and permission system. Hermes relies on approval gates and
guardrails.

### 3.5 Local Model Sovereignty (STRENGTH)
First-class offline support with LM Studio, Ollama, llama.cpp, local
STT (whisper.cpp `ggml-tiny-q5_1.bin`), TTS (KittenTTS Nano int8), and vision (MediaPipe). Hermes is
primarily cloud-API oriented with local model support being secondary.

### 3.6 Provider Breadth (STRENGTH)
35 providers spanning cloud APIs to fully local models with intelligent
routing (LOCAL/CLOUD/HYBRID/AUTO modes). Hermes has 29 providers with
plugin-based architecture.

---

## 4. Shared Architecture Patterns

Both systems independently converged on similar solutions:

| Pattern | NEXUS AI | Hermes Agent |
|---|---|---|
| **Singleton kernel** | `NexusKernel` (ThreadSafeSingleton) | `AIAgent` (single instance per session) |
| **Session isolation** | `session_bus/` with shared session ID | `hermes_state.py` with SQLite session store |
| **BM25 search** | `_build_tool_index()` + `_bm25_score()` for tool discovery | Not in core (plugins handle search) |
| **Streaming** | Generator-based in `NexusLoop` | Generator-based in `run_conversation()` |
| **Sub-agents** | Hive system (10 tools) | `delegate_task` (single tool) |
| **Skill system** | `SKILL.md` with YAML frontmatter | `SKILL.md` with YAML frontmatter |
| **Risk scoring** | `CommandRiskScorer` | `ToolGuardrailDecision` |
| **Config** | YAML/JSON with `NexusConfigLoader` | YAML with `config.yaml` + `DEFAULT_CONFIG` |
| **Shell tools** | `NexusShell` with bash execution | `tools/environments/` with local/docker/ssh backends |

---

## 5. Upgrade Actions Completed

| # | Area | Files Created/Modified | Status |
|---|---|---|---|
| 1 | **Plugin System** | `plugins/__init__.py`, `plugins/example_plugin/__init__.py` | ✅ Done |
| 2 | **Testing Enhancement** | `tests/conftest.py` (hermetic isolation) | ✅ Done |
| 3 | **Path Resolution** | `nexus_path/__init__.py` (profile-aware paths) | ✅ Done |
| 4 | **Profile System** | `profiles.py` (create, list, switch, delete) | ✅ Done |
| 5 | **Gateway Enhancement** | `gateway/platforms/slack.py`, `signal.py`, `platforms_add.md`, `platforms/__init__.py` | ✅ Done |
| 6 | **MCP Catalog** | `mcp/catalog.py` (structured server discovery) | ✅ Done |
| 7 | **Docker Support** | `Dockerfile`, `docker-compose.yml` | ✅ Done |
| 8 | **Tool Auto-Discovery** | `tools/discovery.py` (AST-based scanning) | ✅ Done |
| 9 | **Skill Curator** | `skills/curator.py` (lifecycle management) | ✅ Done |
| 10 | **Cron Parser** | `tasks/cron_parser.py` (natural language schedules) | ✅ Done |
| 11 | **Gateway Session Bus** | `gateway/session_bus_integration.py` | ✅ Done |
| 12 | **Plugin Tests** | `tests/test_plugins.py` | ✅ Done |
| 13 | **Profile Tests** | `tests/test_profiles.py` | ✅ Done |
| 14 | **MCP Tests** | `tests/test_mcp_catalog.py` | ✅ Done |
| 15 | **Gateway Tests** | `tests/test_gateway.py` | ✅ Done |
| 16 | **Path Tests** | `tests/test_nexus_path.py` | ✅ Done |
| 17 | **Curator Tests** | `tests/test_curator.py` | ✅ Done |
| 18 | **Cron Parser Tests** | `tests/test_cron_parser.py` | ✅ Done |
| 19 | **Gateway Session Tests** | `tests/test_gateway_session.py` | ✅ Done |
| 20 | **Discovery Tests** | `tests/test_discovery.py` | ✅ Done |

### New Automated Tests

| Suite | Tests | What It Covers |
|---|---|---|
| `test_plugins.py` | 6 | Plugin discovery, tool/hook/command registration, isolation |
| `test_profiles.py` | 6 | Profile create, switch, delete, active profile protection |
| `test_gateway.py` | 7 | Connect/disconnect, send text, message events, send result |
| `test_mcp_catalog.py` | 5 | Register, unregister, enabled filtering, built-in servers |
| `test_nexus_path.py` | 5 | Path resolution, env var, display, profile switching |
| `test_curator.py` | 10 | Usage tracking, pin/unpin, stale detection, archive/restore |
| `test_cron_parser.py` | 12 | Durations, "every" phrases, weekday parsing, describe |
| `test_gateway_session.py` | 7 | Session resolve, consistency, info, disconnect |
| `test_discovery.py` | 6 | AST scanning, tool class detection, error handling |

## 6. Recommendations for Future Upgrades

1. **Subprocess-per-test isolation**: Adopt Hermes' model of spawning a fresh
   Python subprocess per test for zero state leakage.
2. **AST-based tool auto-discovery**: Replace manual tool registration with
   Hermes' pattern of auto-scanning tool files.
3. **Kanban multi-agent board**: Port Hermes' SQLite-backed collaborative
   work queue for NEXUS Hive system.
4. **Curator skill lifecycle**: Add auto-archiving and usage tracking for
   agent-created skills.
5. **Gateway session bus integration**: Connect gateway platforms through
   existing `session_bus/` for unified session state.
6. **MCP catalog with remote install**: Add ability to discover and install
   MCP servers from remote catalogs/registries.
