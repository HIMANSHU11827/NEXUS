# NEXUS Architecture

For the next target architecture that unifies terminal, CLI, GUI, gateway,
voice, browser, memory, tools, mission timelines, and visual
workflows, see
[`docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md`](NEXUS_UNIFIED_AGENT_ARCHITECTURE.md)
and [`docs/NEXUS_WORKFLOW_MODEL.md`](NEXUS_WORKFLOW_MODEL.md).

NEXUS is a local-first autonomous agent platform organized around these package directories:

### Core Runtime
- `orchestrators/loop.py`: primary reasoning loop (7-state sovereign cognitive loop: GROUNDING → PLANNING → INFERENCE → AUDITING → EXECUTION → VERIFICATION → EVOLVE), tool extraction, prompt assembly, memory sync, and self-correction hooks.
- `kernel/`: singleton runtime, workspace ownership, shared module cache, stats, and boot health.
- `nexus/` and `shell/`: **Terminal** — live operator shell package with direct `NexusLoop` access.

### Tools & Sandbox
- `tools/<name>/`: executable capability layer — 10 tools under `tools/` (bash, code_search, file_ops, knowledge, mcp, memory, reasoning, system, task, web_search). Each tool has its own folder with `<name>.jsnol` (version metadata), `scripts/` (implementation), and `<name>.md` (docs).
- `sandbox/`: direct-execution safety, risk scoring (`CommandRiskScorer`), and failure memory via `SovereignSandbox`.
- `safety/`: safety laws, prover engine, and policy evaluation.

### Evolution & Self-Improvement
- `evolution/`: 18 submodules in per-folder format — `tool_forge/`, `skill_forge/` (includes `SkillSynthesizer`), `plugin_forge/`, `memory_forge/`, `knowledge_forge/`, `logs/`, `status/`, `ledger/`, `nudge/`, `intent/`, `self_improvement/`, `sop/`, `ensemble/`, `version/`. Each has `<name>.jsnol`, `scripts/`, and `<name>.md`. Auto-version tracking via `VersionManager` across all 39 modules.

### Memory & Knowledge
- `memory/`: persistent JSON-based memory storage (per artifact).
- `knowledge/`: knowledge store with RAG index files.
- `rag/`: retrieval layer — BM25 + hybrid vector retrieval with Atlas deep indexing.
- `context/`: context persistence and compression (`NexusContextCompressor`).

### Reasoning & Planning
- `reasoning/`: hyper reasoning engine for planner/critic/verifier workflows with uncertainty and replan triggers.
- `router/`: intent router — multi-signal intent classification with confidence scoring.

### Providers
- `providers/`: 35+ model providers (OpenAI, Anthropic, Groq, Gemini, Ollama, DeepSeek, Mistral, etc.) with health telemetry, capability registry, and fallback routing.

### User Surfaces
- `cli/`: **CLI** — TypeScript Ink UI (API thin client; not the live terminal).
- `gui/`: **GUI** — FastAPI backend and React operator surface.
- `gateway/`: **Gateway** — Telegram, Discord, WhatsApp, and other external channels.

### Support
- `config/`: YAML configuration (provider.yml, settings.yml, system.yml) loaded by `config_loader.py`.
- `prompts/`: `NexusPromptEngine` — token-efficient dynamic prompt builder.
- `security/`: lightweight release hygiene checks, secret scanner.
- `permissions/`: permission policy definitions.
- `lifecycle/`: lifecycle management hooks.
- `tasks/`: task scheduler.
- `skills/`: skill definitions and `NexusSkillMaster` singleton.
- `plugins/`: plugin system (early stage).
- `utils/`: utilities (logger, encryption, compression, math, token counter).
- `mcp/`: MCP stdio server for code graph (Claude/Cursor/Windsurf-style).
- `voice/`: voice mode (whisper.cpp `ggml-tiny-q5_1.bin` + KittenTTS Nano int8).
- `tests/`: test suites (42 passing, 3 pre-existing failures).

## Four User Surfaces

Users can send missions from **any** of the four surfaces above. All normalize into the
same agent runtime (`orchestrators/loop.py`). Terminal is the only surface that runs the
loop in-process; CLI and GUI call `gui` API; gateway routes through `gateway`.

### Internally connected

All four surfaces share one linked session via `session_bus/`:

- `workspace/active_session.json` — which session is live right now
- `logs/sessions/{session_id}.json` — conversation memory
- `workspace/work_events/{session_id}.jsonl` — mission timeline

Chat in GUI → terminal auto-joins on start; CLI/GUI poll `/api/sessions/active` every 5s. Use `/session <id>` or `/events` to switch or inspect manually.

## Operating Model

NEXUS is designed for fast direct execution. It avoids approval spam by default and instead uses deterministic guardrails:

1. Score command risk before execution.
2. Block clearly destructive commands unless explicitly enabled.
3. Keep path writes inside the project root.
4. Store failures for later self-correction.
5. Build a repo map before reasoning so the agent starts with project structure.
6. Verify work through tests, compile checks, and gui builds.
7. Store durable memory as ranked graph nodes and inject compact context packets instead of raw history.
8. Convert failures into reusable strategies and future regression candidates.
9. Predict edit blast radius before multi-file changes.
10. Use rollback/process primitives for long-running or risky OS work.
11. Route providers by health and capability instead of static wishful status.
12. Treat provider error strings as failures so fallback can continue.
13. Run diagnostics and edit planning before risky code changes.
14. Record tool execution in mission replay and tool economy ledgers.
15. Select targeted tests from edit plans, imports, and related test files.
16. Convert concrete failures into reusable strategies, memory rules, and regression plans.

## Honest Capability Boundary

- Swarm is now a real local orchestrator, but it does not yet run independent LLM brains per role by default.
- World modeling is deterministic impact analysis, not a physical simulator.
- Provider health tracks latency/errors, validates keys, routes by capability, and falls back on provider failures. Deep network probes are intentionally bounded to avoid slow startup.
- RAG supports persistent BM25 and hybrid result blending, including cleanup of stale keyword/vector entries. Production vector storage and graph retrieval remain roadmap items.
- Cognition primitives are local deterministic foundations; they are not yet a learned memory optimizer.
- gui state is config-derived and local-first, not a multi-tenant admin service.

## Current Reliability Boundary

The current system is powerful but still experimental. It should be treated as a local development agent, not a hosted multi-tenant service. Stronger gui authentication UX, sandboxed process isolation, role-specific LLM swarm workers, and benchmark-driven improvement are the next production gates.
