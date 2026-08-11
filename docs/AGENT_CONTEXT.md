# Agent Context

NEXUS generates compact repository context for coding agents via `docs/NEXUS.md` — the platform persona/soul file.

## How It Works

- `docs/NEXUS.md` serves as the identity document — loaded by `NexusLoop._load_soul_md()` during grounding
- Context sources: `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.cursor/rules/*.mdc` — loaded by `_load_prompt_files()`
- Context building lives in `orchestrators/v5/grounding.py` (`V5ContextGrounding` mixin) and `orchestrators/v5/compat.py`
- `_workstyle_context(task_desc)` returns workstyle guidance for real tasks
- Context compaction: `_compact_memory()` preserves system messages + the most recent turns when the message count exceeds `compact_threshold` (default 20); `compact_keep` (default 6) most recent turns are kept. Both are runtime config fields on the V5 loop

## Context Loading (Parallel)

All context sources loaded concurrently in `_ground_context()` (`orchestrators/v5/grounding.py`):

1. Soul file (docs/NEXUS.md)
2. Prompt files (AGENTS.md, CLAUDE.md, etc.)
3. Knowledge context (via RAG retrieval)
4. Project docs (via Atlas engine)
5. Tool descriptions (via `_load_tool_descriptions()` reading the live `ToolRegistry`)
6. Stable prompt tier (via `_build_stable_prompt()` — soul + tools + skills index, cached)
7. Progressive rules (via `_load_progressive_rules()`)
8. Continuity context (via `_load_continuity_context()` — persisted unfinished-work evidence)
