# NEXUS Architecture

NEXUS is a local-first autonomous agent platform organized around a small set of durable cores:

- `core/kernel.py`: singleton runtime, workspace ownership, shared module cache, stats, and boot health.
- `orchestrators/loop.py`: primary reasoning loop, tool extraction, tool execution, prompt assembly, memory sync, and self-correction hooks.
- `tools/nexus_tools/`: executable capability layer for shell, files, search, memory, providers, audits, and automation.
- `rag/`: retrieval layer for project memory and source recall.
- `core/code_intelligence/`: static repo map, diagnostics, edit planning, side-effect analysis, and symbol graph primitives.
- `core/autonomy/`: direct-execution safety, risk scoring, and failure memory.
- `core/cognition/`: adaptive memory graph, zero-token context packets, self-improvement strategies, intent forecasting, and skill forge.
- `core/reasoning/`: explicit planner/critic/verifier primitives with uncertainty and replan triggers.
- `core/os_power/`: rollback snapshots and managed background processes.
- `core/aurora/`: mission replay, tool economy, targeted test selection, and failure vaccines for the next-generation runtime.
- `core/providers/`: provider factory, health telemetry, capability registry, and fallback routing.
- `core/security/`: lightweight release hygiene checks such as secret scanning.
- `core/world_model.py`: deterministic action impact simulation for risk, reversibility, and safeguards.
- `core/swarm.py`: local multi-agent orchestration with planning, queues, retries, cancellation, artifacts, and result consolidation.
- `dashboard/`: FastAPI backend and React operator surface.
- `cli/`: TypeScript Ink interface.

## Operating Model

NEXUS is designed for fast direct execution. It avoids approval spam by default and instead uses deterministic guardrails:

1. Score command risk before execution.
2. Block clearly destructive commands unless explicitly enabled.
3. Keep path writes inside the project root.
4. Store failures for later self-correction.
5. Build a repo map before reasoning so the agent starts with project structure.
6. Verify work through tests, compile checks, and dashboard builds.
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
- Dashboard state is config-derived and local-first, not a multi-tenant admin service.

## Current Reliability Boundary

The current system is powerful but still experimental. It should be treated as a local development agent, not a hosted multi-tenant service. Stronger dashboard authentication UX, sandboxed process isolation, role-specific LLM swarm workers, and benchmark-driven improvement are the next production gates.
