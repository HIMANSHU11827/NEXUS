# Git Ops Tool
**Version:** 1.0.0

Read-only git inspection for NEXUS.

## Parameters
- `action` (string, required): `status|diff|log|branch|show|files`
- `ref` (string, optional): Git ref, branch, commit, or comparison target
- `path` (string, optional): Optional path filter
- `limit` (int, optional, default=20): Max rows or commits
