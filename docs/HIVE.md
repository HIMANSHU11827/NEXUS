# Nexus Hive

> **Hive is a plug-and-play multi-agent orchestration capability used by the Nexus main agent.**

The Nexus **main agent is outside Hive**. The main agent has and uses Hive as one
of its capabilities (alongside Tools, Skills, Plugins, MCP, Memory, Models/Providers,
etc.). The main agent hands Hive a **goal**, **task**, or **long-running
responsibility**. Hive then creates or selects its own agents, organizes them into
**Agent Teams**, assigns capabilities and work, runs them sequentially or in
parallel, monitors their progress, handles failures, and returns a **verified
result** to the main agent.

```
Nexus Main Agent
├── Tools
├── Skills
├── Plugins
├── MCP
├── Memory
├── Models and Providers
└── Hive   <-- capability used by the main agent (NOT a container for it)
```

## What Hive is NOT

- The Nexus main agent
- A single AI agent or a model
- A provider or a tool executor
- A skill, plugin, or MCP server
- A simple task list, subprocess launcher, or parallel loop
- An uncontrolled infinite loop

Hive is a complete Nexus capability for creating and operating multiple real AI agents.

## Core concepts (preferred terminology)

| Term | Meaning |
|------|---------|
| **Agent Team** | A reusable group of agents working toward one shared goal. ("Workflow team" is the same older concept; Agent Team is the preferred term.) |
| **Parallel Agents** | Multiple agents executing simultaneously (concurrency-controlled, cancellable). |
| **Sequential Agents** | Agents executing in a defined, dependency-ordered sequence. |
| **Specialized Agents** | Dedicated agents configured for one responsibility (coding, security, testing, research, ...). 184 built-in specializations ship in `hive/specializations.py`. |
| **Sub-agents** | Agents created/delegated by another Hive agent for a smaller piece of work (may themselves be parallel/sequential/temporary). |

The categories **overlap intentionally** — an Agent Team may contain specialized
agents that run in parallel groups and sequential stages, and any agent may spawn
sub-agents. See `docs/HIVE_ARCHITECTURE.md` for the full type system.

## How the main agent uses Hive

There are three layers:

1. **Capability boundary (`hive.capability.HiveCapability`)** — the clean, typed
   interface the main agent uses. Submit a `HiveRequest`, receive a `HiveRunSummary`,
   then control the run (pause/resume/cancel/restore) and read its aggregated result.
   The main agent is never part of Hive's internal agent graph.

2. **Agent Team system (`hive.teams`)** — turns a request into a concrete execution
   plan (ordered stages of sequential agents and parallel agent groups), using
   reusable templates and the specialization library.

3. **Runtime engine (`hive.engine.NexusHiveEngine`)** — executes the agents with
   real LLM tool-loops, per-agent checkpoints, durable effect ledger, dependency
   waves, quorum, and generation-fenced cancellation.

### Programmatic

```python
from hive import HiveCapability, HiveRequest

cap = HiveCapability(root="./hive_runs", available_capabilities={...}, llm_call=my_llm)
summary = await cap.plan_and_execute(
    HiveRequest(goal="Build a feature", required_specializations=["BACKEND_AGENT", "TESTER"])
)
print(summary.status, summary.verification_result)
```

### HTTP (server)

- `POST /api/hive/goal` — submit a goal (set `execute:true` to run immediately).
- `GET  /api/hive/runs` — list Hive runs.
- `POST /api/hive/runs/{id}/cancel` — cancel a run.
- `GET  /api/hive/teams` — list reusable Agent Team templates.

### CLI

- `/hive` — active sub-agent/hive status (runtime engine).
- `/hiveteam` — list reusable Agent Team templates.

## Capability inheritance modes (§14)

Per agent, Hive resolves the concrete capability set from the main agent's
available capabilities using one of:

- **full** — inherit everything except restricted-by-default capabilities.
- **selected** — only explicitly listed tools/skills/plugins/mcp/providers/models.
- **role_based** — capabilities defined by the agent's specialization.
- **custom** — an explicit, fully specified capability assignment.
- **restricted** — a minimal read-only/locked-down set.

A hard **privilege-escalation guard** (`hive.capabilities.assert_no_escalation`)
forbids granting any capability the main agent did not expose, and keeps
write/terminal edit-class tools out of `full` mode by default.

## Feature status

| Feature | Status |
|---------|--------|
| Sub-agent runtime with real LLM tool-loops | Stable |
| Per-agent checkpoints + durable effect ledger | Stable |
| Pause / resume / cancel | Stable |
| Dependency waves (sequential execution) | Stable |
| Parallel agent groups (real concurrency) | Stable |
| Capability boundary (`HiveCapability`) | New (this revision) |
| Agent Team templates + builder | New (this revision) |
| Specialization library (184 roles) | New (this revision) |
| Capability inheritance modes + escalation guard | New (this revision) |
| Persistence + restart recovery | Stable (run-level) |
| Failure isolation (one agent failing ≠ whole Hive dies) | Stable |
| HTTP + CLI surfaces | New (this revision) |
| Result aggregation / verification summary | Stable (basic) |
| **Dynamic-creation limit enforcement (§20)** | **New (this revision)** — max_agents trim, parallel-agent cap, escalation rejection |
| **Controlled continuous / 24/7 loop runner (§17/§19)** | **New (this revision)** — `run_continuous` with iteration/runtime/failure/no-progress bounds, checkpoints, pause/cancel/resume |
| Sub-agent delegation from inside Hive | Partial (route exists; depth limits wired but not yet enforced in engine) |
| Long-running 24/7 loop policy on teams | Partial (team schema + builder policy exist; loop driver not yet wired to engine) |
| MCP / plugin per-agent filtering at runtime | Partial (modeled in capability spec; engine wires tools/registry passed in) |

## Known limitations

- The engine still refers to spawned agents as **sub-agents**; at the capability
  layer these are first-class **Hive agents** organized into **Agent Teams**.
- `required_specializations` drives dynamic team synthesis; richer dynamic
  multi-team orchestration is planned, not yet implemented.
- Continuous/24/7 loop execution is modeled in the team schema and builder but is
  not yet driven by a persistent scheduler inside Hive.

See `docs/HIVE_ARCHITECTURE.md` for the full design, data model, and decision log.
