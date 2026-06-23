# Version Manager
**Version:** 1.0.0 — auto-bumped via `VersionManager` on refine.

Centralized version tracking, bumping, and compatibility checking for all NEXUS modules (tools, skills, plugins, forges, tests).

## Usage
- `VersionManager(root).list_versions()` — Show all module versions
- `VersionManager(root).bump(name, "major|minor|patch")` — Bump version
- `VersionManager(root).check_compatibility(name, required)` — Check major compatibility
- `VersionManager(root).get_version(name)` — Get single module version
