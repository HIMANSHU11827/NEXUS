> _(Architectural reference — may not reflect latest code changes)_

# NEXUS AI: Sovereign Engineering Project Memory (A to Z)

This document captures the core architecture and evolution system of the NEXUS AI platform.

---

## Core Architecture

### The Sovereign Kernel (`src/nexus/runtime/kernel/` package)
A thread-safe singleton managing lazy-loading for all core services:
*   **MoE Router:** Dynamic model tiering (NANO to EXTREME).
*   **Hive Engine:** Asynchronous Hive worker orchestration.
*   **RAG Engine:** Long-term vector memory (BM25 + hybrid vector).
*   **Tool Registry:** Hardened access to current tools: code_search, creating, deep_research, deleting, git_ops, hive, knowledge, memory, modifying, planning, reading, reasoning, shortcuts, system, task, terminal, test_runner, web_search (`bash` is retired).

### Unified Cognitive Loop (`src/nexus/main_agent/core.py`)
The current `NexusLoop` uses a unified model/tool runtime rather than the removed `SCAState` enum. It grounds prompt context, classifies whether real tools are required, streams provider output, extracts tool calls, applies permission/risk/sandbox checks, executes read tools in parallel and write tools sequentially, verifies outcomes, persists session memory, and emits canonical work events throughout.

### Evolution & Version System (`evolution/` package)
20 modules in per-folder format:
*   `tool_forge/`, `skill_forge/`, `plugin_forge/`, `memory_forge/`, `knowledge_forge/`, `log_forge/`
*   Support: `logs/`, `status/`, `ledger/`, `nudge/`, `intent/`, `self_improvement/`, `sop/`, `ensemble/`, `version/`, `local_trainer/`, `omni_kernel/`, `hyper_kernel/`, `researcher/`, `curator/`, `horizons/`
*   `VersionManager` tracks semver across all 67 `.jsnol` module files (repo-wide)
*   All 6 forges auto-bump versions on refine (minor by default, major on upgrade)
*   Every `scripts/*.py` has `__version__` embedded inline
*   Config YAMLs are versioned for non-secret settings. Provider YAML should use environment-variable placeholders for credentials.

### User Interfaces
| Interface | Start | Path |
|-----------|-------|------|
| **TUI** | `python -m nexus` | `apps/tui/` + `apps.web.api` backend |
| **Rich shell** | `python -m nexus --shell` | in-process Rich compat mode (legacy) |
| **GUI** | `python -m nexus --gui` | `apps/web/` + `apps.web.api` |
| **Gateway** | `python -m nexus --gateway` | `gateways/` — 21 platforms (Telegram, Discord, WhatsApp, Slack, Teams, etc.) |

---

## Implemented Upgrades

1.  **7-State Sovereign Loop:** GROUNDING → PLANNING → INFERENCE → AUDITING → EXECUTION → VERIFICATION → EVOLVE
2.  **Auto-Version Tracking:** VersionManager tracks all 67 `.jsnol` modules with semver bump on every forge refine
3.  **Per-Module Evolution Structure:** Every evolution module has `<name>.jsnol` (metadata), `scripts/` (code), `<name>.md` (docs)
4.  **Embedded Inline Versions:** Every script file has `__version__ = "1.0.0"` at the source level
5.  **Tool Registry:** Current split tools under `extensions/tools/built_in/<name>/` with jsnol metadata + sandboxed execution, including dedicated `reading`, `creating`, `modifying`, and `deleting` filesystem tools instead of the removed `file_ops` tool.
6.  **Sovereign Sandbox:** 3-tier security (`no_sandbox`, `normal`, `docker`) with `normal` as the safe default and risk-based filtering before command execution.
7.  **NATE (NEXUS Native Tool Engine):** `src/nexus/capabilities/intelligence/nate/` — 5-layer fused tool calling runtime with universal format adapter, **NATE-Route** embedding router (all-MiniLM-L6-v2 + FAISS, 88% schema reduction, 67% token savings), STRAP clustering, necessity gate, OATS feedback. Solves all 12 skill alignment problems. Two-Phase Schema Loader integrated into NexusLoop. See `docs/NATE.md`.
8.  **Self-Improving Lifecycle:** `evolution/local_trainer/` — auto harvests tool logs → fine-tunes embedding + Zupra-50M → exports GGUF → reloads. Triggered when 20-50+ examples accumulate.
9.  **Zupra Local Provider:** `models/providers/api/zupra.py` — MultivexAI/Zupra-1.6-50M-Instruct-Ultra-exp for fully offline CPU inference. Registered in factory as "zupra". No API key needed.

---

## Security & Autonomy Configuration

### Autonomy Modes
*   **AUTO_PILOT (Default):** Agent self-governs; blocks only high-risk commands.
*   **BYPASS:** Sovereign mode; no blocks, maximum speed.
*   **APPROVE:** Manual control; prompts for every action.
*   **PRE_AUTHORIZED:** Whitelist mode; only runs saved/approved commands.

### Sandbox Tiers
*   **NORMAL (Default):** Workspace-scoped shell execution with reduced environment exposure.
*   **DOCKER:** Container-backed execution when available.
*   **NO_SANDBOX:** Direct execution for explicit local override only.

---

## Memory Persistence
*   **Session Context:** Automatically saved to `.nexus/logs/sessions/` and reloaded on start.
*   **Global History:** Permanent record in `.nexus/memory/`.
*   **Impact Sensing:** Evolution hooks track changes for auto-version bumps.

## Verification
```powershell
python -m pytest tests/ -v --tb=short
python -c "from evolution.version.scripts.version import VersionManager; vm=VersionManager('.'); print(vm.get_all_versions_report())"
```
