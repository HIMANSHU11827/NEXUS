# Sandbox

Isolated execution environment for running tools, agent scripts, and commands safely.

**Version:** 1.0.0

## Components
- `sandbox_manager.py` — `SovereignSandbox`: sandboxed tool execution with concurrent reads, serial writes
- `risk.py` — `CommandRiskScorer`: deterministic command risk scoring

## Security Tiers
- **NO_SANDBOX** — Direct execution for explicit local override only
- **NORMAL** — Workspace-scoped shell isolation and the default/fail-closed tier
- **DOCKER** — Container isolation with host workspace-scope validation before launch
