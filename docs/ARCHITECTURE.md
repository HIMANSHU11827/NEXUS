# Architecture

Nexus AI is a local-first autonomous AI agent framework with a Python backend and multiple frontends. This document reflects the **post-restructuring** layout (see `docs/MIGRATION.md`).

## Core Runtime

- **src/nexus/** — Boot loader (`boot()` function). Entry point for `python -m nexus`, `--setup`, `--server`, `--gui`, `--shell`, `--tui`. Default route launches the Ink TUI and starts the canonical `apps.api:app` API when needed.
- **src/nexus/events.py** — Canonical event system with ~50 event types (run, conversation, message, plan, tool, command, file, search, web, test, subagent lifecycle). Events flow via `work_event_sink` callback and stream to GUI via SSE.
- **src/nexus/main_agent/core.py** — V5 `NexusLoop` — the main agent loop. The live path uses the transcript-driven direct model/tool loop, registry discovery, memory, provider routing, and canonical event emission.
- **src/nexus/runtime/kernel/** — Central singleton with lazy-loaded subsystems, workspace ownership, shared module cache, and health stats.
- **src/nexus/command_system/** — Central command system (`CommandRegistry` singleton in `src/nexus/commands.py`). One registry shared by CLI, TUI, GUI, API, gateways, Hive, workflows, and automation. Every command resolves to exactly one handler.

## Applications (apps/)

Each app is a thin surface that builds `CommandRequest`/uses the command bus and renders `CommandResult`. No command business logic lives in the apps.

- **apps/api/** — FastAPI HTTP/SSE server (`apps.api:app`) on port 8000. Chat (`/api/chat`), sessions, history, resource listing (`/api/tools`, `/api/skills`, `/api/agents`, `/api/plugins`, `/api/mcp`, `/api/providers`), management (`/api/manage`), health (`/api/health`), and OpenAI-compatible `/v1/models`, `/v1/chat/completions`.
- **apps/tui/** — Ink + `apps.web` backend TUI.
- **apps/web/** — React 18 + Vite GUI frontend (`apps.web`); its own FastAPI `apps.web.api` (`apps.web.api.py`) is the GUI backend.
- **apps/gateway/** — **Dedicated Gateway application** (`apps.gateway.nexus_gateway_app`). Discovers enabled gateways (env-gated), supervises connections, reconnects with backoff, routes inbound messages into the central command bus when a matching command is registered, and shuts down gracefully. The gateway engine lives in `gateways/`.
- The legacy `server/`, `tui/`, `gui/` root packages were moved to `apps/api/`, `apps/tui/`, and `apps/web/`.

## Providers (distinct categories — mandate §2.13)

Implementation lives under **models/providers/**, split into three mutually distinct categories:

- **models/providers/local/** — Local / self-hosted runtimes: `ollama`, `llama_cpp`, `lm_studio`, `lm_studio_auto`, `sandbox_interpreter`.
- **models/providers/api/** — API-key providers: `openai`, `anthropic`, `google_gemini`, `deepseek`, `groq`, `mistral`, `cohere`, `perplexity`, `together`, `fireworks`, `xai`, `openrouter`, `huggingface`, `nvidia`, `qwen`, `replicate`, `sambanova`, `azure_openai`, `commandcode`, `zupra`.
- **models/providers/auth/** — Account-authenticated providers: `opencode_cli`.
- **models/providers/core/** — Shared provider machinery: `base`, `factory` (`NexusProviderFactory`), `router` (capability-aware fallback), `profiles`, `auto_detect`, `auto_heal`, `health`, `model_capabilities`, `universal`, `langchain_provider`, `vlm`, `flux_image`, plus reliability/telemetry helpers.

Provider settings stay in **configure/providers/{local,api,auth}/**; secrets are loaded via the Secret Manager, never stored in config files.

## Tools (extensions/tools/built_in/)

Registry-discovered tools, each a flat named directory: `code_search/`, `creating/`, `deep_research/`, `deleting/`, `git_ops/`, `hive/`, `knowledge/`, `memory/`, `modifying/`, `planning/`, `reading/`, `reasoning/`, `shortcuts/`, `system/`, `task/`, `terminal/`, `test_runner/`, `web_search/`. Planning is a **tool** (`extensions/tools/built_in/planning/`), not `src/nexus/planning/` (mandate §2.3).

## Extension Systems

- **extensions/mcp/core/** — MCP stdio client/server and tool adapter (security boundary rejects workspace-root escape, bounds result limits).
- **extensions/plugins/built_in/** — Plugin discovery/execution with trust model.
- **extensions/skills/built_in/** — Skills as `SKILL.md` packages with `SkillRegistry`.
- **evolution/** — Tool/skill/plugin/memory forges, ledger, SOP, ensemble, versioning, local trainer, self-improvement.

## Hive

- **hive/** — Multi-agent orchestration engine. Hive is a capability **owned by the main agent** (mandate §2.2); the main agent is never inside Hive. Supports delegation, agent teams, parallel/sequential agents, result merging, partial-result recovery, and agent health/replacement.

## Gateways (gateways/)

Engine package with `GatewaySupervisor` (discovery, health supervision, reconnect-with-backoff, crash-loop cooldown, lifecycle state persistence), `GatewayRunner` (connect/disconnect + delivery loop), platform adapters (telegram, discord, slack, signal, whatsapp, …), and `webhook_server.py`. The dedicated app `apps/gateway/` supervises it.

## Memory, Knowledge, RAG, Context

- **memory/** — Multi-source `MemoryManager` (JSONL + in-memory hybrid) with parallel prefetch/sync and verified-evidence gating.
- **knowledge/rag/** — BM25 + hybrid vector retrieval with Atlas deep indexing.
- **knowledge/** — Knowledge store with SQLite index and RAG index files.
- **src/nexus/context/** — Context persistence and compression (`NexusContextCompressor`).

## Cross-cutting systems

- **configure/** — Root configuration (was `config/`). `nexus.config.json`, `permissions.json`, `feature-flags.json` at repo root; config precedence: built-in → environment → project → user → profile → explicit → env vars → runtime.
- **security/** — Secret scanner + permission/sandbox enforcement.
- **security/permissions/** — Permission modes (auto, plan, acceptEdits, dontAsk, bypass, approve).
- **sandbox/** — `CommandRiskScorer` (NO_SANDBOX / NORMAL / DOCKER).
- **security/policies/** — Safety laws and policy evaluation.
- **src/nexus/lifecycle/** — Lifecycle hooks (tool, skill, plugin, memory, cron, self-improvement).
- **src/nexus/tasks/** — Task scheduler.
- **observability/telemetry/** — SQLite telemetry.
- **src/nexus/capabilities/reasoning/** — Hyper-reasoning engine for planner/critic/verifier.
- **src/nexus/capabilities/router.py** — Intent router for multi-signal intent classification.
- **reliability/**, **learning/**, **evaluation/**, **governance/**, **maintenance/**, **observability/** — autonomous-systems subsystems.

## Event Flow

1. User sends input to any surface (CLI / TUI / GUI / API / gateway).
2. `NexusLoop.stream_run()` processes input through the model.
3. Loop emits structured work events via `work_event_sink` callback.
4. Events validated through `CanonicalEvent.from_work_event()` in `src/nexus/events.py`.
5. Events persisted to `.nexus/workspace/work_events/<session>.jsonl`.
6. SSE stream multiplexes events to connected clients; GUI and TUI render public events.

## Startup / Shutdown

- Startup: load env → resolve paths → load+validate config → init security/secret manager/logging → validate dirs → acquire locks → init Nexus Core + Lifecycle Manager → load registries → discover components → init command bus → load enabled tools/skills/plugins → connect MCP → load models/providers → init memory/workflows/queues/automation/hive/gateways → init learning/eval/evolution/maintenance → start main agent + health/recovery/maintenance/learning/evolution loops → mark healthy.
- Shutdown: mark stopping → stop unsafe new work → allow safe work to finish → save goals/plans/tasks → write checkpoints → flush memory/queues → stop learning/evolution writes → disconnect gateways → stop Hive/workflows/plugins/MCP/providers → stop command bus → flush logs/metrics → release locks → mark stopped.

## Key Dependencies

- Python: FastAPI, uvicorn, aiohttp, httpx, rich, pyyaml, python-dotenv, numpy, faiss-cpu, sentence-transformers, psutil, cryptography.
- GUI: React 18.3.1, Vite 5.3.3, TypeScript 5.5.3, Tailwind, Framer Motion, Lucide React (TUI uses React 19 + Ink 7).
- Voice: torch, transformers, sounddevice, pywhispercpp, KittenTTS.
- Optional: playwright (browser), opencv-python + mediapipe (vision).
