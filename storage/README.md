# storage — Durable storage: runtime state, data, knowledge indexes

## Authoritative implementation
- `.nexus/` — gitignored runtime state: `queues/` (queue.db), `logs/`, `plans/`, `work_items/`, `workspace/` (todo.md), `memory/`, `context_archive/`, `hive/`, `lifecycle/`, `v5/`, plus `control_plane.sqlite3`, `meta_learning.json`, `versions.json`
- `data/` — gitignored runtime data: `data/memory_forge/`, `data/references/`
- `knowledge/` — knowledge system source; generated indexes (`knowledge/*.db`, `_rag_index.json`) are gitignored and currently none exist

## Why this directory exists
This is the approved home for storage ownership. Policy: runtime state is gitignored under `.nexus/` and `data/`; source code never contains runtime storage. Restructure II (see `docs/MIGRATION_REPORT.md`) consolidated every legacy runtime path (`.nexus_v5/`, root `logs/`, `workspace/`, `queue.db`) under `.nexus/`.

## Notes
`.gitignore` lines 28/77 ignore `.nexus/` and `data/`; line 87 ignores `knowledge/*.db`. The queue driver, scheduler, learning evidence, and planning all write under `.nexus/`.