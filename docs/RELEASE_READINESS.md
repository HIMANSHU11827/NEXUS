# Nexus AI release readiness

Last audited: 2026-08-10

## Current verdict

**CONDITIONAL GO for public internet release.** The runtime, frontend, security gates, and test suite are release-ready. The deployment operator must supply production secrets, a clean release branch, and a Docker-capable hosting target before exposing it publicly.

## Verified in this pass

- Backend starts and `/api/health` returns HTTP 200.
- Unauthenticated `/api/files/list` returns HTTP 401.
- Queue leasing prevents duplicate claims across separate queue instances.
- Queue idempotency returns one task for repeated mission enqueue keys.
- Python compilation passes for changed runtime modules.
- Framework benchmark passes 3/3 provider-independent cases.
- GUI production build passes with a large-chunk warning.
- Docker Compose GUI context now points at the repository root and a production GUI image.
- Compose backend binds on the container interface and runs the API server; the GUI image reverse-proxies `/api` and `/v1` to it for browser clients.
- Full repository suite: 1612 passed, 11 skipped, 49 warnings.
- `/api/metrics` exposes durable queue-worker heartbeat age, state, and bounded counters for external monitoring.
- Repeated embedded-worker failures are persisted and quarantined within a configurable crash window; operators must explicitly clear quarantine after remediation.
- Public deployment security tests: 4 passed.
- Public-mode startup smoke: health 200; protected file/state routes 401 without a token.
- The default PowerShell launcher now probes backend health continuously and restarts an alive-but-degraded API after three failed probes, with bounded restart backoff; `-NoWatchdog` remains an explicit opt-out.
- `/resume` continuation path passed a live-loop integration probe.
- Repository release gate passes: safe config, required container artifacts, compose structure, and untracked secret files.
- Compose now enables the embedded durable queue worker and gives both API and GUI services healthchecks plus `restart: unless-stopped` recovery policy.
- Hive pause/resume and stale-agent replacement passed failure-injection tests; the server now exposes `/api/hives/{hive_id}/pause` and resumes paused Hives in place.
- V5 durable background jobs now persist lifecycle state in SQLite and rehydrate automatically when their explicitly registered factory is available; unregistered ephemeral jobs remain intentionally non-restartable.
- Work-event replay now returns a structured `replay_gap` range when retention has removed events before a reconnecting client’s cursor; the GUI already surfaces this condition.
- Hive consolidation can now require an auditable quorum with configurable vote thresholds and required personas; it refuses unverified consolidation when quorum is not reached.
- Hive blackboard values and artifact fingerprints now survive process restart; optimistic writes fail on stale versions and artifact reconciliation reports present, changed, or missing files.
- The global approval broker now persists pending requests and decisions, rehydrates them after restart, expires stale requests, and rejects late approvals safely.
- Hive side-effect recovery now accepts an optional provider/tool reconciliation callback: confirmed outcomes are committed to the durable effect ledger and replayed, while unknown outcomes remain fail-closed and never trigger duplicate execution.
- Durable V5 background jobs now renew heartbeats while running; stale jobs can be cancelled and requeued by the watchdog, which is invoked at each V5 run/stream boundary.
- V5 run cancellation intents now persist in `.nexus/run_cancellations.sqlite3`, are applied when a restarted loop registers the same turn, and are cleared after terminal unregister.
- V5 records the generated plan with the result and blocks completion when an active plan has zero distinctive lexical overlap with the user objective; this is a conservative guard, not semantic proof.
- Planned V5 turns now pass through the canonical evidence verifier before terminal persistence; missing action records for planned steps force a failed/incomplete result.
- Added `python -m nexus --supervise`, a cross-platform outer supervisor that probes API readiness, restarts bounded failures with backoff, and durably quarantines crash loops in `.nexus/supervisor_incident.json`.
- Quarantine incidents from the queue and outer supervisor can now use `NEXUS_ALERT_WEBHOOK_URL`; delivery is atomic, deduplicated, and retryable after a failed notification.
- Added authenticated `/metrics` Prometheus text exposition with queue, Hive, and supervisor health/quarantine gauges.
- Hive agents now reload durable pause/cancel control files at every safe boundary, so cancellation issued by another server process is honored without relying on in-memory state.
- V5 exposes `set_completion_evaluator(...)` for structured provider-backed semantic verification; configured evaluator failures and invalid verdicts fail closed, while the default remains deterministic evidence verification.
- MissionRunner can now receive a synchronous completion verifier. Queue success is no longer sufficient when configured: rejected or errored acceptance checks are durably recorded and follow the normal replan/block path, with worker summaries passed into the verifier.
- V5 background lanes now enforce priority at admission (serial by default), support explicit bounded parallelism, and preserve priority ordering during durable restart recovery.
- Durable background attempts now use atomic SQLite ownership tokens plus process-PID liveness fencing, preventing duplicate recovery and stale attempts from terminalizing a newer attempt; bounded aging prevents indefinite priority starvation.
- The outer `--supervise` mode now uses a durable singleton PID lock, rejects competing supervisors, and reclaims locks whose owner process is demonstrably dead.

## Remaining release gates

- Configure and validate a real deployment secret/auth setup; do not expose local anonymous mode.
- `/resume` was exercised through a live-loop integration probe; a provider-backed continuation should be smoke-tested again after deployment.
- Preserve the elevated/isolated test invocation in CI; the normal desktop sandbox can still produce `WinError 5` for pytest temp directories.
- Build and smoke-test both containers on a host with Docker.
- Docker/Podman is not installed in this workspace; the compose file was parsed statically but images were not built or run here.
- CI now runs the release gate, uses only development dependencies for the test matrix, and validates compose structure before the Docker build.
- Isolate intentional changes from generated artifacts before tagging a release.
- The current 3-case benchmark is a framework smoke gate, not a model-capability leaderboard; expand it with provider-backed SSE/tool/restart trials for a production performance baseline.
