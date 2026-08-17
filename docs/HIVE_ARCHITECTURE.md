# Nexus Hive — Architecture Reference

This document describes the **as-built** Nexus Hive architecture after the
capability-boundary, Agent Team, and specialization work. It is the source of
truth for the structure; code wins over prose when they disagree.

## 1. Boundary principle (mandatory)

```
Nexus Main Agent  (OUTSIDE Hive)
        │  gives goal / task / responsibility
        ▼
   ┌─────────────────────────────────────┐
   │  HiveCapability  (the boundary)      │   hive/capability.py
   │  - submit_goal / plan_and_execute    │
   │  - get_run / list_runs / pause /     │
   │    resume / cancel / restore         │
   │  - builds Agent Team + execution plan │
   └───────────────┬─────────────────────┘
                   │  one or more execution plans
                   ▼
   ┌─────────────────────────────────────┐
   │  NexusHiveEngine  (runtime)          │   hive/engine.py
   │  - real LLM tool-loops per agent     │
   │  - per-agent checkpoints             │
   │  - idempotent effect ledger          │
   │  - dependency waves (sequential)     │
   │  - parallel groups                   │
   │  - generation-fenced cancellation    │
   │  - quorum + consolidation            │
   └─────────────────────────────────────┘
```

The main agent is **never** a Hive member, supervisor, worker, or internal agent.

## 2. Module map

| File | Responsibility |
|------|----------------|
| `hive/__init__.py` | Public surface: re-exports boundary, models, teams, specializations, capabilities. |
| `hive/models.py` | Typed contract: `HiveRequest`, `HiveRunSummary`, `HiveAgentSpec`, `AgentTeamSpec`, `TaskSpec`, `MessageSpec`, enums (`AgentCategory`, `CapabilityMode`, `ConnectionMode`, `TaskState`, `HiveRunStatus`, `HealthStatus`), task-transition table. |
| `hive/specializations.py` | Plug-and-play specialization registry (184 roles) + `register_specialization`, `get_specialization`, `list_specializations`. |
| `hive/capabilities.py` | Capability inheritance resolver (`resolve`) + privilege-escalation guard (`assert_no_escalation`). |
| `hive/teams.py` | Agent Team spec, reusable templates, `TeamBuilder` (request → execution plan), plug-and-play team registry (`register/get/clone/delete/export/import_team_template`). |
| `hive/capability.py` | `HiveCapability` — the main-agent boundary facade; persistence + restart recovery. |
| `hive/engine.py` | `NexusHiveEngine` + `SubAgent` — the real execution runtime (pre-existing, extended with category/specialization/capabilities). |
| `hive/state.py` | Agent/task runtime state structures. |
| `hive/effects.py` | Idempotent effect ledger. |

## 3. Data flow for one run

1. Main agent builds a `HiveRequest` (goal, specializations, budgets, limits,
   capability mode, connection mode, ...).
2. `HiveCapability.submit_goal` persists the request and builds an Agent Team via
   `TeamBuilder` (template match → clone, or dynamic synthesis from
   `required_specializations`). Returns a `HiveRunSummary` (status `planned`).
3. `execute_run` turns the team into an **execution plan**: an ordered list of
   stages, each `sequential` (one agent) or `parallel` (a group). Each sequential
   stage runs, and its result is threaded into the next stage's prompt
   (`context[prev_spec] = result`) — this is genuine sequential handoff. Parallel
   stages run concurrently via `engine.spawn_hive`.
4. Each agent's per-agent `CapabilitySpec` is injected into its `SubAgent`
   (specialization + category surfaced in the system prompt).
5. When the plan finishes, `HiveCapability` aggregates: collects all agent
   outputs, counts success/failure, records errors, and sets status
   (`completed` / `failed` / `partial`).
6. The main agent reads `HiveRunSummary.verification_result` and
   `final_result`.

## 4. Capability inheritance (§14)

`resolve(mode, available, **opts)` returns a `CapabilitySpec`:

- `full` → all available tools/skills/... minus `RESTRICTED_BY_DEFAULT`
  (`write`, `terminal`, `edit`, ...). No silent escalation.
- `selected` → only the explicit `CapabilitySpec` passed in.
- `role_based` → the specialization's declared `capabilities` (falling back to a
  safe default set capped by what is available).
- `custom` → the explicit spec verbatim.
- `restricted` → read-only / minimal set.

`assert_no_escalation(resolved, security_limits)` raises `CapabilityError` if the
resolved set contains anything outside the main agent's available capabilities or
inside an explicit security deny-list. This is enforced at plan time inside
`HiveCapability`.

## 5. Agent Team model

`AgentTeamSpec` carries: team_id, name, goal, workflow, agents, coordinator,
shared capabilities, budgets, `failure_policy`, `reporting_policy`,
`loop_policy` (for continuous/24/7), `continuous` flag, version.

Built-in templates (8): `software_development`, `research`, `security_audit`,
`documentation`, `incident_response`, `deployment`, `ui_redesign`,
`continuous_maintenance`. All are plug-and-play: clone, edit, delete, export,
import via the registry functions.

## 6. Failure & recovery

- **Per-agent failure isolation**: a failed agent is recorded in
  `run.errors` (`code="hive.agent_failed"`) and `failure_policy` decides whether
  the run fails, continues, or dead-letters the task. The whole Hive does not
  crash.
- **Engine-level**: per-agent checkpoints, idempotent effect ledger (no double
  application on re-run), generation-fenced cancellation (safe to stop mid-turn),
  dependency waves, quorum + consolidation.
- **Run-level persistence**: `HiveCapability` saves every run summary + team to
  `root/runs/<id>.json`. `recover_interrupted` reloads them; a run persisted as
  `running`/`paused` is marked `interrupted` on recovery, while a `planned` run is
  simply reloaded.

## 6b. Dynamic-creation limits (§20)

`TeamBuilder.validate_limits` is called inside `build()` and enforces, before any
agent is spawned:

- **max_agents** — the team is trimmed (parallel agents first) to the cap.
- **max_parallel_agents** — a soft warning; the engine serialises over the cap.
- **max_subagent_depth** — hard cap of 4 (prevents unbounded recursive spawning).
- **Privilege-escalation rejection** — if an agent explicitly requests a
  capability (tool/skill/plugin/mcp/model/provider/permission) that is not in
  the main agent's `available_capabilities` or is in the operator
  `permission_limits` deny-list, `build()` raises `ValueError`. Agents without
  explicit caps are safe because `resolve()` already caps them to `available`.

## 6c. Controlled continuous / 24-7 loop (§17, §19)

`HiveCapability.run_continuous(run_id)` drives the team plan repeatedly under the
team's `LoopPolicy`. Each iteration replays the staged plan (real parallel +
sequential execution). Safety gates checked every iteration:

- pause (status `paused` → break), cancel (dedicated cancel marker → `cancelled`),
- `max_iterations`, `max_runtime_seconds`, `max_failures` (consecutive),
- `no_progress_threshold_seconds` (resets on any successful iteration),
- a checkpoint entry written every `checkpoint_every_iterations` iterations so a
  process restart can resume without duplicating completed work.

The loop is durable and operator-controllable, **not** an unsafe infinite loop.
HTTP: `POST /api/hive/runs/{id}/continuous`.

## 7. Decisions & evidence

- **Reuse the existing engine rather than rebuild.** The pre-existing
  `NexusHiveEngine` already provides real parallelism, sequential dependency
  waves, cancellation, checkpoints, and quorum. Rebuilding would discard working,
  tested code. We extended it (category/specialization/capabilities on `SubAgent`)
  and built the missing *boundary* + *team* + *specialization* layers on top.
- **"Agent Team" = preferred term.** Older "workflow team" naming is the same
  concept; we standardize on Agent Team at the capability layer.
- **Capability inheritance is resolution, not grant.** Hive can only assign what
  the main agent exposes; an escalation guard makes privilege escalation
  impossible by construction.
- **Sequential handoff via context threading**, not just ordering — each stage's
  verified output is passed to the next stage's prompt, so dependent stages are
  genuinely gated on prior results.

## 8. Remaining work (honest status)

- Sub-agent depth limits are modeled in the dynamic-creation guard and the
  request contract; the engine's spawn path is expected to honour the same
  ceiling when agents spawn sub-agents (route exists, end-to-end enforcement
  pending).
- Per-agent MCP/plugin capability filtering at the engine boundary
  (modeled in `CapabilitySpec`; engine already accepts `tool_registry`/tools).
- Richer multi-team orchestration when a single team is insufficient.
- GUI/TUI panels that render `HiveRunSummary` live (CLI `/hiveteam` and HTTP
  endpoints exist; rich UI panels are future work).
