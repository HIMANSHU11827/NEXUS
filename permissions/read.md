# Permissions

Access control and permission management — roles, policies, and authorization rules.

**Version:** 1.0.0

## Permission Policies
- DEFAULT / APPROVE — human approval required when no explicit allow rule matches
- PLAN — permit actions that are part of an accepted plan
- AUTO / AUTO_PILOT — autonomous mode with risk scoring and explicit deny rules
- PRE_AUTHORIZED — exact command allowlist only
- BYPASS — explicit local override that skips policy checks

Explicit deny rules win before allow rules in every non-BYPASS mode.

## Decision Log
Every permission check records a bounded in-memory decision with:
- mode, tool, allow/deny result, source, reason, and matched rule when present
- optional run/session/surface context
- a scrubbed action preview with common tokens and API keys redacted

Use `PermissionSystem().get_decision_log()` or the server's
`/api/permissions/decisions` endpoint to inspect recent decisions.
