# Tests

Test suites, fixtures, mock data, and quality assurance infrastructure for the entire codebase.

**Version:** 1.0.0

## Running Tests
`powershell
python -m pytest tests/ -v --tb=short
`

## Test Structure
- 	est_evolution_*/ — Evolution system tests (forge, nudge, intent, etc.)
- core/test_loop/ — Loop/orchestrator tests
- Each test has its own folder with scripts/ and conftest.py
- System: 42 passing, 3 pre-existing failures
