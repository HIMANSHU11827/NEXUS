# automation — Scheduling and automation engine

## Authoritative implementation
- `src/nexus/tasks/scheduler.py` — `NexusTaskScheduler`: persisted one-shot scheduler with bounded retry and restart recovery (state via `NEXUS_SCHEDULER_STATE_PATH`)
- `src/nexus/lifecycle/managers/cron_lifecycle.py` — `CronLifecycle`: cron task state machine (`SCHEDULED → RUNNING → COMPLETED/FAILED/CANCELLED → RESCHEDULED`, any state → `ERROR`) with versioning
- `queues/driver.py` — `QueueDriver`: always-on 24/7 worker pool that leases tasks from the durable SQLite `TaskQueue` and runs each through `NexusLoop`; standalone: `python -m queue.driver --workers 2`

## Why this directory exists
This is the approved home for scheduling/automation ownership. The implementations live in `src/nexus/tasks/`, `src/nexus/lifecycle/managers/`, and `queues/`; `automation/` holds the responsibility map and docs.

## Notes
Cron lifecycle versioning: default `1.0`, `improve` bumps minor, `major_upgrade` bumps major.