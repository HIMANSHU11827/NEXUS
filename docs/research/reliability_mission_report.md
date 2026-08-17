# Nexus AI — Reliability Mission Report

Date: 2026-08-17 · Goal: transform Nexus into a persistent, self-healing agent runtime.

## 1. Outcome

Every change is verified by tests. Full battery: **599 passed, 0 failed** (below). No regressions in the pre-existing V5 contract (411 tests unchanged and green).

## 2. What changed

### New: reliability core (`reliability/`)
- `failure.py` — 30-class `FailureClass` taxonomy, `FailureEnvelope` (redaction, idempotency keys, side-effect status, retryable/transient/security flags), `envelope_from_exception` reusing `providers.reliability.classify_failure`; classification never raises.
- `states.py` — `RunState` validated `TRANSITION_TABLE`, recorded transitions with reasons, atomic persistence, **auto-resume from disk on construction**.
- `goal.py` — durable `GoalState`/`GoalStore` (plan steps, blockers, recovery history, completion evidence); blocked goals stay active (resumable); tolerant deserialization.
- `recovery.py` — `RecoveryEngine`: user-action → non-recoverable → adapters → generic bounded ladder; **strategy freezing per failure signature**; persisted quarantine; consistent attempt semantics (off-by-one fixed); precise `next_action` on blocked states.
- `progress.py` — wall-clock + repeated-signature stall detection, time-injectable, persisted.
- `observability.py` — correlation ids, structured logs, events into the SSE pipeline.

### V5 loop integration
- `orchestrators/v5/reliability.py` — `V5Reliability` mixin: state-machine mirroring, durable goals per session, recovery routing, stall hints + honest stall envelopes, checkpoint-failure surfacing, terminal-goal persistence with evidence. Every method fail-tolerant.
- `core.py` — `V5LoopState` extended with `RECOVERING/REPLANNING/DEGRADED/WAITING_*/BLOCKED_NON_RECOVERABLE/PARTIALLY_COMPLETED`; `_transition_to` now mirrors, records progress, surfaces checkpoint failures, persists terminal goals.
- `direct_loop.py` — stall detection at round top; per-tool progress recording + recovery events; provider-failure recovery hook; per-run stall reset.
- `retry.py` — enforcement retries with exponential backoff + jitter (`NEXUS_PLAN_RETRY_BACKOFF_BASE/MAX`).
- `nexus/run_context.py` — `set_intermediate_status` (`recovering`/`blocked`/`waiting_*`/`degraded`/`paused`); `finish()` accepts intermediate starting states.
- `nexus/events.py` — new `EVENT_TYPES` (`goal.*`, `reliability.*`).

### Queue worker isolation (`queue/driver.py`)
Worker supervision now isolates crashed workers (`asyncio.wait(FIRST_COMPLETED)`, per-worker quarantine, replacement workers with `NEXUS_QUEUE_WORKER_REPLACEMENTS` budget, honest all-quarantined failure). Companion tests: `tests/test_queue_worker_isolation.py`.

### Capability hardening
- `tools/web_search` — bounded retry/backoff+jitter for transient failures (SSRF guard untouched).
- `tools/nexus_tools/registry.py` — env-tunable retry defaults + backoff.
- `mcp_adapter.py` — per-call timeout guard (fixed a missing-import bug).
- `memory/__init__.py` — forge failures logged, never raise (fixed a `self`-param bug).
- `plugins/manager.py` — rollback guard when context creation fails.

## 3. Verification (all runs on this machine, pytest 9.1.1, Python 3.14.7)

| Suite | Result |
|---|---|
| `tests/test_reliability/` (new, 5 files) | 89 passed |
| `tests/test_reliability_integration/` (new: loop integration, retry/run-context, **chaos injection**) | 28 passed |
| `tests/test_reliability_capabilities/` (new) | 25 passed |
| `tests/v5/` (pre-existing contract) | **411 passed — no regression** |
| `tests/test_queue_driver.py test_queue_worker_isolation.py test_run_context_recovery.py test_supervisor.py test_hive_control.py test_planning_work_items.py` | 46 passed |
| **Total** | **599 passed, 0 failed** |

Chaos injections cover: provider outage → failover adapter; network partition → bounded block with resume path; MCP disconnect → reconnect strategy (no quarantine); worker crash → reclaim+restart; repeated identical failures → escalate to blocked with frozen strategy; non-recoverable → resumable blocked state; restart/resumption for state machine, goal, strategy history, and quarantine.

## 4. Bugs found and fixed during the work

- `RecoveryEngine` attempt double-count (+1 twice) — reported "attempt 2" for a first failure.
- `RunStateMachine` constructor ignored persisted state — restarts always began at INITIALIZING.
- `GoalState.from_dict` crashed on non-dict blockers/history entries.
- Progress tracker persisted call counters forever — a new run on the same session instantly looked stalled (regression caught by `test_direct_loop_bounds_repeated_non_unavailable_failures`; fixed with per-run `_reset_progress`).
- Pre-existing: `mcp_adapter.py` missing `import os` (NameError), `memory/__init__.py` wrong `self` param on `_run_memory_forge`.

## 5. Remaining limitations (documented, not hidden)

See `docs/audits/reliability_limitation_audit.md` and `docs/audits/reliability_adoption_audit.md`:

- Tool results (normal size) not durably flushed mid-round; `_checkpoint_resume` and `set_intermediate_status` not yet wired into live paths (restart = fail-and-reprompt).
- 7 of 13 subsystems still unwired to the envelope (`tools/nexus_tools/result.py::classify_error` duplicates classification); 104 silent-swallow sites remain (largest: skills 32, gateway 28, providers 14).
- Worker quarantine in-memory only; todo.md/TODO.md casing mismatch; dual `FailureClass` taxonomies (provider 12 vs reliability 30).
- Intentional: 1M-round cap, permission gates, SSRF fail-closed, no Temporal-style determinism replay.

## 6. Files touched (new: *)

- `reliability/*` (7 files)* · `tests/test_reliability/*` (5)* · `tests/test_reliability_integration/*` (3)* · `tests/test_reliability_capabilities/*` (25)*
- `orchestrators/v5/{core,reliability*,direct_loop,retry}.py` · `nexus/{run_context,events}.py`
- `queue/driver.py` · `tools/web_search/scripts/web_search.py` · `tools/web_search/web_search.jsnol` · `tools/nexus_tools/{registry,mcp_adapter}.py` · `memory/__init__.py` · `plugins/manager.py`
- `tests/test_queue_worker_isolation.py`* · `tests/test_queue_driver.py`
- Docs (this report + architecture + 2 audits)*

Nothing was committed; the tree contains the user's own uncommitted work, preserved untouched (baseline HEAD in `.baseline_commit.txt`).