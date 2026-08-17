# NEXUS AI — Complete Codebase Structure Map

> **Project**: `C:\Users\himan\Desktop\NEXUS AI`  
> **Remote**: https://github.com/HIMANSHU11827/NEXUS.git  
> **Branch**: main  


---

## Table of Contents

| # | Directory | Purpose | Status |
|---|-----------|---------|--------|
| 1 | `src/nexus/` | Events & Boot Loader | Stable |
| 2 | `apps/api/` | FastAPI HTTP/SSE Server (v2.1.0) | Stable |
| 3 | `gateways/` | Multi-Platform Gateway (21 platforms) | Beta |
| 4 | `src/nexus/main_agent/` | NexusLoop Agent Loop (rebuilt) | Stable |
| 5 | `src/nexus/runtime/kernel/` | Central Singleton (20 subsystems) | Stable |
| 6 | `models/providers/` | 40+ LLM Provider + OAuth | Stable |
| 7 | `src/nexus/capabilities/intelligence/` | MoE Router + NATE 5-Layer Engine | Beta |
| 8 | `knowledge/rag/` | BM25 + SimHash + Atlas Deep Indexing | Beta |
| 9 | `src/nexus/capabilities/reasoning/` | HyperReasoningEngine | Beta |
| 10 | `extensions/tools/built_in/` | Registry-discovered tools (BaseTool + .jsnol) | Stable |
| 11 | `hive/` | Sub-Agent Engine | Beta |
| 12 | `extensions/skills/built_in/` | Skill Registry (SKILL.md) | Stable |
| 13 | `extensions/plugins/built_in/` | Plugin System + Trust Model | Beta |
| 14 | `extensions/mcp/core/` | MCP Client/Server/Tool Integration | Beta |
| 15 | `memory/` | Multi-Source MemoryManager | Stable |
| 16 | `sandbox/` | 3-Tier Sandbox + Risk Scoring | Stable |
| 17 | `security/policies/` | Sovereign Laws + Logic Prover | Stable |
| 18 | `security/` | Secret Scanner | Stable |
| 19 | `security/core/auth.py` | OAuth 2.0 + Token Auth | Stable |
| 20 | `evolution/` | Self-Improvement (6 Forges + VersionManager) | Beta |
| 21 | `apps/web/` | React 18 + Vite + TypeScript (rebuilt) | Stable |
| 22 | `apps/tui/` | Ink TUI (React 19) | Stable |
| 23 | `apps/voice/` | Voice Pipeline (4 STT backends) | Beta |
| 24 | `configure/` | YAML/JSON/env Configuration | Stable |
| 25 | `tests/` | 150+ Test Files | Stable |
| 26 | `docs/` | Documentation (32 markdown files) | Mixed |
| 27 | `scripts/` | Build & Run Scripts | Stable |
| 28 | `deployment/` | Docker Deployment | Stable |

---

## 1. `src/nexus/` — Events & Boot Loader

**Purpose**: Entry point for the entire NEXUS AI runtime. Handles boot sequence, process lifecycle, command aliases, and canonical event system.

### Python Files
| File | Description |
|------|-------------|
| `src/nexus/__init__.py` | Boot loader (687 lines) — loads `.env`, applies command aliases, launches TUI/GUI/server/gateway/setup, export/import, first-run wizard |
| `src/nexus/__main__.py` | Delegates to `boot()` |
| `src/nexus/commands.py` | CommandRegistry singleton — canonical 152-command catalog across shared/client general, settings, info, workspace, developer, integrations, and orchestration entries |
| `src/nexus/events.py` | **CanonicalEvent** dataclass — ~50 event types with validation, `infer_event_type()` heuristic |
| `src/nexus/runtime.py` | `ChatRunRequest`, session/turn ID sanitization, provider normalization |
| `src/nexus/run_context.py` | `RunContext` durable identity, `start_run_context()`, `list_run_contexts()`

---

## 2. `apps/api/` — FastAPI HTTP/SSE Server

**Purpose**: Standalone HTTP API server (port 8000, v2.1.0) powering the GUI, TUI, and external clients. OpenAI-compatible `/v1/chat/completions` endpoint. 80+ API endpoints covering sessions, chat, files, providers, tools, skills, plugins, MCP, voice, engine management, auth.

### Python Files
| File | Description |
|------|-------------|
| `apps/api/__init__.py` | **2,690 lines** — Main FastAPI app. 80+ routes: `/api/chat`, `/api/sessions`, `/api/history`, `/v1/chat/completions`, `/api/tools`, `/api/skills`, `/api/files/list`, `/api/voice/*`, `/api/engine/*`, auth middleware, CORS, SSE streaming, OpenAI-compatible streaming |
| `apps/api/__main__.py` | Uvicorn runner (`python -m apps.api`)

### Subdirectories
- `.nexus/logs/` — session logs (`sessions/`, `run_contexts/`)
- `.nexus/workspace/` — runtime state (`kernel_state.json`, `active_session.json`)

---

## 3. `src/nexus/main_agent/` — Agent Loop

**Purpose**: Core agent orchestration — the main `NexusLoop` sovereign reasoning loop (`src/nexus/main_agent/core.py`, rebuilt).

### Python Files
| File | Description |
|------|-------------|
| `src/nexus/main_agent/core.py` | **NexusLoop V5** — canonical sovereign loop. Direct model/tool turns, registry discovery, permission policies, memory management, risk scoring, Hive/MCP integration, verification, and canonical work events |
| `src/nexus/main_agent/__init__.py` | Package init |

### Notes
- `architect.py` (legacy) and `mission_control.py` have been removed — planning uses `todo.md` + `planning` tool

---

## 4. `models/providers/` — 40+ LLM Provider Implementations

**Purpose**: Universal LLM provider abstraction. Every major provider has a dedicated adapter with OAuth, auto-healing, health checks, and routing.

### Python Files (core)
| File | Provider |
|------|----------|
| `models/providers/core/base.py` | Base provider interface |
| `models/providers/core/factory.py` | NexusProviderFactory — creates provider instances |
| `models/providers/core/profiles.py` | Provider profiles/capabilities |
| `models/providers/core/router.py` | Provider routing logic |
| `models/providers/core/health.py` | Health check system |
| `models/providers/core/auto_detect.py` | Auto-discovery of available providers |
| `models/providers/core/auto_heal.py` | Auto-recovery on provider failures |
| `models/providers/core/heal_tools.py` | Healing tool implementations |
| `models/providers/core/universal.py` | Universal provider wrapper |
| `models/providers/api/openai.py` | OpenAI |
| `models/providers/api/anthropic.py` | Anthropic (Claude) |
| `models/providers/api/deepseek.py` | DeepSeek |
| `models/providers/api/google_gemini.py` | Google Gemini |
| `models/providers/api/groq.py` | Groq |
| `models/providers/local/ollama.py` | Ollama (local) |
| `models/providers/local/llama_cpp.py` | llama.cpp |
| `models/providers/local/lm_studio.py` | LM Studio |
| `models/providers/local/lm_studio_auto.py` | LM Studio auto-config |
| `models/providers/api/mistral.py` | Mistral |
| `models/providers/api/cohere.py` | Cohere |
| `models/providers/api/perplexity.py` | Perplexity |
| `models/providers/api/together.py` | Together AI |
| `models/providers/api/huggingface.py` | Hugging Face |
| `models/providers/api/fireworks.py` | Fireworks |
| `models/providers/api/sambanova.py` | SambaNova |
| `models/providers/api/nvidia.py` | NVIDIA |
| `models/providers/api/xai.py` | xAI (Grok) |
| `models/providers/api/replicate.py` | Replicate |
| `models/providers/api/qwen.py` | Qwen |
| `models/providers/api/zupra.py` | Zupra |
| `models/providers/api/azure_openai.py` | Azure OpenAI |
| `models/providers/api/commandcode.py` | CommandCode |
| `models/providers/auth/opencode_cli.py` | OpenCode CLI |
| `models/providers/api/openrouter.py` | OpenRouter (aggregator) |
| `models/providers/core/flux_image.py` | FLUX image generation |
| `models/providers/core/vlm.py` | Vision Language Models |
| `models/providers/local/sandbox_interpreter.py` | Sandbox code interpreter |
| `models/providers/core/search_serper.py` | Serper search |
| `models/providers/core/langchain_provider.py` | LangChain bridge |
| `models/providers/core/langchain_tools.py` | LangChain tool bridge |

### Subdirectories
- `models/providers/auth/oauth/` — Full OAuth 2.0 / PKCE / Device Code flow
  - `callback_server.py`, `device_code.py`, `pkce.py`, `registry.py`, `storage.py`, `types.py`, `refresh.py`
  - `models/providers/auth/oauth/providers/` — OAuth adapters: Claude, Codex, Copilot, Gemini, Grok, Minimax, OpenRouter, Qwen, Chutes (9 providers)

---

## 5. `extensions/tools/built_in/` — Tool Registry & Tool Implementations

**Purpose**: Runtime tool discovery via `.jsnol` metadata, active local skills, and MCP adapters. The model receives the current executable registry through `ToolRegistry`.

### Core Registry
| File | Description |
|------|-------------|
| `extensions/tools/built_in/__init__.py` | Tool package init |
| `extensions/tools/built_in/nexus_tools/base_tool.py` | BaseTool abstract class + ToolResult dataclass |
| `extensions/tools/built_in/nexus_tools/registry.py` | ToolRegistry — loads `.jsnol` metadata, discovers BaseTool subclasses, validates |
| `extensions/tools/built_in/threat_patterns.py` | Content-level threat scanner — 41 regex patterns in 3 scopes (all/context/strict) |

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

> **Note**: `bash` is retired (disabled in `ToolRegistry`). The 13 stale
> unimplemented stub tool directories were removed entirely and their names
> added to `DISABLED_TOOL_NAMES`, so the registry never advertises them.

---

## 6. `gateways/` — Multi-Platform Gateway

**Purpose**: Connects NEXUS AI to external messaging platforms via 21 async platform adapters with per-platform message handling, webhook HMAC verification, session tracking, and supervised lifecycle.

### Python Files
| File | Description |
|------|-------------|
| `gateways/__init__.py` | Package init |
| `gateways/base.py` | Base gateway interface |
| `gateways/main.py` | Gateway entry point |
| `gateways/run.py` | Gateway runner + ingress dedupe |
| `gateways/supervisor.py` | GatewaySupervisor — supervised lifecycle (retries, crash-loop detection, state persistence) |
| `gateways/state.py` | GatewayStateStore — atomic JSON state persistence |
| `gateways/webhook_server.py` | Webhook server (Meta HMAC + LINE, Teams, Google Chat, Feishu, YuanBao, QQBot, DingTalk, WeCom, Weixin, BlueBubbles) |
| `gateways/session_bus_integration.py` | Session bus bridge |
| `gateways/session_ids.py` | Session ID management |

### Subdirectories
- `gateways/platforms/` — 21 async adapters: BlueBubbles, DingTalk, Discord, Email, Feishu, Google Chat, IRC, LINE, Matrix, Mattermost, Meta, QQBot, Signal, Slack, SMS, Teams, Telegram, WeCom, Weixin, WhatsApp, Yuanbao

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
| `docs/development.md` | Development guide | Current |
| `docs/design-qa.md` | Design QA report | Historical |

### Subdirectories
- `docs/architecture/` — Architecture proposals
- `docs/audits/` — Code audit reports (capability audit, full acceptance audit)
- `docs/research/` — Research notes (framework comparison, reports)
