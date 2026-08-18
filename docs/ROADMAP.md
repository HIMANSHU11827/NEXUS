# NEXUS Roadmap

See `docs/NEXUS_OPTIMIZATION_NEXTGEN_BLUEPRINT.md` for the broader research-backed
next-generation architecture and invention backlog.

See `docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md` and
`workflows/NEXUS_WORKFLOW_MODEL.md` for the unified mission runtime and workflow
model that combines TUI, GUI, Gateway, memory, tools, and visual
agent timelines into one system.

For the current evidence-backed completion status, see
`docs/ROADMAP_STATUS.md`.

## Phase 1: Hard Reliable Coding Agent

- Git-aware patch ledger with automatic revert points.
- Repo map cache with incremental updates.
- LSP diagnostics integration.
- Test-fix loop with failure memory.
- Tool result contracts and structured observations.
- Deterministic command risk policy.
- Provider latency registry, health status API, and fallback tuning.
- gui request audit viewer.

## Phase 2: Next-Gen Memory

- Hybrid BM25 + vector retrieval.
- Timeline memory with decay and importance ranking.
- Project knowledge graph linking files, symbols, tests, failures, and decisions.
- Memory cleanup jobs to remove stale or low-value facts.
- Retrieval regression set for project-specific memory.
- Promote adaptive memory graph into a hybrid graph/vector store.
- Add contradiction review UI and memory provenance browser.

## Phase 3: Autonomous Workflows

- Background job manager.
- Long-task checkpointing and resume.
- Multi-agent task economy with explicit artifacts.
- Role-specific LLM execution adapters for swarm tasks.
- Predictive debugging from historical failures.
- Benchmark trainer that turns failures into regression tests.
- Self-improvement loop that proposes prompt/tool/test changes and requires verification before persistence.

## Phase 4: Product Platform

- Authenticated gui.
- Profiles for coding, research, automation, architecture, and bug hunt.
- MCP-compatible tool/plugin SDK.
- Provider health checks and fallback router.
- CI template and release packaging.

## Phase 5: Moat

Build the best local-first autonomous engineering operating system: fast direct execution, deep project memory, repo consciousness, safe-by-design command power, and an operator-grade gui.

### Achieved this session
- **NATE-Route**: Embedding-based tool router (all-MiniLM-L6-v2 + FAISS). 88% schema reduction, 67% token savings, 100% accuracy. Solves all 12 skill alignment problems at once with zero training.
- **Self-Improving Lifecycle**: `evolution/local_trainer/` — auto harvests tool call logs → fine-tunes embedding + Zupra-50M → exports to GGUF → reloads into NATE. Runs autonomously on schedule.
- **Zupra-50M Local Brain**: `models/providers/api/zupra.py` — MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp for fully offline CPU inference. No API key needed. Registered in provider factory.
- **Lifecycle data pipeline**: `training_data/harvest/` collects structured JSONL from every tool call, routing decision, and OATS feedback event. Auto-triggers fine-tune at configurable thresholds.
