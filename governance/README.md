# governance — Governance, policy, and oversight

## Authoritative implementation
- `security/policies/laws.py` — `NexusLawKernel`: policy audit engine enforcing laws from `security/policies/sovereign_laws.yaml` on tool calls
- `security/policies/prover.py` — logic prover used alongside the sovereign laws for policy reasoning
- `security/core/auth.py` — token auth (`NEXUS_DASHBOARD_TOKEN`), OAuth 2.0 (Google, GitHub), signed session cookies, gateway auth helpers
- `permissions.json` — default permission grants for every executable component (filesystem, network, process, environment variables, secrets)
- `src/nexus/common/runtime_guard.py` — runtime write-guard: `PROTECTED_DIRS` (`src`, `apps`, `extensions`, `models`, `security`, …) prevent core rewrites; `guarded_write_text` / `guarded_jsonl_append` helpers

## Why this directory exists
This is the approved home for governance/oversight. The implementations live in `security/`, `permissions.json`, and `src/nexus/common/runtime_guard.py`; `governance/` owns the responsibility map.

## Notes
Runtime guard can be bypassed deliberately via `NEXUS_DISABLE_RUNTIME_GUARD=1` for legitimate maintenance.