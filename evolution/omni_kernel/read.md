# OmniEvolutionKernel

Central orchestration kernel for coordinating evolution subsystems across NEXUS AI.

**Version:** 2.0.0

## Status
Implemented — `scripts/omni_kernel.py` (v0.2.0).

## Components
- `OmniEvolutionKernel`:
  - `evolve(...)` — run an evolution cycle through the stage pipeline
  - `run_cycle(...)` — alias for a full cycle
  - `status()` — per-stage state report
  - `_run_stage(name, outcome, payload)` — guarded stage execution with fault isolation
- Stage pipeline: `ledger` → `backlog` → `memory_forge` → `curator` (unknown stages are rejected)

## Notes
- Covered by `tests/test_evolution_subsystems/` (asserts `is_stub is False`).
