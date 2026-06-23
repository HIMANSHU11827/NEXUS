# Evolution Ledger

EvolutionLedger — immutable record of all evolution events (forges, refinements, version bumps).

**Version:** 1.0.0

## Features
- record(event_type, data) — Append-only event logging
- query(filters) — Query ledger history
- replay(mission_id) — Replay mission timeline
