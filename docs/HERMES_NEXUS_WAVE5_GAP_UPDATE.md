# Hermes/Nexus gap update — 2026-08-10

This update records the second implementation wave against Hermes commit
`03fa32c92dd445eb64c7f67434dd91d32c40701d`.

## Implemented gaps

| Area | Hermes pattern | Nexus change |
|---|---|---|
| Memory provenance | Structured origin/session/tool metadata | Verified memory keeps session, turn, task, call ID, provider-run evidence path, redacted summary, and stable memory ID in `.nexus_v5/memory_evidence.jsonl`. |
| Learning deduplication | Stable source-qualified memory references | Repeated identical verified evidence is deduplicated and `learned.md` references the opaque memory ID. |
| Credential identity | Stable pooled credential IDs | Factory attaches non-secret credential source/identity metadata; attempt records can carry it without exposing keys. |
| Quota rotation | Temporary quarantine/cooldown | Nexus now uses existing reason-specific cooldown backoff instead of permanently setting profiles inactive. |

## Remaining gaps

- Hermes leases credentials by stable pool entry across concurrent workers;
  Nexus still selects configured profiles and lacks cross-process leasing.
- Nexus profile/evidence writes are protected in-process; multi-process file
  locking is not yet implemented.
- The evidence bundle has provider attempts and outcome data, but canonical
  event IDs and replay/verifier verdict linkage should be added for complete
  cross-run traceability.
- A controlled cross-provider soak benchmark remains to be executed with
  identical prompts, tool schemas, sandbox policy, and completion criteria.

Verification for this wave: **111 passed, 8 warnings** across provenance,
credential identity, cooldown, provider routing, OAuth, V5 loop, sandbox, and
durable-evidence tests.
