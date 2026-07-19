# NEXUS AI — Complete Codebase Structure Map

> **Project**: `C:\Users\himan\Desktop\NEXUS AI`  
> **Remote**: https://github.com/HIMANSHU11827/NEXUS.git  
> **Branch**: main  


---

## Table of Contents

| # | Directory | Purpose |
|---|-----------|---------|
| 1 | `nexus/` | Events & Boot Loader |
| 2 | `server/` | FastAPI HTTP/SSE Server |
| 3 | `gateway/` | Multi-Platform Gateway (Telegram, Discord, WhatsApp, Slack) |
| 4 | `orchestrators/` | Agent Loop & Mission Control |
| 5 | `kernel/` | Central Singleton |
| 6 | `providers/` | 30+ LLM Provider Implementations |
| 7 | `intelligence/` | MoE Router & Intelligence |
| 8 | `rag/` | RAG Engine |
| 9 | `cognition/` | Cognitive Architecture |
| 10 | `reasoning/` | Reasoning Engine |
| 11 | `neural/` | Neural Network Models |
| 12 | `prompts/` | Prompt Templates |
| 13 | `router/` | Request Router |
| 14 | `optimization/` | Performance Optimization |
| 15 | `tools/` | Tool Registry & Tool Implementations |
| 16 | `hive/` | Sub-Agent Engine |
| 17 | `skills/` | Skill System |
| 18 | `plugins/` | Plugin System |
| 19 | `mcp/` | MCP Server Integration |
| 20 | `commands/` | Command Registry |
| 21 | `tasks/` | Task Management |
| 22 | `memory/` | Memory Manager |
| 23 | `knowledge/` | Knowledge Base |
| 24 | `indexer/` | Codebase Indexing |
| 25 | `context/` | Context Management |
| 26 | `lifecycle/` | Component Lifecycle Management |
| 27 | `gui/` | React 19 + Vite + TypeScript Frontend |
| 28 | `tui/` | Ink-based TUI |
| 29 | `shell/` | Rich-based TUI |
| 30 | `voice/` | Voice Processing |
| 31 | `dino-game/` | Dino Game Integration |
| 32 | `games/` | Game Environments |
| 33 | `sandbox/` | 3-Tier Sandbox & Risk Scoring |
| 34 | `safety/` | Safety & Guardrails |
| 35 | `security/` | Security Policies |
| 36 | `authentication/` | Auth & OAuth |
| 37 | `permissions/` | Permission Policies |
| 38 | `evolution/` | Self-Improvement & Evolution |
| 39 | `telemetry/` | Telemetry & Monitoring |
| 40 | `config/` | Configuration Files |
| 41 | `scripts/` | Build & Run Scripts |
| 42 | `tests/` | Test Suite |
| 43 | `deploy/` | Deployment Configs |
| 44 | `hardware/` | Hardware Detection |
| 45 | `external/` | External Integrations |
| 46 | `integrations/` | Integration Adapters |
| 47 | `utils/` | Utility Functions |
| 48 | `models/` | Model Files |
| 49 | `training_data/` | Training Data |
| 50 | `logs/` | Runtime Logs |
| 51 | `workspace/` | Runtime Workspace State |
| 52 | `graphify-out/` | Graph Visualization Output |
| 53 | `docs/` | Documentation |
| 54 | `bin/` | Binary & Executable Scripts |

---

## 1. `nexus/` — Events & Boot Loader

**Purpose**: Entry point for the entire NEXUS AI runtime. Handles boot sequence, process lifecycle, and defines the canonical event system used across all components.

### Python Files
| File | Description |
|------|-------------|
| `nexus/__init__.py` | Boot loader — loads `.env`, applies command aliases, launches Ink TUI/backend, GUI, server, gateway, setup, import/export |
| `nexus/__main__.py` | Delegates to `boot()` |
| `nexus/commands.py` | Command registry (shared across all interfaces) |
| `nexus/events.py` | **CanonicalEvent** — 50+ event types (`run.*`, `message.*`, `plan.*`, `tool.*`, `command.*`, `subagent.*`, etc.) with validation |

### Key Config Files
- `read.md` — directory documentation

---

## 2. `server/` — FastAPI HTTP/SSE Server

**Purpose**: Standalone HTTP API server (port 8000) powering the GUI, TUI, and external clients. OpenAI-compatible `/v1/chat/completions` endpoint. Session management, auth, CORS, SSE streaming.

### Python Files
| File | Description |
|------|-------------|
| `server/__init__.py` | **2,151 lines** — Main FastAPI app. Routes: `/api/chat`, `/api/sessions`, `/api/history`, `/v1/chat/completions`, `/api/tools`, `/api/skills`, `/api/files/list`, auth middleware, config management, OpenAI-compatible streaming |
| `server/__main__.py` | Uvicorn runner (`python -m server`) |

### Subdirectories
- `server/configs/` — runtime config files
- `server/logs/` — session logs (`sessions/`, `tasks.json`)
- `server/skill/` — skill endpoints
- `server/workspace/` — runtime state (`kernel_state.json`, `active_session.json`)

---

## 3. `orchestrators/` — Agent Loop & Mission Control

**Purpose**: Core agent orchestration — the main reasoning loop, workflow engine, and legacy architect.

### Python Files
| File | Description |
|------|-------------|
| `orchestrators/loop.py` | **NexusLoop** — Main 2,880-line sovereign loop. Permission policies (AUTO, AI_DECIDE, ASK_ALL, CHECKLIST), ToolCall, HookRegistry, `stream_run()`, tool grounding, memory management, risk scoring, self-improvement hooks |
| `orchestrators/mission_control.py` | Mission orchestration layer |
| `orchestrators/workflow_engine.py` | Workflow execution engine |
| `orchestrators/architect.py` | **Legacy** — stub imports for missing modules, kept for compatibility |
| `orchestrators/langchain_agents.py` | LangChain agent integration |

---

## 4. `providers/` — 30+ LLM Provider Implementations

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
  - `providers/oauth/providers/` — OAuth adapters for 10+ services: Claude, Codex, Copilot, Gemini, Grok, Minimax, OpenRouter, Qwen, Chutes

---

## 5. `tools/` — Tool Registry & Tool Implementations

**Purpose**: Tool discovery via `.jsnol` metadata files. 20+ tools with JSON schema definitions and Python handlers.

### Core Registry
| File | Description |
|------|-------------|
| `tools/__init__.py` | Tool package init |
| `tools/nexus_tools/base_tool.py` | BaseTool abstract class |
| `tools/nexus_tools/registry.py` | ToolRegistry — loads `.jsnol` metadata, discovers scripts |
| `tools/threat_patterns.py` | Threat pattern detection for security |

### Tool Implementations (each has `.jsnol` + `.md` + `scripts/*.py`)
| Tool | Files | Purpose |
|------|-------|---------|
| `bash` | `bash.jsnol`, `scripts/bash.py` | Shell command execution |
| `code_search` | `code_search.jsnol`, `scripts/code_search.py` | Code search across project |
| `deep_research` | `deep_research.jsnol`, `scripts/deep_research.py` | Decomposes queries, spawns RESEARCHER sub-agents |
| `git_ops` | `git_ops.jsnol`, `scripts/git_ops.py` | Git commands |
| `hive` | `hive.jsnol`, `scripts/hive.py` | Sub-agent spawning (single/parallel/hive modes) |
| `knowledge` | `knowledge.jsnol`, `scripts/knowledge.py` | Knowledge base operations |
| `memory` | `memory.jsnol`, `scripts/memory.py` | Memory operations |
| `reading` | `reading.jsnol`, `scripts/reading.py` | File/content reads |
| `creating` | `creating.jsnol`, `scripts/creating.py` | File/content creation |
| `modifying` | `modifying.jsnol`, `scripts/modifying.py` | File/content modification |
| `deleting` | `deleting.jsnol`, `scripts/deleting.py` | File/content deletion |
| `reasoning` | `reasoning.jsnol`, `scripts/reasoning.py` | Reasoning chain tool |
| `system` | `system.jsnol`, `scripts/system.py` | System info |
| `task` | `task.jsnol`, `scripts/task.py` | Task management |
| `test_runner` | `test_runner.jsnol`, `scripts/test_runner.py` | Test execution |
| `web_search` | `web_search.jsnol`, `scripts/web_search.py` | Web search tool |

---

## 6. `gateway/` — Multi-Platform Gateway

**Purpose**: Connects NEXUS AI to external messaging platforms. Supports Telegram, Discord, WhatsApp, and Slack with per-platform message handling, authentication, and event routing.

### Python Files
| File | Description |
|------|-------------|
| `gateway/__init__.py` | Package init |
| `gateway/base.py` | Base gateway interface |
| `gateway/main.py` | Gateway entry point |
| `gateway/run.py` | Gateway runner |
| `gateway/webhook_server.py` | Webhook server for incoming messages |
| `gateway/session_bus_integration.py` | Session bus bridge |
| `gateway/session_ids.py` | Session ID management |

### Subdirectories
- `gateway/telegram/` — Telegram bot adapter
- `gateway/discord/` — Discord bot adapter
- `gateway/slack/` — Slack adapter
- `gateway/whatsapp/` — WhatsApp adapter
- `gateway/platforms/` — Platform abstraction layer
- `gateway/signal/` — Signal messenger support
- `gateway/meta/` — Meta platform integrations

---

## 7. `docs/` — Documentation

**Purpose**: Central documentation hub for the NEXUS AI project — architecture guides, API references, roadmaps, and development notes.

### Key Files
| File | Description |
|------|-------------|
| `docs/ARCHITECTURE.md` | System architecture overview |
| `docs/GUI_ARCHITECTURE.md` | GUI frontend architecture |
| `docs/AGENT_LOOP.md` | Main agent loop design |
| `docs/AGENT_CONTEXT.md` | Agent context management |
| `docs/HIVE.md` | Sub-agent engine documentation |
| `docs/MCP_CODE_GRAPH.md` | MCP code graph guide |
| `docs/NEXUS.md` | NEXUS framework overview |
| `docs/README.md` | Docs landing page |
| `docs/ROADMAP.md` | Project roadmap |
| `docs/ROADMAP_STATUS.md` | Roadmap status tracking |
| `docs/WORK_EVENTS.md` | Event system documentation |
| `docs/VOICE_ASSISTANT.md` | Voice assistant docs |
| `docs/UNIFIED_GRAPH.md` | Unified graph documentation |
| `docs/TUI_COMMANDS.md` | TUI command reference |
| `docs/PROJECT_MEMORY.md` | Project memory documentation |
| `docs/NATE.md` | NATE system documentation |
| `docs/NEXUS_WORKFLOW_MODEL.md` | Workflow model docs |
| `docs/HERMES_COMPARISON.md` | Hermes comparison |
| `docs/MEDIAPIPE_SUITE.md` | MediaPipe suite docs |
| `docs/SPECIAL_FOCUS.md` | Special focus areas |
| `docs/DEVELOPMENT.md` | Development guide |
| `docs/NEXUS_OPTIMIZATION_NEXTGEN_BLUEPRINT.md` | Optimization blueprint |
| `docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md` | Unified agent architecture |

### Subdirectories
- `docs/architecture/` — Architecture diagrams and details
- `docs/audits/` — Code audit reports
- `docs/research/` — Research notes and findings
