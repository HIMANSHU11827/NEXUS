# Ensemble Manager

EnsembleManager — multi-strategy reasoning for improved decision making.

**Version:** 2.0.0

## Status
Implemented — `scripts/ensemble.py` (v2.1.0).

## Components
- `EnsembleResult` — result envelope (problem, winner, scores, history)
- `EnsembleManager`:
  - `select_winner(candidates)` — weighted scoring of candidate answers (40/20/20/20 weights: quality, speed, consistency, evidence)
  - `run_ensemble(problem, candidates)` — full ensemble pass returning `EnsembleResult`
  - `get_history()` — past ensemble outcomes
  - `_score_candidate(candidate)` — per-candidate scoring logic

## Features
- Weighted voting for decision aggregation
- Strategy/answer performance tracking via history

## Notes
- Covered by `tests/test_evolution_subsystems/` (asserts `is_stub is False`).
