# NEXUS AI

NEXUS AI is an autonomous AI agent platform and multi-agent runtime. It is local-first but **provider-agnostic — not local-only**: it runs on local models (Ollama, LM Studio, llama.cpp), cloud APIs (OpenAI, Anthropic, Gemini, DeepSeek, and 20+ other vendors), and authenticated (OAuth) providers (Claude, Codex, Copilot, Gemini, Grok, OpenRouter, Qwen, MiniMax, Chutes, OpenCode CLI). It is built to understand a codebase, execute tools directly, repair failures, remember project history, and operate through both a terminal-first workflow and a visual GUI. Its built-in **Hive** engine provides full multi-agent orchestration — parallel, sequential, specialist, sub, and team agents.

The project is not trying to be a chatbot with plugins. It is trying to become an operator-grade AI development and orchestration system: fast command execution, codebase awareness, durable memory, multi-model routing, autonomous multi-agent workflows, and a control surface for long-running engineering work.

## Core Capabilities

- Unified Python agent loop with streaming responses and tool execution.
- Direct shell/file/search tools with deterministic risk scoring.
- Repo map and lightweight symbol graph for codebase understanding.
- Persistent BM25 RAG plus hybrid keyword/vector result blending for project recall.
- Persistent failure memory for self-correction and regression prevention.
- Three primary interfaces â€” TUI, GUI, Gateway â€” all feeding one agent runtime.
- FastAPI GUI API and React operator GUI.
- TypeScript Ink TUI (API thin client; not the live terminal).
- Multi-provider model routing, provider health telemetry, and local model experiments.
- Capability-aware provider fallback with normalized provider error handling.
- Environment-variable provider secrets and a repository secret scanner.
- Local-first **Hive** multi-agent orchestration with task queues, role planning, retries, cancellation, artifacts, and result merging. Hive supports five agent types: **parallel** (concurrent hive, bounded by `NEXUS_HIVE_MAX_CONCURRENCY`), **sequential** (staged execution plan), **specialist** (specialization registry), **sub** (isolated persona sub-agent emitting `subagent.*` events), and **team** (reusable `AgentTeamSpec`).
- Hive agent contracts, scoped handoff packets, and checkpoints to reduce subagent forgetting and role drift.
- Deterministic world-model impact analysis for command/file actions.
- Adaptive memory graph with ranking, contradiction repair, cleanup, and compressed context packets.
- Zero-token context packets that preserve pointer IDs instead of replaying raw history.
- Self-improvement strategy store that converts failures and wins into reusable tactics.
- Intent forecasting for likely next tests, security checks, and repo refresh work.
- Skill Forge for safe reusable workflow/macro definitions.
- Hyper Reasoning Engine for explicit planner/critic/verifier workflows with uncertainty and replan triggers.
- Rollback and process-management primitives for real OS control.
- Side-effect analyzer for cross-file edit blast-radius prediction.
- Diagnostics runner for Python/JSON/YAML validation and gui build checks.
- Symbol-aware edit planner that reports symbols, imports, impacted files, and recommended checks before edits.
- Targeted test selector for changed-file verification planning.
- Failure vaccine engine that turns failures into memory rules, reusable strategies, and regression plans.
- MCP stdio code graph server for Claude/Cursor/Windsurf-style clients.
- Code-graph-backed `NEXUS.md` generation for repository-level coding-agent context.
- Unified NEXUS graph that connects code, memory, evidence, mission/session events, tool metrics, and benchmark history.
- First-class NEXUS tools for rollback, patch ledger, process management, side-effect analysis, hyper-planning, cognition, and skill forging.
- Local self-benchmark runner with persistent score history.
- gui security hardening for local-only mode, upload/session sanitization, rate limits, and honest provider status.
- gui audit control plane for unified graph status, roadmap progress, evidence, mission replay, and tool economy.
- Experimental training and self-improvement systems.
- MediaPipe Holistic Vision integration (543 landmarks tracking for face, body, and hands); full MediaPipe suite status is documented in `docs/MEDIAPIPE_SUITE.md`.
- **NATE-Route**: Zero-training embedding-based tool router (all-MiniLM-L6-v2 + FAISS). 88% schema token reduction, 67% input token savings. Solves all 12 skill alignment problems. See `docs/NATE.md`.
- **Self-Improving Lifecycle**: `evolution/local_trainer/` â€” auto harvests tool logs, fine-tunes embedding + Zupra-50M models, exports to GGUF, reloads into NATE. Self-improving cycle improves routing + local inference over time.
- **Zupra Local Provider**: `models/providers/api/zupra.py` â€” MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp for fully offline CPU inference. No API key needed. Registered as "zupra" in provider factory.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The target unified agent architecture is defined in
[docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md](docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md),
with the mission workflow model in
[workflows/NEXUS_WORKFLOW_MODEL.md](workflows/NEXUS_WORKFLOW_MODEL.md).

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md).
Current audited completion status lives in [docs/ROADMAP_STATUS.md](docs/ROADMAP_STATUS.md).

For the long-range next-generation architecture and invention backlog, see
[docs/NEXUS_OPTIMIZATION_NEXTGEN_BLUEPRINT.md](docs/NEXUS_OPTIMIZATION_NEXTGEN_BLUEPRINT.md).

For MCP code graph setup, see [docs/MCP_CODE_GRAPH.md](docs/MCP_CODE_GRAPH.md).

For generated coding-agent context files, see [docs/AGENT_CONTEXT.md](docs/AGENT_CONTEXT.md).

For the consolidated runtime/code/memory graph, see [docs/UNIFIED_GRAPH.md](docs/UNIFIED_GRAPH.md).

- For local microphone/speaker voice mode with whisper.cpp `ggml-tiny-q5_1.bin` and KittenTTS Nano int8, see
[docs/VOICE_ASSISTANT.md](docs/VOICE_ASSISTANT.md).

## Engineering Directive

NEXUS carries a durable repair directive for weak/fake systems in [docs/SPECIAL_FOCUS.md](docs/SPECIAL_FOCUS.md). The prompt engine loads this directive so future agent runs keep pressure on Hive orchestration, world modeling, command safety, providers, RAG, tests, packaging, and gui security.

## User Surfaces

A user can send a mission from **any** of these three interfaces:

| Interface | Start | Path |
|-----------|-------|------|
| **TUI** (Ink client) | `nexus` | `apps/tui/` + `apps.web.api` backend on `:8000` |
| **GUI** | `nexus --gui` | React app + `apps.web.api` backend |
| **Server** | `nexus --server` | standalone `apps.api:app` API |
| Gateway | `nexus --gateway` | `gateways/` — Telegram, Discord, WhatsApp, Slack, SMS (Twilio) |

TUI is **not** the terminal (host environment) — it is an Ink UI over the API.

All interfaces are **internally connected** via `src/nexus/common/session_bus.py`: one active `session_id`, shared chat history (`.nexus/logs/sessions/`), and mission timelines (`.nexus/workspace/work_events/`). Chat in GUI or TUI auto-join the same session and can continue without re-sending.

## Quick Start

```powershell
# First-time setup (uv is required; Python 3.12+)
uv sync                      # creates .venv + installs NEXUS and all deps
nexus --setup               # optional setup wizard

# Start an interface
nexus                       # TUI (default)
nexus --gui                 # GUI
nexus --server              # API server only
nexus --gateway             # multi-platform gateway
```

Provider keys are loaded from environment variables (or `configure/.env`). Do not commit raw API keys:

```powershell
$env:OPENROUTER_API_KEY="..."
$env:QWEN_API_KEY="..."
```

GUI:

```powershell
nexus --gui
```

TUI:

```powershell
nexus
```

Gateway:

```powershell
nexus --gateway
```

Voice mode:

```powershell
uv sync --extra voice
nexus-voice --warmup
```

## Verification

```powershell
uv run pytest tests/ -v --tb=short
cd apps/tui && pnpm install && pnpm build && pnpm test
cd apps/web && pnpm install && pnpm build
```

Version integrity:

```powershell
uv run python -c "from versioning.version.scripts.version import VersionManager; vm=VersionManager('.'); print(vm.get_all_versions_report())"
```

## Current Status

NEXUS is an advanced prototype, not a production service yet. The core loop, tools, adaptive memory graph, zero-token context packets, RAG, gui, repo map, risk scorer, Hive orchestrator, world model, self-improvement store, intent forecaster, skill forge, and model provider layers exist. The evolution system is fully restructured into per-module folders with auto-version tracking across all 67 modules via `VersionManager`. Several systems remain experimental: long-task durability, sandboxing, role-specific LLM agents, and benchmark-driven training.
