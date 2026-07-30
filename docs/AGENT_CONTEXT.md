# Agent Context

NEXUS generates compact repository context for coding agents via `docs/NEXUS.md` — the platform persona/soul file.

## How It Works

- `docs/NEXUS.md` serves as the identity document — loaded by `NexusLoop._load_soul_md()` during grounding
- Context sources: `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.cursor/rules/*.mdc` — loaded by `_load_prompt_files()`
- `_scan_and_filter_context()` applies threat scanning before context enters the model
- `_identity_context()` returns NEXUS identity for identity questions
- `_workstyle_context()` returns workstyle guidance for real tasks
- Context compaction: `_compact_memory()` at `COMPACT_THRESHOLD=20` keeps `COMPACT_KEEP=6` most recent turns

## Context Loading (Parallel)

All context sources loaded concurrently in `_ground_context()`:
1. Soul file (docs/NEXUS.md)
2. Prompt files (AGENTS.md, CLAUDE.md, etc.)
3. Knowledge context (via RAG retrieval)
4. Project docs (via Atlas engine)
5. Tool descriptions (via NATE or ToolRegistry)
6. Stable prompt tier (via `_build_stable_prompt()`)
7. Progressive rules (via `_load_progressive_rules()`)
