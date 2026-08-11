# Nexus runtime capability matrix

This is the 50-item reliability and agent-runtime backlog used for the current
Nexus upgrade. It separates capabilities already present from gaps that still
need implementation, so “24/7” is not treated as a claim without an observed
test. Items are ordered roughly by impact on lost work and safe unattended use.

| # | Capability | Current state |
|---:|---|---|
| 1 | Durable task queue | Present; SQLite leases; immutable per-attempt receipts/effect reconciliation remain the next gap |
| 2 | Atomic task leasing | Present; concurrency tested |
| 3 | Idempotent enqueue | Present; tested |
| 4 | Lease heartbeat renewal | Present; tested |
| 5 | Startup orphan-lease reaping | Present; tested |
| 6 | Task retry with attempt limits | Present |
| 7 | Mission milestone hydration | Present; restart tested |
| 8 | Canonical run identity | Present |
| 9 | Run heartbeat lease | Present |
| 10 | Orphaned run detection | Present |
| 11 | Phase checkpoints | Present |
| 12 | Interactive checkpoint resume | Present |
| 13 | Queue worker crash supervision | Implemented in this pass; regression tested |
| 14 | Desktop child-process watchdog | Implemented in this pass; opt-out available |
| 15 | Opt-in Hive startup auto-resume | Implemented in this pass |
| 16 | Durable Hive event projection | Implemented in this pass |
| 17 | Hive task-level checkpoints | Improved; durable V5 state records agent lifecycle, and restart resume now reuses saved agent IDs to hydrate transcript/tool-call checkpoints with task validation |
| 18 | Hive retry policy per agent | Implemented; stable agent identity with bounded retry/backoff and lifecycle events |
| 19 | Hive dependency graph | Implemented as optional index-based dependency waves; cyclic plans fail closed |
| 20 | Hive quorum/consensus policy | Implemented; deterministic vote extraction, thresholds, required personas, and fail-closed consolidation option |
| 21 | Hive duplicate-side-effect guard | Partial; durable effect ledger replays completed effects, refuses live duplicates, and now supports an optional provider/tool reconciliation hook; provider-specific lookups remain |
| 22 | Hive priority lanes | Implemented for V5 background admission; lanes are bounded (serial by default), choose lower priority then FIFO with bounded aging, support explicit parallel limits, and rehydrate in persisted priority order |
| 23 | Hive resource budgets | Improved; optional engine-wide concurrency, per-agent step/retry budgets, and shared aggregate inference-step budget (`NEXUS_HIVE_MAX_TOTAL_STEPS`) |
| 24 | Hive cancellation tokens | Improved; `cancel_hive()` now publishes the durable cancelled control before awaiting local workers, and agents reload it at safe boundaries; broader distributed token fan-out and non-cooperative provider termination remain |
| 25 | Hive pause/resume | Implemented; durable control file and cooperative safe-boundary resume |
| 26 | Hive dead-agent replacement | Implemented; supervisor restarts stale-heartbeat agents with checkpoint identity preserved |
| 27 | Hive blackboard persistence | Implemented; SQLite-backed values with versions and optimistic conflict detection |
| 28 | Hive artifact manifest | Implemented; durable fingerprints reconcile present, changed, and missing files |
| 29 | Scheduled/cron task persistence | Implemented in this pass; restart/retry tested |
| 30 | Background task persistence | Improved; opt-in SQLite ledger and factory-based rehydration now use platform-aware owner-process liveness checks with atomic owner/attempt fencing, while ephemeral jobs remain process-local |
| 31 | Background task restart policy | Implemented for opted-in durable jobs; bounded retry/backoff and startup recovery |
| 32 | Stalled-loop watchdog | Partial; durable jobs renew heartbeats and can be cancelled/requeued on stale heartbeat at V5 turn boundaries; continuous external polling remains |
| 33 | Provider circuit breakers | Present |
| 34 | Provider fallback routing | Present |
| 35 | Tool timeout enforcement | Present in V5 background runner |
| 36 | Tool retry with classification | Present |
| 37 | Tool idempotency keys | Partial; queue/mission enqueue keys and terminal-result guards present; provider/tool effect receipts remain |
| 38 | Approval recovery after restart | Implemented; global broker persists pending/decided/expired requests with stable IDs and safe late-decision rejection |
| 39 | Event log append atomicity | Present |
| 40 | Event replay after reconnect | Present via SSE/polling |
| 41 | Event gap detection | Implemented; replay endpoint reports retention gaps and missing sequence range |
| 42 | Event backpressure controls | Partial |
| 43 | Context compaction budget | Improved; exact character-envelope admission and final fitting prevent floored-estimate bypasses |
| 44 | Context continuity memory | Present |
| 45 | User-direction drift detector | Partial; deterministic objective-anchor check blocks zero-overlap active plans and reports missing anchors; semantic/provider-backed evaluation remains |
| 46 | Goal completion verifier | Improved: active plans require action evidence, V5 exposes an optional semantic evaluator, and durable MissionRunner reconciliation now supports a fail-closed completion verifier that records its verdict and replans queue-successful milestones when acceptance evidence is rejected; verifier policy/configuration remains deployment-specific |
| 47 | Structured progress contract | Present in canonical events |
| 48 | Health/readiness endpoints | Present |
| 49 | Metrics and alert export | Partial; `/api/metrics` JSON and Prometheus-compatible `/metrics` expose queue/Hive/supervisor health plus opt-in deduplicated webhook alerts; richer labels/exporters remain |
| 50 | Crash-loop quarantine and operator alert | Partial; embedded queue/Hive supervisors and the cross-platform API supervisor persist bounded crash recovery, use a durable singleton PID lock, quarantine state, and opt-in deduplicated webhook alerts; paging integrations remain |

## Current rollout rule

The high-risk items are implemented in waves with a focused regression test,
then a full-suite run. Auto-resume is opt-in (`NEXUS_HIVE_AUTO_RESUME=true`)
until Hive task idempotency and side-effect reconciliation are implemented and
verified. The desktop launcher watchdog is enabled by default; pass
`-NoWatchdog` for an intentional one-shot developer run.

The server cron API now uses the project `.nexus_queue.db` tables
`cron_jobs`/`cron_runs`; manual runs enqueue real durable queue tasks and the
server tick materializes due interval slots. The API can own an embedded,
supervised queue worker when `NEXUS_EMBED_QUEUE_DRIVER=true` (the project
`run.ps1` launcher enables this by default); scaled deployments may disable it
with `-NoWorker` and run `python -m nexus --autonomous` separately. The API
health endpoint fails closed when its embedded worker is configured but stopped.

The legacy one-shot V5 scheduler now normalizes orphaned `running` entries on
startup and retries them immediately after a process restart; its state file
also works when configured as a filename without a parent directory.

The control-plane outbox now supports atomic publisher leases,
acknowledgement, and release-for-retry. This prevents two publisher processes
from claiming the same event and lets a crashed publisher lease expire safely.

The gateway now has that delivery ledger: responses are persisted before
sending, claimed with expiring leases, acknowledged on adapter success, and
returned to retryable state after failures. Live resume also uses an exclusive
durable claim file, preventing a successful checkpoint from being dispatched
twice while allowing stale crash claims to recover.

The embedded queue supervisor records repeated failures in
`.nexus/queue_driver_incident.json` and quarantines after the configured crash
window (`NEXUS_QUEUE_MAX_RESTARTS`, `NEXUS_QUEUE_CRASH_WINDOW`). Set
`NEXUS_QUEUE_CLEAR_QUARANTINE=true` for an explicit operator recovery after
fixing the underlying cause; the incident is also exposed by `/api/metrics`.
