# Hive (Sub-Agent Engine)

Multi-agent sub-engine for parallel task decomposition and execution.

**Version:** 2.0.0

## Components
- `engine.py` — `NexusHiveEngine`: spawn_agent, spawn_hive, consolidate_hive with optional quorum policy, cancel_hive, durable pause/resume controls, stale-agent recovery, blackboard, live signals
- `state.py` — SQLite-backed blackboard versions and artifact fingerprints with restart-safe reconciliation
- `SubAgent` — isolated LLM call with `subagent.*` event emission
- 5 built-in personas: RESEARCHER, ENGINEER, REVIEWER, PLANNER, TESTER
- Fallback LLM chain: MoE router → provider factory → openai localhost

## Features
- Parallel agent spawning with asyncio.gather
- Blackboard for cross-agent data sharing
- Configurable timeout per hive (default 30s)
- Extracts changed files from agent artifacts via regex
- Full event lifecycle: subagent.started → subagent.progress → subagent.result → subagent.completed / subagent.failed
