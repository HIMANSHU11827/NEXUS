# NEXUS AI — Complete Codebase Structure Map

> **Project**: `C:\Users\himan\Desktop\NEXUS AI`  
> **Remote**: https://github.com/HIMANSHU11827/NEXUS.git  
> **Branch**: main  


---

## Table of Contents

| # | Directory | Purpose | Status |
|---|-----------|---------|--------|
| 1 | `nexus/` | Events & Boot Loader | Stable |
| 2 | `server/` | FastAPI HTTP/SSE Server (v2.1.0) | Stable |
| 3 | `gateway/` | Multi-Platform Gateway (21 platforms) | Beta |
| 4 | `orchestrators/` | NexusLoop Agent Loop (rebuilt) | Stable |
| 5 | `kernel/` | Central Singleton (20 subsystems) | Stable |
| 6 | `providers/` | 40+ LLM Provider + OAuth | Stable |
| 7 | `intelligence/` | MoE Router + NATE 5-Layer Engine | Beta |
| 8 | `rag/` | BM25 + SimHash + Atlas Deep Indexing | Beta |
| 9 | `reasoning/` | HyperReasoningEngine | Beta |
| 10 | `tools/` | Registry-discovered tools (BaseTool + .jsnol) | Stable |
| 11 | `hive/` | Sub-Agent Engine | Beta |
| 12 | `skills/` | Skill Registry (SKILL.md) | Stable |
| 13 | `plugins/` | Plugin System + Trust Model | Beta |
| 14 | `mcp/` | MCP Client/Server/Tool Integration | Beta |
| 15 | `memory/` | Multi-Source MemoryManager | Stable |
| 16 | `sandbox/` | 3-Tier Sandbox + Risk Scoring | Stable |
| 17 | `safety/` | Sovereign Laws + Logic Prover | Stable |
| 18 | `security/` | Secret Scanner | Stable |
| 19 | `authentication/` | OAuth 2.0 + Token Auth | Stable |
| 20 | `evolution/` | Self-Improvement (6 Forges + VersionManager) | Beta |
| 21 | `gui/` | React 18 + Vite + TypeScript (rebuilt) | Stable |
| 22 | `tui/` | Ink TUI (React 19) | Stable |
| 23 | `shell/` | Legacy Rich Compat Shim | Legacy |
| 24 | `voice/` | Voice Pipeline (4 STT backends) | Beta |
| 25 | `config/` | YAML/JSON/env Configuration | Stable |
| 26 | `tests/` | 150+ Test Files | Stable |
| 27 | `docs/` | Documentation (32 markdown files) | Mixed |
| 28 | `scripts/` | Build & Run Scripts | Stable |
| 29 | `deploy/` | Docker Deployment | Stable |

---

## 1. `nexus/` — Events & Boot Loader

**Purpose**: Entry point for the entire NEXUS AI runtime. Handles boot sequence, process lifecycle, command aliases, and canonical event system.

### Python Files
| File | Description |
|------|-------------|
| `nexus/__init__.py` | Boot loader (687 lines) — loads `.env`, applies command aliases, launches TUI/GUI/server/gateway/setup, export/import, first-run wizard |
| `nexus/__main__.py` | Delegates to `boot()` |
| `nexus/commands.py` | CommandRegistry singleton — 42 built-in slash commands across general/settings/info categories |
| `nexus/events.py` | **CanonicalEvent** dataclass — ~50 event types with validation, `infer_event_type()` heuristic |
| `nexus/runtime.py` | `ChatRunRequest`, session/turn ID sanitization, provider normalization |
| `nexus/run_context.py` | `RunContext` durable identity, `start_run_context()`, `list_run_contexts()`

---

## 2. `server/` — FastAPI HTTP/SSE Server

**Purpose**: Standalone HTTP API server (port 8000, v2.1.0) powering the GUI, TUI, and external clients. OpenAI-compatible `/v1/chat/completions` endpoint. 80+ API endpoints covering sessions, chat, files, providers, tools, skills, plugins, MCP, voice, engine management, auth.

### Python Files
| File | Description |
|------|-------------|
| `server/__init__.py` | **2,690 lines** — Main FastAPI app. 80+ routes: `/api/chat`, `/api/sessions`, `/api/history`, `/v1/chat/completions`, `/api/tools`, `/api/skills`, `/api/files/list`, `/api/voice/*`, `/api/engine/*`, auth middleware, CORS, SSE streaming, OpenAI-compatible streaming |
| `server/__main__.py` | Uvicorn runner (`python -m server`)

### Subdirectories
- `server/logs/` — session logs (`sessions/`, `tasks.json`)
- `server/workspace/` — runtime state (`kernel_state.json`, `active_session.json`)

---

## 3. `orchestrators/` — Agent Loop

**Purpose**: Core agent orchestration — the main `NexusLoop` sovereign reasoning loop (`orchestrators/v5/core.py`, rebuilt).

### Python Files
| File | Description |
|------|-------------|
| `orchestrators/v5/core.py` | **NexusLoop V5** — canonical sovereign loop. Direct model/tool turns, registry discovery, permission policies, memory management, risk scoring, Hive/MCP integration, verification, and canonical work events |
| `orchestrators/__init__.py` | Package docstring |

### Notes
- `architect.py` (legacy) and `mission_control.py` have been removed — planning uses `todo.md` + `planning` tool

---

## 4. `providers/` — 40+ LLM Provider Implementations

**Purpose**: Universal LLM provider abstraction. Every major provider has a dedicated adapter with OAuth, auto-healing, health checks, and routing.

### Python Files (Root)
| File | Provider |
|------|----------|
| `providers/base.py` | Base provider interface |
| `providers/factory.py` | NexusProviderFactory — creates provider instances |
| `providers/profiles.py` | Provider profiles/capabilities |
| `providers/router.py` | Provider routing logic |
| `providers/health.py` | Health check system |
| `providers/auto_detect.py` | Auto-discovery of available providers |
| `providers/auto_heal.py` | Auto-recovery on provider failures |
| `providers/heal_tools.py` | Healing tool implementations |
| `providers/universal.py` | Universal provider wrapper |
| `providers/openai.py` | OpenAI |
| `providers/anthropic.py` | Anthropic (Claude) |
| `providers/deepseek.py` | DeepSeek |
| `providers/google_gemini.py` | Google Gemini |
| `providers/groq.py` | Groq |
| `providers/ollama.py` | Ollama (local) |
| `providers/llama_cpp.py` | llama.cpp |
| `providers/lm_studio.py` | LM Studio |
| `providers/lm_studio_auto.py` | LM Studio auto-config |
| `providers/mistral.py` | Mistral |
| `providers/cohere.py` | Cohere |
| `providers/perplexity.py` | Perplexity |
| `providers/together.py` | Together AI |
| `providers/huggingface.py` | Hugging Face |
| `providers/fireworks.py` | Fireworks |
| `providers/sambanova.py` | SambaNova |
| `providers/nvidia.py` | NVIDIA |
| `providers/xai.py` | xAI (Grok) |
| `providers/replicate.py` | Replicate |
| `providers/qwen.py` | Qwen |
| `providers/zupra.py` | Zupra |
| `providers/azure_openai.py` | Azure OpenAI |
| `providers/commandcode.py` | CommandCode |
| `providers/opencode_cli.py` | OpenCode CLI |
| `providers/openrouter.py` | OpenRouter (aggregator) |
| `providers/flux_image.py` | FLUX image generation |
| `providers/vlm.py` | Vision Language Models |
| `providers/sandbox_interpreter.py` | Sandbox code interpreter |
| `providers/search_serper.py` | Serper search |
| `providers/langchain_provider.py` | LangChain bridge |
| `providers/langchain_tools.py` | LangChain tool bridge |

### Subdirectories
- `providers/oauth/` — Full OAuth 2.0 / PKCE / Device Code flow
  - `callback_server.py`, `device_code.py`, `pkce.py`, `registry.py`, `storage.py`, `types.py`, `refresh.py`
  - `providers/oauth/providers/` — OAuth adapters: Claude, Codex, Copilot, Gemini, Grok, Minimax, OpenRouter, Qwen, Chutes (9 providers)

---

## 5. `tools/` — Tool Registry & Tool Implementations

**Purpose**: Runtime tool discovery via `.jsnol` metadata, active local skills, and MCP adapters. The model receives the current executable registry through `ToolRegistry`.

### Core Registry
| File | Description |
|------|-------------|
| `tools/__init__.py` | Tool package init |
| `tools/nexus_tools/base_tool.py` | BaseTool abstract class + ToolResult dataclass |
| `tools/nexus_tools/registry.py` | ToolRegistry — loads `.jsnol` metadata, discovers BaseTool subclasses, validates |
| `tools/threat_patterns.py` | Content-level threat scanner — 41 regex patterns in 3 scopes (all/context/strict) |

### Tool Implementations (each has `.jsnol` + `.md` + `scripts/*.py` extending BaseTool)
| Tool | Handler | Lines | Status |
|------|---------|-------|--------|
| `code_search` | CodeSearchTool | 75 | Stable |
| `creating` | CreatingTool | 27 | Stable |
| `deep_research` | DeepResearchTool | 160 | Stable |
| `deleting` | DeletingTool | 23 | Stable |
| `git_ops` | GitOpsTool | 78 | Stable |
| `hive` | HiveTool | 157 | Stable |
| `knowledge` | KnowledgeTool | 85 | Stable |
| `memory` | MemoryTool | 104 | Stable |
| `modifying` | ModifyingTool | 85 | Stable |
| `planning` | PlanningTool | 316 | Stable |
| `reading` | ReadingTool | 24 | Stable |
| `reasoning` | ReasoningTool | 106 | Stable (v3.0.0, LLM-backed) |
| `shortcuts` | ShortcutsTool | 101 | Stable |
| `system` | SystemTool | 73 | Stable |
| `task` | TaskTool | 216 | Stable |
| `terminal` | TerminalTool | 33 | Stable |
| `test_runner` | TestRunnerTool | 89 | Stable |
| `web_search` | WebSearchTool | 277 | Stable |

> **Note**: `bash` is retired (disabled in `ToolRegistry`). 13 additional tool directories
> (`bash_timeout_control`, `browser_open`, `fault_tolerant_command_runner`, `file_path_resolver`,
> `live_news_tool`, `long_running_command_handler`, `news_aggregator_live`, `nexus_codebase_research`,
> `safe_file_path_tracking`, `sandbox_path_validation`, `sandbox_path_validator`, `workspace_path_guard`,
> `workspace_path_validation`) are **unimplemented stubs** — registered via `.json` metadata but marked
> `unavailable` by `ToolRegistry`.

---

## 6. `gateway/` — Multi-Platform Gateway

**Purpose**: Connects NEXUS AI to external messaging platforms via 21 async platform adapters with per-platform message handling, webhook HMAC verification, session tracking, and supervised lifecycle.

### Python Files
| File | Description |
|------|-------------|
| `gateway/__init__.py` | Package init |
| `gateway/base.py` | Base gateway interface |
| `gateway/main.py` | Gateway entry point |
| `gateway/run.py` | Gateway runner + ingress dedupe |
| `gateway/supervisor.py` | GatewaySupervisor — supervised lifecycle (retries, crash-loop detection, state persistence) |
| `gateway/state.py` | GatewayStateStore — atomic JSON state persistence |
| `gateway/webhook_server.py` | Webhook server (Meta HMAC + LINE, Teams, Google Chat, Feishu, YuanBao, QQBot, DingTalk, WeCom, Weixin, BlueBubbles) |
| `gateway/session_bus_integration.py` | Session bus bridge |
| `gateway/session_ids.py` | Session ID management |

### Subdirectories
- `gateway/platforms/` — 21 async adapters: BlueBubbles, DingTalk, Discord, Email, Feishu, Google Chat, IRC, LINE, Matrix, Mattermost, Meta, QQBot, Signal, Slack, SMS, Teams, Telegram, WeCom, Weixin, WhatsApp, Yuanbao

---

## 7. `docs/` — Documentation

**Purpose**: Central documentation hub — architecture guides, API references, roadmaps, and development notes.

### Key Files (32 markdown files)
| File | Description | Status |
|------|-------------|--------|
| `docs/read.md` | Directory index | Current |
| `docs/README.md` | Root-level overview | Current |
| `docs/ARCHITECTURE.md` | System architecture | Current |
| `docs/AGENT_LOOP.md` | Main agent loop design | Current |
| `docs/AGENT_CONTEXT.md` | Agent context management | Outdated |
| `docs/NEXUS.md` | NEXUS platform persona/soul | Current |
| `docs/ROADMAP.md` | Project roadmap | Current |
| `docs/ROADMAP_STATUS.md` | Roadmap status tracking (67.9%) | Current |
| `docs/PROJECT_MEMORY.md` | A-to-Z project memory | Outdated |
| `docs/GUI_ARCHITECTURE.md` | GUI frontend architecture | Current |
| `docs/TUI_COMMANDS.md` | TUI command reference | Current |
| `docs/HIVE.md` | Hive sub-agent codex | Current |
| `docs/NATE.md` | NATE tool engine | Current |
| `docs/NATE-ROADMAP.md` | NATE development roadmap | Current |
| `docs/WORK_EVENTS.md` | Event system reference | Current |
| `docs/VOICE_ASSISTANT.md` | Voice assistant integration | Current |
| `docs/MCP_CODE_GRAPH.md` | MCP code graph guide | Current |
| `docs/UNIFIED_GRAPH.md` | Unified knowledge graph | Current |
| `docs/NEXUS_WORKFLOW_MODEL.md` | Workflow/phase model | Current |
| `docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md` | Unified agent architecture | Current |
| `docs/NEXUS_OPTIMIZATION_NEXTGEN_BLUEPRINT.md` | Optimization blueprint | Current |
| `docs/HERMES_COMPARISON.md` | Hermes comparison | Historical |
| `docs/MEDIAPIPE_SUITE.md` | MediaPipe vision suite | Current |
| `docs/SPECIAL_FOCUS.md` | Special focus areas | Outdated |
| `docs/DEVELOPMENT.md` | Development guide | Current |
| `docs/design-qa.md` | Design QA report | Historical |

### Subdirectories
- `docs/architecture/` — Architecture proposals
- `docs/audits/` — Code audit reports (capability audit, full acceptance audit)
- `docs/research/` — Research notes (framework comparison, reports)
