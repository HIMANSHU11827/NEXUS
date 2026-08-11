# Tests

Test suites, fixtures, mock data, and quality assurance infrastructure for the entire codebase.

**Version:** 2.0.0

## Running Tests
```powershell
python -m pytest tests/ -v --tb=short
```

## Test Structure
- 32 test subdirectories: 28 `test_*` dirs + `core/`, `gui/`, `smoke/`, `v5/` — 156+ test files total
- `test_evolution_*/` — Evolution system tests (forge, nudge, intent, etc.)
- `core/test_evolution/` — Evolution subsystem tests (ledger, log, forges)
- Fixtures live in `tests/conftest.py` (root) and `tests/gui/conftest.py`; test dirs ship their own `scripts/` modules, not per-folder conftest files
- Full-suite run: ~163 tests passing (see `LOOP_RESEARCH_REPORT.md`)
