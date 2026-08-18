# migrations — Schema/data migration discipline

## Authoritative implementation
- `docs/MIGRATION_REPORT.md` — final report of Restructure II (2026-08-19: expanded authoritative root allowlist, runtime state consolidated under `.nexus/`); supersedes the Restructure I report (2026-08-18: 111 → 42 root entries)

## Why this directory exists
This is the approved home for migration documentation and policy. Policy: migrations are reviewed, validated, committed, and documented **before** deployment; no in-place destructive migration without a validated rollback path. Restructure II validated with the full test suite (2582 passed / 15 skipped / 0 failed).

## Notes
There is currently no migration framework; any future schema/data migration records its review and rollback plan here and updates `docs/MIGRATION_REPORT.md`.