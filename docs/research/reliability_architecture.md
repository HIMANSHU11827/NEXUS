# Nexus AI — Reliability Architecture & External-Framework Comparison

Date: 2026-08-17 · Scope: reliability core (`reliability/`), V5 loop integration, queue, capability hardening

## 1. What was built

| Layer | Module | Responsibility |
|---|---|---|
| Failure envelope | `reliability/failure.py` | Unified 30-class taxonomy (`FailureClass`), `FailureEnvelope` (idempotency keys, side-effect status, redaction, correlation ids), `envelope_from_exception` reusing `providers.reliability.classify_failure` with fallback heuristics. Classification never raises. |
| State machine | `reliability/states.py` | `RunState` (validated transitions via `TRANSITION_TABLE`), recorded history with reasons, atomic persistence, auto-resume on construction, `RunState.load` for explicit rebuilds. |
| Durable goals | `reliability/goal.py` | `GoalState` per session (plan steps, blockers, recovery history, completion evidence), atomic JSON `GoalStore`. The original goal is never replaced by the current error. |
| Recovery engine | `reliability/recovery.py` | Policy ladder: user-action-required → non-recoverable → component adapters → generic bounded ladder. Strategy freezing after identical repeated failures, component quarantine (persisted), bounded backoff, precise `next_action` on blocked states. |
| Stall detection | `reliability/progress.py` | Wall-clock idleness + repeated identical call/error signatures, time-injectable, persisted, per-run reset. |
| Observability | `reliability/observability.py` | Correlation-id ContextVar, structured logs, `emit_reliability_event` into the existing `work_event_sink`/SSE pipeline (new `EVENT_TYPES`: `goal.*`, `reliability.*`). |
| V5 integration | `orchestrators/v5/reliability.py` (`V5Reliability` mixin) | Mirrors every `_transition_to` into the validated machine; records stall guidance and honest stall envelopes; routes tool/provider failures through `_recovery_for_failure`; surfaces checkpoint failures; persists terminal goals with evidence. All methods fail-tolerant (never break the loop they protect). |
| Queue | `queue/driver.py` | Worker isolation via `asyncio.wait(FIRST_COMPLETED)`, per-worker quarantine, replacement workers with budget, honest all-quarantined failure. |
| Capability hardening | tools, registry, MCP adapter, memory, plugins | Bounded retry/backoff with jitter for web search and tool registry (env-tunable), MCP timeout guard, memory-forge never raises, plugin rollback guard. |

## 2. Design decisions (and why)

1. **Advisory observability, not control flow.** The mixin never changes loop control; invalid state transitions, recovery results, and checkpoint failures are surfaced but never thrown. Control flow stays in the loop's existing bounded mechanisms (repair budget, deadlines, permission gates). This keeps the 411-test V5 contract intact while making failures visible and durable.
2. **Checkpointing is the easy half; failure *detection* and *resumption policy* are the hard half.** The pre-existing `V5Checkpoint` already had atomic, locked, redacted snapshots. The gap was: no validated state story, no per-run stall detection, no durable goal, no recovery ladder, and no honest blocked states. This is exactly the gap the 2026 LangGraph/Temporal analysis describes ("checkpoints are not durable execution").
3. **Recovery strategy switching after *identical repeated* failures.** Each failure's signature is `component_type|component_id|operation|failure_class|error_code`; failed strategies are frozen per signature so the same mistake is never retried with the same approach.
4. **Per-run stall scoping.** Progress counters reset at run start (`_reset_progress`); otherwise a previous run's identical calls make a fresh run look stalled on round 0 (found by regression: `test_direct_loop_bounds_repeated_non_unavailable_failures`).
5. **Consistent attempt semantics.** `RecoveryResult.attempts` is the 1-based attempt number of the failure being decided (fixed an off-by-one that reported "attempt 2" for the first failure).
6. **Blocked ≠ dead.** Blocked goals stay active/resumable (`GoalStore.list_active` includes blocked); `run_context.set_intermediate_status` records `recovering`/`blocked`/`waiting_*` and `finish()` accepts them as starting states; abandoned blocked runs are retired by lease expiry.

## 3. Comparison matrix

| Dimension | Nexus (this work) | LangGraph checkpointer | Temporal / Dapr durable execution |
|---|---|---|---|
| Durability unit | Per-phase checkpoint + durable goal/state machine/progress/run-context (multiple layers) | Snapshot at superstep boundaries, keyed by `thread_id` | Event history; workflow replays deterministically |
| Failure detection | `recover_orphaned_runs` (lease + PID liveness), queue lease reap, stall tracker, heartbeat | None (you must detect) | Built into runtime |
| Failure classification | 30-class taxonomy + envelope (retryable/transient/security/user-action flags, redaction) | `RetryPolicy` per node (exponential backoff) only | Activity retry policies (attempts, backoff, non-retryable error types) |
| Strategy switching | Frozen strategies per failure signature after repeated identical failures | No fallback routing / DLQ / notification | Retry policy is fixed per activity; no signature-based strategy freezing |
| Blocked/human-in-loop | First-class states (`WAITING_FOR_PERMISSION`, `WAITING_FOR_CREDENTIALS`, `BLOCKED_NON_RECOVERABLE`), durable run-context status, resumable goals | `interrupt()` durable only with persistent checkpointer | Durable waits/signals (zero compute while parked) |
| Idempotency discipline | `idempotency_key` + `side_effect_status` on envelopes; queue `quarantine_uncertain` (never replay uncertain outcome); canonical task dedupe | `@task` records results; docs say "assume nodes re-execute" | Activities recommended idempotent; tool calls need idempotency keys |
| Duplicate-execution prevention | Lease fencing (SQLite `BEGIN IMMEDIATE`, token-checked ack), queue leases + heartbeat, run-context owner PID | None — two workers can resume one `thread_id` | Built-in (single logical workflow per id) |
| Stalled-run detection | Wall-clock + repeated-signature stall signals, model-visible hints, honest stall envelope after budget | None | Timers; no stall semantics |
| Cost model | Local-first, single process, no replay determinism requirement (LLM calls are inherently non-deterministic) | Framework-local, single process | Requires determinism: LLM/tool calls must be Activities (the "replay trap") |
| When to choose | Personal/local autonomous agent: seconds-to-minutes runs, one operator, needs honest failure + resumable state without infra | Short read-only reasoning graphs | Long-running, multi-worker, side-effect-heavy production workflows |

**Verdict.** Nexus's model — validated state machine + durable goals + signature-keyed recovery ladder + per-run stall detection + lease-based orphan recovery — is closer to "self-healing runtime" than a checkpointer alone, while avoiding durable-execution's determinism tax (appropriate for an LLM loop whose model calls cannot replay). The single most valuable missing piece, per both the external analysis and our own audit, is *per-round transcript/tool-result flushing* so a restart can restore a mid-turn runtime instead of fail-and-reprompt (see limitation audit).

## 4. Sources

- LangChain LangGraph docs: durability modes (`exit`/`async`/`sync`), `@task`, checkpointers at node boundaries.
- Temporal docs/blog (2026-07/08): LangGraph integration, Activity retries, durable waits, event-history replay; "model and tool calls run as Activities… a call in flight when the worker died retries from the start".
- Diagrid (2026-02): "Checkpoints are not durable execution" — no automatic failure detection, no resumption, no duplicate-execution prevention in LangGraph/CrewAI/ADK.
- Cordum comparison (2026-04): thresholds — ≤30 s single read-only step: framework alone; ≥3 external calls / hours-long pauses / production side effects: add durable orchestration; always keep a pre-dispatch governance gate.
- Repository audit: `docs/audits/reliability_adoption_audit.md`, `docs/audits/reliability_limitation_audit.md`, `docs/research/reliability_mission_report.md`.