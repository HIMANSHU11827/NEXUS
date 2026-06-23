# Test Evolution Ledger
**Version:** 1.0.0 — auto-bumped via `VersionManager` on refine.

Tests for the `EvolutionLedger` module (`evolution.ledger.ledger`), covering:

- **test_init**: Verifies that an `EvolutionLedger` instance is initialized with the correct root path.
- **test_record_event**: Ensures events can be recorded and contain the expected kind field.
- **test_summary**: Verifies that `summary()` returns correct event counts after recording.
