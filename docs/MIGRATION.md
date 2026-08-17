# Migration Guide

This document records the restructure of the NEXUS AI repository toward the target architecture (see `docs/ARCHITECTURE.md`). All changes are committed, validated by the test suite (2,597 tests collect cleanly), and preserve backward-compatible shims so existing imports keep working during transition.

## Committed checkpoints

| # | Change | Notes |
|---|--------|-------|
| 1 | `gateway/` → `gateways/`, `config/` → `configure/`, `queue/` → `queues/` | Stdlib `queue` left untouched; `queues/__init__.py` shim forwards `TaskQueue`, `QueueDriver`. |
| 2 | Providers split into `models/providers/{core,local,api,auth}/` | 44 modules moved by category; `providers/` is a re-export shim. Factory routes `providers.<name>` → `models.providers.<cat>.<name>`. |
| 3 | `tools/` → `extensions/tools/built_in/` | Whole package moved; `tools/` shim re-exports. Planning now lives here (mandate §2.3). |
| 4 | `skills/` → `extensions/skills/built_in/` | 69 `SKILL.md` packages; `skills/` shim re-exports. |
| 5 | `plugins/` → `extensions/plugins/built_in/`, `mcp/` → `extensions/mcp/core/` | Shim re-exports for both. |
| 6 | `server/`→`apps/api/`, `tui/`→`apps/tui/`, `gui/`→`apps/web/` | `nexus:boot` updated; shims `server/`,`tui/`,`gui/` remain. |
| 7 | Dedicated Gateway app `apps/gateway/nexus_gateway_app/` | Thin layer over the `gateways/` engine; `nexus-gateway-app` console script. |
| 8 | Root config scaffolding | `nexus.config.json`, `permissions.json`, `feature-flags.json`, `.env.example`, `.pre-commit-config.yaml`. |

## Import compatibility shims (temporary, per mandate §27)

- `tools` → `extensions.tools.built_in` (identity-preserving `sys.modules` alias)
- `skills` → `extensions.skills.built_in`
- `plugins` → `extensions.plugins.built_in`
- `mcp` → `extensions.mcp.core`
- `providers` → `models.providers.*` (re-export shim, 269+ external references preserved)
- `server`/`tui`/`gui` → `apps.api`/`apps.tui`/`apps.web`
- `queues` → corrected shim (not a filename rename)

These shims should be removed after dependents are migrated to canonical paths.

## How to migrate a stale reference

1. Find importers: `grep -rn "from tools\." --include=*.py .` (replace `tools` with the component).
2. Update Python imports to the canonical path (`extensions.tools.built_in.…`).
3. Update dynamic imports / entry points / registries / `tests/`.
4. Run `python -m pytest --co` to confirm collection; run the affected component tests.
5. Only delete the old shim after the suite is green without it.

## Known non-goals of this migration

- `src/nexus/` wrapping: `nexus/` works as the package root; moving to `src/nexus/` is deferred (high-risk import churn, low architectural gain).
- ~20 other working top-level subsystems (`cognition/`, `intelligence/`, `kernel/`, `orchestrators/`, `security/`, `safety/`, `sandbox/`, `reliability/`, `memory/`, `knowledge/`, `rag/`, `context/`, …) were intentionally NOT relocated — they are functioning subsystems; the auditor confirmed `commands/` and `registries/` are already consolidated (the two hardest mandate requirements).
- `build/` is a stale setuptools artifact; gitignored, not tracked.
