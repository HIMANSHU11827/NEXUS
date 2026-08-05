# Lifecycle

Lifecycle management for NEXUS AI — per-entity state machines (skills, tools,
plugins, cron, self-improvement, memory) plus a component supervision layer
(startup/shutdown ordering, restart recovery, quarantine, persistence).

**Version:** 2.1.0

## Two layers

### 1. Per-entity lifecycle managers

Each manager implements a state machine over `LifecycleState`
(`CREATED / ACTIVE / STALE / ARCHIVED / DELETED / ERROR`) with valid
transitions, pre/post hooks, event history, and JSON persistence:

| Manager                     | Entity                    | Domain states                                                      |
|-----------------------------|---------------------------|--------------------------------------------------------------------|
| `SkillLifecycle`            | Skills                    | CREATED → ACTIVE ↔ STALE → ARCHIVED → DELETED                      |
| `ToolLifecycle`             | Tools                     | DISCOVERED → REGISTERED → ENABLED → DISABLED → DEPRECATED          |
| `PluginLifecycle`           | Plugins                   | DISCOVERED → LOADED → REGISTERED → RUNNING → STOPPED → UNLOADED    |
| `CronLifecycle`             | Cron tasks                | SCHEDULED → RUNNING → COMPLETED / FAILED / CANCELLED → RESCHEDULED |
| `SelfImprovementLifecycle`  | Improvement cycles        | IDLE → ANALYZING → LEARNING → APPLYING → EVALUATING → INTEGRATED   |
| `MemoryLifecycle`           | Memory records            | STORED → ACCESSED → CONSOLIDATED → ARCHIVED → EVICTED              |

All managers share the base `LifecycleManager` in `lifecycle/__init__.py`
(`register_entity`, `transition`, `get_events`, `get_stats` and the
`_persist_key`-driven persistence hook).

### 2. Component supervision layer (new in 2.1)

`lifecycle/supervisor.py` adds a coarse `LifecycleStage` machine on top of the
per-entity managers. It supervises whole components (database, cache, workers,
agents, ...) through:

    created -> initializing -> ready -> running <-> paused
    ready/running/paused -> stopping -> stopped
    failed/quarantined -> recovering -> ready      (restart recovery)
    start failure x3 -> quarantined

- `ComponentSupervisor.register(id, name, after=[], cooldown=5.0)` — register a
  component. Re-registering preserves the current stage.
- `mark_stage(id, stage)` — validated transitions; illegal transitions raise
  `StageTransitionError` with a reason (no ghost states). Use `try_mark_stage`
  for a non-raising `(ok, reason)` form, and `may_transition` /
  `transition_reason` for read-only checks.
- `startup(components)` / `shutdown(components)` (async) — start in declared
  `after=` dependency order, stop in reverse, each step timed. Async component
  calls are bounded by `asyncio.wait_for` (default 10s); sync calls run
  directly. A failing component is marked `failed` and startup/shutdown
  continues; `MAX_START_FAILURES` (3) consecutive start failures quarantine it.
- `restart(id, check=None)` (async) — moves failed/quarantined components
  through `recovering` → `ready`. With a readiness `check`, recovery only
  completes after the component's cooldown once the check passes; without a
  check, recovery is immediate.
- Persistence (via `lifecycle/persistence.py`) — every stage transition is
  saved under `~/.nexus/lifecycle/` so a process restart restores the
  last-known stages. Pass `persist=False` or a custom `persist_key` for
  isolated/embedded use.
- `get_component_supervisor()` — module-level accessor for the shared
  supervisor instance. Exported from `lifecycle` along with `LifecycleStage`,
  `StageTransitionError`, and `ComponentSupervisor`.

## Persistence

State files live under `~/.nexus/lifecycle/<key>.json`. Writes and reads are
best-effort: any IO failure is a silent fallback (in-memory operation
continues), so persistence can never crash a lifecycle operation.

## Notes

- Startup/shutdown ordering lives in the `ComponentSupervisor` layer. The
  per-entity managers do NOT provide agent lifecycle hooks or session state
  transitions; supervisor components are the unit of startup/teardown.
