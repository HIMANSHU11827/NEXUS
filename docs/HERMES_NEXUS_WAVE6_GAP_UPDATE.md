# Hermes/Nexus gap update — 2026-08-10, wave 6

Reference source: `external/hermes-agent`, commit
`03fa32c92dd445eb64c7f67434dd91d32c40701d`.

Implemented and verified:

- Cross-process provider profile leases with advisory file locks, opaque lease
  IDs, TTL expiry, renewal, exact-owner release, stale-writer protection, and
  spawned-process race coverage.
- Durable evidence trace summaries with canonical event IDs, replay path,
  checkpoint references, bounded verifier verdicts, and Hermes-compatible
  bounded ShareGPT trajectory conversion.
- UX audit evidence covering Nexus GUI/TUI provider setup, authentication,
  fallback visibility, model switching, and sandbox controls. The report adds
  the canonical setup/troubleshooting path and documents that backend
  connectivity is distinct from authentication.

Verification:

- Trace/provider/lease/V5 regression gate: **128 passed, 8 warnings**.
- Provider-independent Nexus framework benchmark: **3/3 passed**; report
  written to `workspace/benchmark_history/nexus_agent_framework_v2.json`.
- Configured-provider soak benchmark dry-run completed; its report is at
  `workspace/provider_soak_dry.json`. Local routes were `planned` and missing
  cloud credentials were `auth_failed`; no network calls were made.

Remaining gaps:

- Named profile leases are now acquired by the provider factory and released by
  the V5 MoE path on success, failure, and fallback; legacy unnamed-provider
  calls remain unchanged.
- Evidence can summarize canonical IDs and replay paths, but full event-stream
  persistence and verifier-to-replay joins remain future work.
- UX runtime visibility is now implemented as a read-only diagnostics projection.
  `GET /api/providers` and `GET /api/status` expose the selected provider/profile/
  model, bounded fallback-attempt summaries, cooldown timers/reasons, and the
  last classified failure. The API whitelists fields and redacts reasons before
  returning them; credential IDs, API keys, and raw provider payloads are not
  exposed.
- The GUI Providers settings card renders the active selection, fallback count,
  cooldowns, and last failure. `/providers`, `/provider status`, and `/status`
  in the active TUI render the same safe diagnostics. This remains observability
  only; routing and credential selection are unchanged.
- Live soak execution remains opt-in and requires explicit provider names plus
  configured credentials; no external provider was contacted in this wave.

Wave 7 persistence hardening:

- Terminal evidence now receives a bounded identity-only canonical event
  projection; raw event payloads remain in the live stream only.
- Replay and checkpoint evidence now classifies artifacts as `present`,
  `missing`, `invalid`, `unlinked`, or `ambiguous`, and records SHA-256
  content identities when an artifact is present.
- Replay JSONL rows now carry an opaque `entry_id`, and replay input/response
  previews are redacted before persistence. Evidence references the entry
  when it is created before the bundle is written.
- The V5 core compatibility shim now delegates checkpoint saving to
  `V5Checkpoint`; checkpoint snapshots recursively redact secret-like strings.
- Focused event/checkpoint/V5 regression gate: **49 passed, 8 warnings**.

Wave 9 verifier freshness hardening:

- V5 verification now records `status`, a bounded `evidence_id`, check time,
  and workspace-scoped file identities for action-referenced paths.
- `V5Verifier.check_verification_freshness()` returns `fresh`, `stale`, or
  `unverified`; changing a referenced file invalidates the prior freshness
  result without deleting the original evidence.
- Run evidence projects the bounded freshness fields while preserving the
  existing redaction boundary.
- New verifier freshness tests cover unchanged files, modified files,
  missing freshness, and bounded evidence projection.

This is intentionally a local content-identity contract rather than a full
Hermes SQLite ledger. Nexus now persists the bounded verifier projection in
`.nexus_v5/verifier_state.json` with advisory cross-process locking, atomic
replacement, session/root isolation, retention pruning, and conservative
`unverified` handling for malformed or expired state. Successful V5 file
mutation events and file API mutations mark matching state stale while
preserving the verifier ID.

Remaining difference: Hermes stores a normalized command/exit-code event
ledger; Nexus currently stores the latest bounded state projection and keeps
full run evidence separately.

Wave 11 verifier event history:

- Added `.nexus_v5/verifier_events.sqlite3`, a bounded, redacted event history
  carrying event ID, session/root, verifier ID, status, command fields, kind,
  scope, exit code, timestamp, and output summary.
- Each V5 verification now creates one event and stores its `last_event_id`
  in the latest-state projection. File edits preserve that link while marking
  the state stale.
- Event retention is bounded and isolated by session/workspace; command and
  output summaries pass through the existing secret-redaction boundary.
- Wave 11 regression gate: **147 passed, 1 skipped, 9 warnings**.

Nexus now has both Hermes-equivalent latest-state freshness semantics and a
bounded event history, though Hermes still has richer command classification
and explicit verification-command workflows.

Wave 12 command-evidence adapter:

- Added conservative classification for configured commands and recognizable
  `pytest`, npm test/build, Cargo, Go, Ruff, and MyPy checks.
- Shell chains, generic scripts, arbitrary commands, and commands without a
  trusted exit code are not classified as verification. Pipes/redirection are
  rejected before configured-command matching. Targeted scope is inferred from
  explicit file/test selectors, and exit codes plus bounded redacted output
  flow into verifier events only when a command is recognized.
- V5 actions now preserve the trusted sandbox exit code in the action
  envelope, allowing the classifier to avoid inferring success from a missing
  code.
- Wave 12 regression gate: **151 passed, 1 skipped, 9 warnings**.

Wave 13 identity joins:

- Run evidence now exposes an explicit `trace.joins` object linking session,
  turn, verifier event ID, replay entry ID, and checkpoint artifact paths,
  statuses, and digests.
- Replay entries now carry unique IDs and a canonical per-record SHA-256;
  evidence recomputes that digest and marks tampered records `invalid`.
- The join is metadata-only; raw transcripts, command output, and secrets are
  not copied into the linkage record.
- Provider soak remains honest and offline by default. The current configured
  dry-run report records three local routes as `planned` and two cloud routes
  as `auth_failed`; no network provider call was made.

Wave 14 explicit verification workflow:

- Added `run_programmatic_verification` and `/api/verification/run` for
  explicit verification recipes. Each command runs through
  `SovereignSandbox`, retains the trusted exit code, bounded redacted output,
  canonical command, Hermes-compatible kind/scope, phase, cwd/root/session
  identity, duration, timeout/error facts, and status, and persists per-check
  events plus an aggregate verifier event and latest durable state under a
  shared run ID.
- Missing exit codes, shell chains, and unclassifiable commands remain
  `unverified`; they cannot create a passing durable state.
- Public API execution does not accept caller-selected shells or arbitrary
  self-authorized commands; it enforces workspace scope and a total deadline.
- Optional readiness evidence is supported for loopback HTTP(S) URLs only;
  external URLs and arbitrary start commands remain disallowed at the public
  boundary.
- Added read-only Hermes-style recipe detection from Nexus manifests and
  project metadata, plus an explicit `recipe: "auto"` execution mode. It runs
  detected checks only through the sandbox and never starts an application
  process automatically.
- Wave 15 focused gate: **44 passed, 1 warning**.
- Wave 16 focused gate: **16 passed**.

Wave 17 provider preflight:

- The configured local routes were safely probed and both are currently
  unreachable: LM Studio `127.0.0.1:1234` and Ollama `127.0.0.1:11434`.
- Live provider soak now performs a bounded local TCP preflight and records
  `unavailable/local_server_unreachable` without issuing a model request when
  the service is absent. Remote providers remain credential-gated and are not
  probed implicitly.
- Wave 17 provider gate: **14 passed**.

Wave 18 provider fallback correction:

- Factory resolution already treated loopback providers as keyless-safe, but
  router invocation and streaming fallback still called remote-style
  `validate_api_key()` unconditionally. The router now recognizes loopback
  endpoints/provider IDs consistently while keeping remote authentication
  fail-closed.
- Wave 18 provider/router gate: **17 passed**.
- Hermes-compatible targeted scope now recognizes test directories such as
  `tests/`, `spec/`, and `__tests__/` in addition to file/node selectors.
- Wave 14 focused gate: **23 passed** (programmatic workflow, API, command
  classifier, event history, and durable state tests).

Wave 19 OAuth resolution correction:

- Provider-factory resolution now performs the OAuth token lookup even when no
  named profile is selected, after config/profile/environment precedence is
  exhausted. The resolved provider carries a redacted oauth:<provider>
  credential identity rather than silently appearing keyless.
- This fixes the real Grok OAuth regression found during the broad regression
  run; the focused OAuth, refresh-single-flight, router-attempt, and streaming
  regression gate passed **10 tests**.
- A fresh broad-suite attempt is currently limited by the host's Windows
  WinError 5 ACL on pytest's temporary root while setting up tmp_path
  fixtures; this is an execution-environment limitation, not reported as a
  passing full-suite result.
