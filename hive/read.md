# Hive (Sub-Agent Engine)

Multi-agent sub-engine for parallel task decomposition and execution.

**Version:** 2.0.0

## Components
- `engine.py` — `NexusHiveEngine`: spawn_agent, spawn_hive, consolidate_hive, cancel_hive, blackboard, live signals
- `SubAgent` — isolated LLM call with `subagent.*` event emission
- 5 built-in personas: RESEARCHER, ENGINEER, REVIEWER, PLANNER, TESTER
- Fallback LLM chain: MoE router → provider factory → openai localhost

## Features
- Parallel agent spawning with asyncio.gather
- Blackboard for cross-agent data sharing
- Configurable timeout per hive (default 120s)
- Extracts changed files from agent artifacts via regex
- Full event lifecycle: subagent.started → subagent.status → subagent.result → subagent.completed
