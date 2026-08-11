# Architecture

Nexus AI is a local-first autonomous AI agent framework with a Python backend and multiple frontends.

## Core Runtime

- **nexus/** - Boot loader (`boot()` function). Entry point for `python -m nexus`, `--setup`, `--server`, `--gui`, and `--shell`. The default route launches the Ink TUI and starts `gui.api:app` when needed.
- **nexus/events.py** - Canonical event system with ~50 event types (run, conversation, message, plan, tool, command, file, search, web, test, subagent lifecycle). Events flow via `work_event_sink` callback and stream to GUI via SSE.
- **orchestrators/v5/core.py** - V5 `NexusLoop` - the main agent loop. The live path uses the transcript-driven direct model/tool loop, registry discovery, memory, provider routing, and canonical event emission.
- **kernel/** - Central singleton with lazy-loaded subsystems, workspace ownership, shared module cache, and health stats.

## API Layer

- **server/** - FastAPI HTTP/SSE server on port 8000. Authenticated via `authentication/` module. Provides:
  - `/api/chat` - Chat endpoint with streaming SSE and non-streaming modes
  - `/api/sessions` - Session CRUD
  - `/api/history` - Chat history per session
  - `/api/tools`, `/api/skills`, `/api/agents`, `/api/plugins`, `/api/mcp`, `/api/providers`, `/api/features` - Resource listing
  - `/api/manage` - Runtime management (enable/disable tools, skills, MCP, providers)
  - `/api/files/list` - Directory listing
  - `/api/health` - Health check
  - `/v1/models`, `/v1/chat/completions` - OpenAI-compatible endpoints
- **gui/api.py** - Separate FastAPI app for the GUI frontend.

## Providers

- **providers/** - 40+ LLM provider implementations:
  - Cloud: OpenAI, Anthropic, DeepSeek, Google Gemini, Groq, Mistral, Cohere, Perplexity, Together AI, Fireworks, Sambanova, xAI, OpenRouter, HuggingFace, NVIDIA
  - Local: Ollama, LM Studio, llama.cpp, Zupra (offline CPU)
  - Utilities: auto-detect, auto-heal, health telemetry, capability-aware routing, fallback chain
- **providers/router.py** - Provider router for capability-aware fallback
- **providers/factory.py** - `NexusProviderFactory` singleton
- **providers/profiles.py** - Provider profile store

## Tools

- **tools/** - Registry-discovered tools organized in subdirectories:
  - Implemented (18): `code_search/`, `creating/`, `deep_research/`, `deleting/`, `git_ops/`, `hive/`, `knowledge/`, `memory/`, `modifying/`, `planning/`, `reading/`, `reasoning/`, `shortcuts/`, `system/`, `task/`, `terminal/`, `test_runner/`, `web_search/`
  - Unimplemented stubs (13): `bash_timeout_control/`, `browser_open/`, `fault_tolerant_command_runner/`, `file_path_resolver/`, `live_news_tool/`, `long_running_command_handler/`, `news_aggregator_live/`, `nexus_codebase_research/`, `safe_file_path_tracking/`, `sandbox_path_validation/`, `sandbox_path_validator/`, `workspace_path_guard/`, `workspace_path_validation/` — registered via `.json` metadata but marked `unavailable`
  - Each tool has a `<name>.jsnol` metadata file and handler scripts (stub tools use `.json` only)
- **tools/nexus_tools/registry.py** - `ToolRegistry` for tool discovery and management (note: `bash` is retired — `terminal` is the only command-execution tool)
- **tools/threat_patterns.py** - Threat pattern detection for security (41 regex patterns, 3 scopes)

## Interfaces

Three user interfaces, all feeding into the same agent runtime:

| Interface | Command | Technology | Port |
|-----------|---------|------------|------|
| **TUI** | `python -m nexus` | Ink + `gui.api` backend | 8000 |
| **Rich shell** | `python -m nexus --shell` | Rich | in-process |
| **GUI** | `python -m nexus --gui` | React 18 + Vite + `gui.api` | 8000/5173 |
| **Server** | `python -m nexus --server` | standalone FastAPI `server:app` | 8000 |
| **Gateway** | `python -m nexus --gateway` | 21 platforms (Telegram, Discord, WhatsApp, Slack, Teams, WeCom, etc.) | external |

All interfaces share sessions via `utils/session_bus.py`:
- `workspace/active_session.json` - Active session tracking
- `logs/sessions/<id>.json` - Conversation memory
- `workspace/work_events/<id>.jsonl` - Mission timeline

## Support Systems

- **memory/** - Multi-source `MemoryManager` (JSONL + in-memory hybrid) with parallel prefetch/sync and verified-evidence gating
- **sandbox/** - `CommandRiskScorer` with 3 tiers: NO_SANDBOX / NORMAL / DOCKER
- **rag/** - BM25 + hybrid vector retrieval with Atlas deep indexing
- **knowledge/** - Knowledge store with SQLite index and RAG index files
- **context/** - Context persistence and compression (`NexusContextCompressor`)
- **safety/** - Safety laws and policy evaluation
- **security/** - Secret scanner for repository hygiene
- **permissions/** - Permission mode definitions (auto, plan, acceptEdits, dontAsk, bypass, approve)
- **lifecycle/** - Lifecycle hooks (tool, skill, plugin, memory, cron, self-improvement)
- **tasks/** - Task scheduler
- **telemetry/** - SQLite-based telemetry database
- **hive/** - Multi-agent orchestration engine
- **reasoning/** - Hyper-reasoning engine for planner/critic/verifier workflows
- **router/** - Intent router for multi-signal intent classification

## Extension Systems

- **mcp/** - MCP stdio client/server and tool adapter. Security boundary rejects workspace-root escape, bounds result limits.
- **plugins/** - Plugin discovery/execution with trust model. Remote installation disabled by default.
- **skills/** - Skill definitions with `SKILL.md` format and `SkillRegistry`.
- **evolution/** - 20 submodules: tool_forge, skill_forge, plugin_forge, memory_forge, knowledge_forge, logs, status, ledger, nudge, intent, self_improvement, sop, ensemble, version, local_trainer, omni_kernel, hyper_kernel, researcher, curator, horizons.
- **voice/** - Voice mode (whisper.cpp ggml-tiny-q5_1.bin + KittenTTS Nano int8)

## Event Flow

1. User sends input to any surface
2. `NexusLoop.stream_run()` processes input through the model
3. Loop emits structured work events via `work_event_sink` callback
4. Events are validated through `CanonicalEvent.from_work_event()` in `nexus/events.py`
5. Events are persisted to `workspace/work_events/<session>.jsonl`
6. SSE stream multiplexes events to connected clients
7. GUI and TUI render public events

## Key Dependencies

- Python: FastAPI, uvicorn, aiohttp, httpx, rich, pyyaml, python-dotenv, numpy, faiss-cpu, sentence-transformers, psutil, cryptography
- GUI: React 18.3.1, Vite 5.3.3, TypeScript 5.5.3, Tailwind, Framer Motion, Lucide React (TUI uses React 19 + Ink 7)
- Voice: torch, transformers, sounddevice, pywhispercpp, KittenTTS
- Optional: playwright (browser), opencv-python + mediapipe (vision)
