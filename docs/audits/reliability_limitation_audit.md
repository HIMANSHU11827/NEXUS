# Nexus AI — Reliability Limitation Audit (persistence & resume surfaces)

Date: 2026-08-17 · Read-only audit of what is durable, what is not, and where a process death loses state.

## Already durable

| Surface | Mechanism | Evidence |
|---|---|---|
| User + final assistant messages | Session JSON (`logs/sessions/<session>.json`), atomic write | `core.py:714-724, 1568-1602` |
| Assistant tool-call blocks | `_persist_direct_message` flushed before tools ("a crash cannot erase the exact model decision") | `core.py:1604-1651`, `direct_loop.py:1590-1601` |
| Per-phase checkpoints | Atomic temp+fsync+`os.replace`, sqlite interprocess lock, redacted, pruned to 200 | `orchestrators/v5/checkpoint.py:141-310` |
| Run context | Lease + heartbeat + orphan retirement (`logs/run_contexts/`), atomic + interprocess lock | `nexus/run_context.py`; wiring `core.py:2329-2398` |
| Queue tasks | SQLite WAL, leases with tokens, heartbeat, boot reaping of expired leases, canonical dedupe, `quarantine_uncertain` (never replay uncertain outcome) | `queue/store.py`, `queue/driver.py:577-597, 387-572, 283-353` |
| Plans | `workspace/todo.md` + control-plane plans; plan discarded unless persisted | `tools/nexus_tools/planning/scripts/planning.py:140-147` |
| Goals / state machine / progress | `.nexus_v5/{goals,state_machine,progress}/` (new) | `orchestrators/v5/reliability.py:61-74` |

## Not durable / not wired (the real gaps)

1. **Tool results (normal size) are never durably flushed mid-round.** Appended only to the local `messages` list (`direct_loop.py:1726-1745`); they survive only via the next checkpoint's 12-message tail. Oversized results are archived, small ones are not. **Most important gap.**
2. **`_checkpoint_resume` has zero production callers.** Restart resume today = prompt-level evidence injection gated on "continue/resume" keywords (`core.py:2653-2674`), and `recover_orphaned_runs` retires the interrupted run as `failed`. The durable goal is fail-and-reprompt, not state restoration.
3. **`set_intermediate_status` has zero production callers.** The `recovering`/`blocked`/`waiting_*` surface exists and is tested, but the loop does not yet publish intermediate statuses during long waits/recoveries.
4. **Worker quarantine is in-memory only** (`queue/driver.py:133`); a restart forgets quarantined workers.
5. **Case mismatch:** continuity reads `workspace/todo.md` (`continuity.py:130`) while `core.py:1440` reads `workspace/TODO.md`.

## Mid-round loss windows (file:line)

1. **Model call** — crash during `_prompt_too_long_retry` (`direct_loop.py:1418`) loses the round's model output (last checkpoint is from round start, `:1257`).
2. **Tool execution** — `direct_loop.py:1620-1745`: crash mid-tool loses the result unless oversized (`:893` archive path).
3. **Between assistant flush and tool side effect** — `direct_loop.py:1590-1601` then `:1620+`: orphaned call; next process reconstructs with `UNKNOWN:` placeholder (`:1154-1167`) — evidence-preserving, not state-restoring.
4. **Terminal sequence** — `core.py:2788` (terminal checkpoint) then `:2802` (`finish_run_context`): crash in between leaves checkpoint `completed` but run context `running`, later retired as failed (`run_context.py:426`) — the durable record contradicts itself.
5. **Stamped-but-not-written transcript tail** — `_stamp_recent_messages` (`direct_loop.py:999-1005`) persists only at the next `_checkpoint_save`.
6. **Checkpoint write itself** — save failure is surfaced (`_checkpoint_failed`) but never retried; staleness (previous phase snapshot) is acceptable.

## Intentional / accepted limits

- 1M-round hard cap and permission gates remain the outer bounds (mission §5, §12); recovery never bypasses them.
- SSRF guard stays fail-closed in `web_search`; retry only touches transient transport failures.
- Secret redaction is applied at envelope creation, checkpoint write, and queue store; no new secret surfaces.
- Reliability components degrade to disabled (`_reliability_disabled`) rather than breaking the loop on storage failure.
- Determinism tax of durable-execution engines (Temporal-style replay) is deliberately avoided — model calls cannot replay; signature-keyed recovery + durable state is the chosen model (see `docs/research/reliability_architecture.md`).

## Recommended follow-ups (not done in this mission)

- Per-round transcript/tool-result flush (closes windows 1-3, 5).
- Wire `_checkpoint_resume` + `set_intermediate_status` into the live loop so a restart restores a mid-turn runtime and long waits publish their status.
- Persist worker quarantine; fix the todo.md/TODO.md casing mismatch; retry failed checkpoint saves once.
- Make the terminal sequence atomic (checkpoint + run-context retirement in one durable step).