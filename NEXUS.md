# NEXUS AI Claude Context

This file is generated from the local NEXUS code graph. Keep it concise, factual, and easy for coding agents to obey.

## Project Identity

- NEXUS AI is a local-first autonomous engineering agent platform for direct system control, coding workflows, RAG, memory, provider routing, tools, and gui operations.
- The product direction is fast autonomous execution with intelligent safeguards: command risk scoring, rollback, evidence logging, diagnostics, and recovery instead of approval friction.
- Treat claims as untrusted until backed by source code, tests, command output, or persisted evidence.

## Four User Surfaces

Users can send work from **any** of these four channels; all feed the same agent core (`orchestrators/loop.py`):

| Surface | Entry | Notes |
|---------|-------|-------|
| **Terminal** | `python -m nexus` → `shell` package | Live in-process runtime. **Not** the Ink CLI. |
| **CLI** | `cli/nexus-cli.tsx` | Ink thin client; needs API on port 8000. |
| **GUI** | `python -m server` + `gui/src/App.tsx` | Visual mission cockpit. |
| **Gateway** | `gateway/` | Telegram, Discord, WhatsApp, Meta webhooks. |

Do not conflate **terminal** with **CLI** (`cli/`). Terminal is the real live operator.

## Internally Connected Surfaces

All four surfaces share **one linked session**. Chat in GUI → open terminal or CLI → continue the same conversation without re-sending.

| Store | Path |
|-------|------|
| Active session pointer | `workspace/active_session.json` |
| Session memory | `logs/sessions/{session_id}.json` |
| Work events | `workspace/work_events/{session_id}.jsonl` |

- Switching session on any surface updates `active_session.json` for all others.
- Terminal reloads disk memory before each reply (`sync_memory`).
- CLI/GUI poll `/api/sessions/active` every 5s.
- Gateway writes to `gateway_{platform}_{chat_id}` sessions on the same bus.

Terminal: auto-joins active session on start; `/session <id>`, `/events`. CLI: `/session <id>`, `/events`. GUI: session picker + live sync.

## Architecture Snapshot

*This snapshot comes from `workspace/code_graph.json`; refresh it with `code_graph build` or `nexus-mcp` graph tools after meaningful code changes.*

- Graph nodes: 2232
- Graph edges: 10010
- Node kinds: class=283, file=260, function=388, method=1123, module=178
- Edge kinds: calls=7010, defines=1794, imports=1074, inherits=132
- Built at: 2026-04-26 12:19:24

### High-Signal Hubs

* `os` (module, degree=140)
* `typing` (module, degree=138)
* `json` (module, degree=93)
* `tests/test_core.py` (file, degree=78)
* `orchestrators/loop.py` (file, degree=72)
* `gui/src/App.tsx` (file, degree=69)
* `tools/nexus_tools/advanced_power_tool.py` (file, degree=69)
* `time` (module, degree=68)
* `tools/nexus_tools/advanced_power_tool.py` (method, degree=65)
* `orchestrators/loop.py` (method, degree=52)
* `skill/red-teaming/godmode/scripts/parseltongue.py` (file, degree=52)
* `orchestrators/architect.py` (file, degree=50)

## Core Working Areas

- **Package Folders directly in root**: kernel, config_loader, discovery, indexer, nexus_compat, nexus_path, observer, permissions, router, session_bus, skills, stream_filters, tool_adapters, world_model, server, nexus, shell, voice_chat, prompts, neural, authentication, sandbox, code_intel, and optimization.
- `models/local/`: Local model assets for voice, vision, and optional local Transformers models. The primary chat brain currently routes through LM Studio using **qwen3.5-0.8b-uncensored-opus-distill**.
- `tools/nexus_tools/`: tool registry and callable agent tools, including shell, file edit, RAG, graph, unified graph, evidence, rollback, process, diagnostics, and benchmarks.
- `orchestrators/`: planning and execution loops that coordinate agents, tools, prompts, and long-running work.
- `rag/` and `knowledge/`: retrieval, indexing, memory, and knowledge ingestion surfaces.
- `integrations/`: external protocol integrations, including the MCP stdio code graph server.
- `gui/`: frontend/gui experience and API integration.
- `tests/`: regression coverage for core behavior, tools, providers, MCP, safety, and next-gen systems.

## Commands

- Full tests: `python -m pytest -q`
- Targeted next-gen tests: `python -m pytest tests\test_nextgen_power.py -q`
- Compile check: `python -m compileall -q assets config_loader discovery indexer kernel nexus_compat nexus_path observer permissions router session_bus skills stream_filters tool_adapters world_model server nexus shell voice_chat prompts neural authentication sandbox code_intel optimization`
- gui build: `cd gui && npm run build`
- Benchmark: `python -c "from evaluation.benchmark import BenchmarkRunner; import json; print(json.dumps(BenchmarkRunner('.').run(), indent=2))"`
- MCP server: `python -m mcp.server` or installed entry point `nexus-mcp`

## Agent Tooling

- Use `code_graph` before broad edits to search symbols, inspect dependencies, and find dependents without reading giant files.
- Use `unified_graph` to connect code, memory, evidence, mission/session events, tool metrics, benchmarks, todos, strategies, and agent context files.
- Use Hive contracts and handoff packets for delegated work so Hive workers receive scoped objectives, constraints, required outputs, and artifact pointers instead of raw history.
- Use `evidence_ledger` to record important claims with proof, especially after tests, audits, or risky fixes.
- Use `rollback` or `patch_ledger` before high-risk multi-file edits.
- Use `diagnostics`, `test_select`, and full tests to verify behavior after code changes.
- Use `agent_context preview` to inspect this file and `agent_context write` to refresh `NEXUS.md`.

## Sovereign Neural Path

NEXUS uses a multi-tier neural strategy:
- **Primary Sovereign Brain**: `lm_studio/qwen3.5-0.8b-uncensored-opus-distill` (local LM Studio chat model).
- **Speech-to-Text**: `models/local/voice/distil-whisper-large-v3` (local Distil-Whisper model for speech transcription).
- **Text-to-Speech**: `KittenML/kitten-tts-micro-0.8` (40M parameter lightweight TTS).
- **Vision Grounding**: MobileNet-V3-Small (Local image/UI classification).

## MCP Code Graph Tools

Expose structural awareness to compatible clients through:

```powershell
python -m mcp.server
```

Available MCP tools include `nexus_code_graph_build`, `nexus_code_graph_summary`, `nexus_code_graph_search`, `nexus_code_graph_dependencies`, `nexus_code_graph_dependents`, and `nexus_code_graph_symbol_context`.

## Engineering Rules

- Do not invent status. Verify from real files, configs, tests, logs, or command output.
- Keep edits scoped and work with existing project patterns before adding abstractions.
- Prefer structured parsers and graph queries over brittle text guessing.
- Preserve user changes. Never revert unrelated work.
- Avoid writing generated/runtime data into source unless the feature explicitly requires it.
- For shell execution, prefer autonomous execution with risk scoring, timeouts, logs, and rollback plans.

## Do Not Treat As Source

- `workspace/`, `logs/`, `models/`, `data/`, `training_data/`, `gui/node_modules/`, `dist/`, `build/`, `.pytest_cache/`, and `__pycache__/` are runtime, dependency, or generated surfaces.

## Refresh Policy

Regenerate after architecture changes, tool registry changes, MCP changes, new verification commands, or major gui/backend workflow changes.
