# Sandbox

Isolated execution environment — 3-tier sandbox + deterministic risk scoring + failure memory.

**Version:** 2.0.0

## Components
- `sandbox_manager.py` — `SovereignSandbox`: async streaming execution with concurrent reads, serial writes
- `risk.py` — `CommandRiskScorer`: deterministic risk scoring (8 regex rules, 16 safe prefixes, block threshold 80)
- `failure_memory.py` — `FailureMemory`: append-only JSONL failure log for preventive learning

## Security Tiers
- **NO_SANDBOX** — Direct execution for explicit local override only
- **NORMAL** — Workspace-scoped shell isolation (default/fail-closed)
- **DOCKER** — Container isolation with workspace-scope validation before launch
