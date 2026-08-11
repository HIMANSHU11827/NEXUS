# Git Ops Tool
**Version:** 2.0.0

Read-only git inspection for NEXUS.

## Parameters
- `action` (string, required): `status|diff|log|branch|show|files`
- `ref` (string, optional): Git ref, branch, commit, or comparison target
- `path` (string, optional): Optional path filter
- `name_only` (bool, optional, default=false): For `diff`, list changed file names only (`git diff --name-only`)
- `limit` (int, optional, default=20): Max rows or commits
