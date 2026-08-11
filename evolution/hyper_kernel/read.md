# HyperKernel

Meta-reasoning kernel enabling cross-domain synthesis and advanced cognitive pipelines.

**Version:** 2.0.0

## Status
Implemented — `scripts/hyper_kernel.py` (v0.2.0).

## Components
- `HyperKernel`:
  - `register_check(name, check, module=None)` — register a named health/consistency check
  - `check_all(names=None)` — run registered checks (optionally a subset), returning per-check results
  - `snapshot(name)` — last result for a check
  - `summary()` — aggregate status overview
  - `_run_check(name, cfg)` — executes a check with error capture

## Notes
- Covered by `tests/test_evolution_subsystems/` (asserts `is_stub is False`).
