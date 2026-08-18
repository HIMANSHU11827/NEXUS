# NEXUS AI Repository Restructure — Final Migration Report

Date: 2026-08-18
Commits: `fcd4ad9c` (structure move), `f48139fc` (regression fixes I), `e35031c3` (regression fixes II), `cd4622b8`/`ed0d4d9e` (cleanup)

## Objective

Restructure the repository from a flat, namespace-colliding root layout (111 root entries, top-level packages like `server/`, `providers/`, `kernel/`, `tools/`, `gui/` shadowing installed packages) to an approved root allowlist, with every import, patch target, path constant, launcher, and test rewritten, and the full test suite green.

## Result

| | Entries |
|---|---|
| Original root entries | 111 |
| Final root entries | 42 (36 after excluding dotfiles) |
| Approved code directories | apps, src, extensions, hive, gateways, models, memory, queues, sandbox, security, reliability, observability, knowledge, evolution, evaluation, maintenance, native, configure, tests, scripts, deployment, docs, examples, benchmarks |
| Root tree audit | Clean — every remaining entry is an allowed code dir, a config/doc file (README, pyproject.toml, docker-compose.yml, nexus.config.json, permissions.json, feature-flags.json, opencode.json, .env.example, LICENSE, SECURITY.md, ...), or gitignored runtime state (.nexus/, .nexus_v5/, .nexus_queue.db, context_archive/, data/, logs/, workspace/, references/, .tmp/, .pytest_cache/) |

## What moved (per the classification plan)

- **Code packages → canonical dirs** (rewritten imports): `server/` → `apps/api/__init__.py`; `gui/` → `apps/web/`; `tui/` → `apps/tui/`; `voice/` → `apps/voice/`; `providers/` → `models/providers/{core,api,local,auth}`; `orchestrators/` → `src/nexus/main_agent/` (NexusLoop alias retained in `src/nexus/main_agent/__init__.py`); `kernel/` → `src/nexus/runtime/kernel/`; `tools/` → `extensions/tools/built_in/`; `plugins/` → `extensions/plugins/built_in/`; `skills/` → `extensions/skills/built_in/`; `mcp/` → `extensions/mcp/core/`; `authentication/` → `security/core/auth.py`; `queue/` → `queues/`; `config/` → `configure/`; `bin/` → `native/`; `deploy/` → `deployment/`; `rag/` + `indexer/` → `knowledge/rag/` + `knowledge/rag/atlas/`; `telemetry/` → `observability/`; `cognition/` → `src/nexus/capabilities/reasoning/` + `intelligence/`; `utils/`, `tasks/`, `commands/`, `prompts/`, `shared/`, `core/`, `context/`, `optimization/`, `reliability/`, `safety/`, `permissions/`, `lifecycle/`, `greeting/`, `hardware/`, `neural/`, `games/`, `router/`, `intelligence/`, `reasoning/` → consolidated into `src/nexus/**` or their allowlist homes.
- **Runtime state → `.nexus/`**: workspace, logs, sessions, work events, checkpoints, voice log, hive manifest, queue.db, todo.md, lifecycle skill state. `.research` → `references/` (gitignored).
- **Launchers** → `scripts/launchers/` (15 `.cmd`/`.ps1`; `NEXUS_ROOT=%~dp0..\..`, `PYTHONPATH=%NEXUS_ROOT%;%NEXUS_ROOT%src`). Setup wizard, release gate, doctor, export/import tools updated.
- **Config**: `pyproject.toml` packages.find (src + root dirs), `[tool.setuptools]` pythonpath, entry points, `.gitignore` refreshed, ci.yml compileall + GUI job, `apps/web` + `apps/tui` Docker/nginx files preserved under `deployment/` references and root `docker-compose.yml`.

## Verification

- **Full test suite**: `pytest tests -q` → **2582 passed, 15 skipped, 0 failed** (was: 2564 collected with 5 collection errors pre-fix; subsets showed 404+ pass/… failures mid-migration).
- `compileall` on all code + tests: OK.
- Boot smoke: `python -m nexus --version` / `--help` run clean.
- All 56 provider `MAPPINGS` lazy-load paths verified importable.
- Runtime guard (`src/nexus/common/runtime_guard.py`) verified active: `PROJECT_ROOT` corrected to repo root (was one level short after the move — the guard's own activation tests now pass and it demonstrably blocks writes to `apps/api/__init__.py`, `src/nexus/**`).

## Stale references fixed

- 26+ test files: import/alias rewrites (`import apps.api as server`, `security.core.auth as authentication`, `nexus.main_agent` for orchestrators, `extensions.mcp.core.client`, `extensions.tools.built_in.nexus_tools.registry`, `models.providers.*` patch targets, `queues.*`, `apps.web.api`).
- `models/providers/core/factory.py` MAPPINGS dict: 56 entries + fallback loader path → `models.providers.*` canonical.
- `scripts/release_gate.py`: `deploy/` → `deployment/` + root `docker-compose.yml`; `gui/` → `apps/web/`.
- `scripts/launchers/setup.ps1`: gui/tui/config paths → `apps/web`, `apps/tui`, root `.env`/`.env.example`.
- `apps/api/__init__.py`, `apps/web/api.py`, `src/nexus/__init__.py`, discovery, plugins manager, skills engine, tools registry, evolution researcher/status, TUI compile gate, observability unified_graph: all runtime path constants → `.nexus/` or canonical dirs.
- Stale test expectations for the old layout (work-items store `logs/sessions` → `.nexus/logs/sessions`, tool/skill discovery dirs, plugin install root, TUI entry path, prompt-engine fallback module) updated to canonical paths; several tests additionally revealed real bugs that were fixed (runtime guard root, provider factory fallback, release gate).

## Remaining technical debt (pre-existing, out of scope)

- `src/nexus/common/token_counter.py` imports `tiktoken`, which is not declared in pyproject dependencies (FAIL-B, pre-existing).
- Cosmetic log/diagnostic strings still mention old paths (e.g. `server/__init__.py`, `kernel/__init__.py`, `voice/...` labels); harmless, left for clarity of history.
- `datetime.utcnow()` deprecation warning in one test file; FastAPI TestClient httpx deprecation warning (environment).
- `.claude/settings.json` is written on demand by the API (external-config compatibility, same pattern as `.opencode`).
- `workspace-under-test/` created by `test_tool_skill_boundary_fixes.py` is gitignored (test byproduct).

## How to verify from a clean checkout

```powershell
cd "$env:USERPROFILE\Desktop\NEXUS AI"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
$env:PYTHONPATH = "$PWD;$PWD\src"
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m nexus --help
```