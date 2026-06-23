# NEXUS AI: Sovereign Engineering Project Memory (A to Z)

This document captures the core architecture and evolution system of the NEXUS AI platform.

---

## Core Architecture

### The Sovereign Kernel (`kernel/` package)
A thread-safe singleton managing lazy-loading for all core services:
*   **MoE Router:** Dynamic model tiering (NANO to EXTREME).
*   **Hive Engine:** Asynchronous Hive worker orchestration.
*   **RAG Engine:** Long-term vector memory (BM25 + hybrid vector).
*   **Tool Registry:** Hardened access to 10 tools (bash, code_search, file_ops, knowledge, mcp, memory, reasoning, system, task, web_search).

### Unified Cognitive Loop (`orchestrators/loop.py`)
A 7-state sovereign cognitive loop (`SCAState`):
*   **GROUNDING:** Parallel load of rules, RAG, and compiler status.
*   **PLANNING:** Complexity classifier (tiers 0/1/2) — direct chat, checklist, or architect roadmap.
*   **INFERENCE:** LLM call via MoE router with tool call extraction.
*   **AUDITING:** Permission policy resolution + `CommandRiskScorer` + `SafetyLaws`.
*   **EXECUTION:** Concurrent reads / serial writes via `SovereignSandbox`.
*   **VERIFICATION:** Diagnostics, failure vaccines, context compaction, gap detection.
*   **EVOLVE:** Session sync, memory persist, evolution logging.

### Evolution & Version System (`evolution/` package)
18 modules in per-folder format:
*   `tool_forge/`, `skill_forge/`, `plugin_forge/`, `memory_forge/`, `knowledge_forge/`, `log_forge/`
*   Support: `logs/`, `status/`, `ledger/`, `nudge/`, `intent/`, `self_improvement/`, `sop/`, `ensemble/`, `version/`
*   `VersionManager` tracks semver (1.0.0) across all 39 `.jsnol` module files
*   All 6 forges auto-bump versions on refine (minor by default, major on upgrade)
*   Every `scripts/*.py` has `__version__` embedded inline
*   Config YAMLs also versioned (`config/provider.yml`, `settings.yml`, `system.yml`)

### User Surfaces
| Surface | Start | Path |
|---------|-------|------|
| **Terminal** (live) | `python -m nexus` | `nexus/` package |
| **CLI** (Ink client) | `cd cli && npm start` | `cli/` — needs API on `:8000` |
| **GUI** | `cd gui && python -m server` | `gui/`, `server/` package |
| **Gateway** | `python -m gateway.main` | `gateway/` — Telegram, Discord, WA |

---

## Implemented Upgrades

1.  **7-State Sovereign Loop:** GROUNDING → PLANNING → INFERENCE → AUDITING → EXECUTION → VERIFICATION → EVOLVE
2.  **Auto-Version Tracking:** VersionManager tracks all 39 modules with semver bump on every forge refine
3.  **Per-Module Evolution Structure:** Every evolution module has `<name>.jsnol` (metadata), `scripts/` (code), `<name>.md` (docs)
4.  **Embedded Inline Versions:** Every script file has `__version__ = "1.0.0"` at the source level
5.  **Tool Registry:** 10 tools under `tools/<name>/` with jsnol metadata + sandboxed execution
6.  **Sovereign Sandbox:** 2-tier security (Restricted Shell / Docker) with risk-based filtering

---

## Security & Autonomy Configuration

### Autonomy Modes
*   **AUTO_PILOT (Default):** Agent self-governs; blocks only high-risk commands.
*   **BYPASS:** Sovereign mode; no blocks, maximum speed.
*   **APPROVE:** Manual control; prompts for every action.
*   **PRE_AUTHORIZED:** Whitelist mode; only runs saved/approved commands.

### Sandbox Tiers
*   **NO_SANDBOX (Default):** Direct speed.
*   **SANDBOX:** Isolation via **Normal** (Shell) or **Docker** backends.

---

## Memory Persistence
*   **Session Context:** Automatically saved to `logs/sessions/` and reloaded on start.
*   **Global History:** Permanent record in `logs/memory/global_history.md`.
*   **Impact Sensing:** Evolution hooks track changes for auto-version bumps.

## Verification
```powershell
python -m pytest tests/ -v --tb=short
python -c "from evolution.version.scripts.version import VersionManager; vm=VersionManager('.'); print(vm.get_all_versions_report())"
```
