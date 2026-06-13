# NEXUS AI

NEXUS AI is a local-first autonomous engineering agent platform. It is built to understand a codebase, execute tools directly, repair failures, remember project history, and operate through both a terminal-first workflow and a visual gui.

The project is not trying to be a chatbot with plugins. It is trying to become an operator-grade AI development system: fast command execution, codebase awareness, durable memory, multi-model routing, autonomous workflows, and a control surface for long-running engineering work.

## Core Capabilities

- Unified Python agent loop with streaming responses and tool execution.
- Direct shell/file/search tools with deterministic risk scoring.
- Repo map and lightweight symbol graph for codebase understanding.
- Persistent BM25 RAG plus hybrid keyword/vector result blending for project recall.
- Persistent failure memory for self-correction and regression prevention.
- Four user surfaces — terminal, CLI, GUI, gateway — all feeding one agent runtime.
- FastAPI GUI API and React operator GUI.
- TypeScript Ink CLI (API thin client; not the live terminal).
- Multi-provider model routing, provider health telemetry, and local model experiments.
- Capability-aware provider fallback with normalized provider error handling.
- Environment-variable provider secrets and a repository secret scanner.
- Local Hive orchestration with task queues, role planning, retries, cancellation, artifacts, and result merging.
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

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
The target unified agent architecture is defined in
[docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md](docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md),
with the mission workflow model in
[docs/NEXUS_WORKFLOW_MODEL.md](docs/NEXUS_WORKFLOW_MODEL.md).

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md).
Current audited completion status lives in [docs/ROADMAP_STATUS.md](docs/ROADMAP_STATUS.md).

For the long-range next-generation architecture and invention backlog, see
[docs/NEXUS_OPTIMIZATION_NEXTGEN_BLUEPRINT.md](docs/NEXUS_OPTIMIZATION_NEXTGEN_BLUEPRINT.md).

For MCP code graph setup, see [docs/MCP_CODE_GRAPH.md](docs/MCP_CODE_GRAPH.md).

For generated coding-agent context files, see [docs/AGENT_CONTEXT.md](docs/AGENT_CONTEXT.md).

For the consolidated runtime/code/memory graph, see [docs/UNIFIED_GRAPH.md](docs/UNIFIED_GRAPH.md).

- For local microphone/speaker voice mode with local Distil-Whisper and KittenTTS Micro (40M), see
[docs/VOICE_ASSISTANT.md](docs/VOICE_ASSISTANT.md).

## Engineering Directive

NEXUS carries a durable repair directive for weak/fake systems in [docs/SPECIAL_FOCUS.md](docs/SPECIAL_FOCUS.md). The prompt engine loads this directive so future agent runs keep pressure on Hive orchestration, world modeling, command safety, providers, RAG, tests, packaging, and gui security.

## User Surfaces

A user can send a mission from **any** of these four surfaces:

| Surface | Start | Path |
|---------|-------|------|
| **Terminal** (live) | `python -m nexus` | `nexus/` package |
| **CLI** (Ink client) | `cd cli && npm start` | `cli/` — needs API on `:8000` |
| **GUI** | `cd gui && python -m server` | `gui/`, `server/` package |
| **Gateway** | `python -m gateway.main` | `gateway/` — Telegram, Discord, WA |

Terminal is the real in-process operator. CLI is **not** the terminal — it is an Ink UI over the API.

All four surfaces are **internally connected** via `session_bus/`: one active `session_id`, shared chat history (`logs/sessions/`), and mission timelines (`workspace/work_events/`). Chat in GUI → terminal or CLI auto-join the same session and can continue without re-sending.

## Quick Start

```powershell
python -m pip install -e .
python -m nexus
```

Provider keys are loaded from environment variables. Do not commit raw API keys:

```powershell
$env:OPENROUTER_API_KEY="..."
$env:QWEN_API_KEY="..."
```

GUI:

```powershell
cd gui
npm install
npm run build
python -m server
```

CLI (requires GUI API running):

```powershell
cd cli
npm install
npm start
```

Gateway:

```powershell
python -m gateway.main
```

Voice mode:

```powershell
python -m pip install -e ".[voice]"
python -m voice_chat --warmup
```

## Verification

```powershell
python -m compileall -q assets config_loader discovery indexer kernel nexus_compat nexus_path observer permissions router session_bus skills stream_filters tool_adapters world_model server nexus shell voice_chat prompts neural authentication sandbox code_intel optimization
python tests\test_sandbox.py
python tests\test_cognition.py
python tests\test_hardening.py
python tests\test_nextgen_power.py
python tests\test_advanced_tools.py
python tests\test_gui_security.py
python tests\test_provider_routing.py
python tests\test_secret_scanner.py
python tests\test_core.py
python tests\test_unified_loop.py
python tests\test_genesis.py
cd gui
npm run build
```

Benchmark gate:

```powershell
python -c "from tools.nexus_tools.registry import ToolRegistry; print(ToolRegistry().execute('benchmark', command='run', compress=False))"
```

## Current Status

NEXUS is an advanced prototype, not a production service yet. The core loop, tools, adaptive memory graph, zero-token context packets, RAG, gui, repo map, risk scorer, Hive orchestrator, world model, self-improvement store, intent forecaster, skill forge, and model provider layers exist. Several systems remain experimental: long-task durability, sandboxing, role-specific LLM agents, and benchmark-driven training.
