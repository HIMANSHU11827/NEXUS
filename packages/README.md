# packages — Shared packages for distribution

## Authoritative implementation
None yet. No shared packages exist; `pnpm-workspace.yaml` currently lists only `apps/web` and `apps/tui`, and `pyproject.toml` covers only the root `nexus-ai` package (documented as absent in `docs/MIGRATION_REPORT.md`).

## Why this directory exists
This is the approved home for distributable shared packages. Intended layout: `packages/<name>/` with a `package.json` (Node) or `pyproject.toml` (Python) per package; apps depend on them via the workspace (a future package is added to the `packages:` list in `pnpm-workspace.yaml`).

## Notes
Keep this directory documentation-only until a real package exists; do not create empty package scaffolding.