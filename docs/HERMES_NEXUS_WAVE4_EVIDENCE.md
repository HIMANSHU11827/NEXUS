# Hermes/Nexus implementation wave — 2026-08-10

Hermes reference: `external/hermes-agent`, commit
`03fa32c92dd445eb64c7f67434dd91d32c40701d`.

Implemented in Nexus after source comparison:

- Provider attempts are bounded, redacted, classified, and exposed from both
  provider routing paths.
- OAuth refresh is single-flight per provider for async storage and sync
  factory resolution, preventing concurrent refresh storms.
- V5 `code-action` now requires an active sandbox and has no direct Python
  subprocess fallback when the sandbox is absent.
- Recalled aggregate memory context is redacted before model injection.
- V5 terminal runs persist bounded evidence under
  `workspace/provider_run_evidence/<provider>/<model>/<turn>.json`.
- Verified memory now preserves `call_id`, session/turn/task metadata, and the
  provider-run evidence path in deduplicated `.nexus_v5/memory_evidence.jsonl`
  records; `learned.md` references the resulting opaque memory IDs.
- Provider credentials now expose opaque runtime identities such as
  `config:openai`, `profile:openai:backup`, or `env:openai`; quota rotation uses
  cooldown backoff instead of permanent profile deactivation.

The evidence artifact includes selected/requested provider and model, provider
attempts and fallback outcomes, budget report, tool success/verification
summaries, and final outcome. Raw transcripts and raw tool output are excluded.

Verification:

- Hermes comparison regression set: **44 passed, 1 skipped**.
- V5 direct-loop and streaming-router set: **41 passed**.
- Provenance/credential/cooldown combined wave: **111 passed, 8 warnings**.

Remaining high-value follow-up: true Hermes-style multi-credential leasing,
cross-process locking for profile/evidence writers, canonical event IDs in the
evidence bundle, and a cross-provider soak benchmark.
