# Nexus Runtime Map — Verified 2026-08-17

Concise map of the real Nexus runtime as traced in the working tree. Every
component's status was verified by reading its entry points and (where noted)
by the passing test suite (full run: 2544 passed / 1 failed / 15 skipped).

## 1. Runtime entry points

| Interface | Entry | Runtime path |
|-----------|-------|--------------|
| TUI | `python -m nexus` | `nexus/boot` → `tui/nexus-tui.tsx` ↔ `nexus/commands.py` registry |
| GUI | `python -m nexus --gui` | `nexus/boot` → `server/__init__.py` (FastAPI :8000) + `gui/` (Vite :5173) |
| Server | `python -m nexus --server` | `nexus/boot` → `server/__init__.py` app |
| Gateway | `python -m nexus --gateway` | `nexus/boot` → `gateway/main.py` → `gateway/run.py::GatewayRunner` |
| Queue worker | embedded (default) | `server/__init__.py` → `queue/driver.py::QueueDriver` (env `NEXUS_EMBED_QUEUE_DRIVER=true`) |

## 2. Main agent loop (the central controller)

```
user request
   │
   ▼
NexusLoopV5.stream_run()  (orchestrators/v5/core.py — mixin host)
   │  V5DirectModelToolLoop (orchestrators/v5/direct_loop.py)
   │  ├─ model call via kernel MoE router → providers (40+ providers, fallback chains)
   │  ├─ tool execution via ToolRegistry (tools/nexus_tools/registry.py)
   │  │    ├─ built-in tools (tools/<name>/*.jsnol → BaseTool)
   │  │    ├─ skills (skills/registry.py → SKILL.md procedures)
   │  │    ├─ plugins (plugins/manager.py → hooks + tool registration)
   │  │    ├─ MCP tools (tools/nexus_tools/mcp_adapter.py → mcp/client)
   │  │    └─ Hive sub-agents (hive/engine.py + orchestrators/v5/hive.py)
   │  ├─ permissions gate (V5Permissions + sandbox risk scorer)
   │  ├─ durability: checkpoint (v5/checkpoint.py), session store, run context lease
   │  └─ reliability: RecoveryEngine + GoalStore + RunStateMachine + ProgressTracker
   ▼
streamed events → server SSE / gateway delivery ledger / TUI / GUI
```

Status: ✅ wired and tested (`tests/v5/*`, `tests/test_server/*`).

## 3. Component map (verified)

| Component | Location | Entry | Verified status |
|-----------|----------|-------|-----------------|
| V5 loop | `orchestrators/v5/core.py` | `stream_run()` | ✅ Stable; single canonical streaming path used by server + gateway + queue driver |
| Direct model/tool loop | `orchestrators/v5/direct_loop.py` | mixed into loop | ✅ Tool messages durably persisted per call (P37 fixed) |
| Tool registry | `tools/nexus_tools/registry.py` | `ToolRegistry` | ✅ Structured `list_tools()`; real execution only |
| Skills | `skills/` registry + engine | `skills/registry.py` | ✅ 69 SKILL.md files; engine executes procedures |
| Plugins | `plugins/manager.py` | lifecycle manager | 🟡 Beta; init failures log-and-disable |
| MCP | `mcp/client`, `tools/nexus_tools/mcp_adapter.py` | stdio client | 🟡 Beta; bounded timeout, no process-level cancel (P19), stdio only (P20) |
| Hive | `hive/engine.py`, `orchestrators/v5/hive.py` | `spawn_hive`/`consolidate_hive` | ✅ Sub-agent timeouts, cancellation, per-agent budgets, concurrency cap (P27 fixed) |
| Queue | `queue/store.py` (SQLite WAL), `queue/driver.py` | leases, fencing, reaper | ✅ Durable; leases + heartbeat + startup reap + quarantine + mission runner |
| Providers | `providers/*` + `providers/router.py` | kernel MoE router | ✅ Fallback chains, reliability wrappers, redaction |
| Memory | `memory/__init__.py` | `MemoryManager` | ✅ Verified-evidence gate; multi-source prefetch |
| Reliability | `reliability/*` + `orchestrators/v5/reliability.py` | RecoveryEngine, GoalStore, StateMachine, ProgressTracker | ✅ Wired into the loop; durable goals/state/progress |
| Checkpoints | `orchestrators/v5/checkpoint.py` | atomic fsync + sqlite lock, pruned | ✅ Per-phase, redacted |
| Run context | `nexus/run_context.py` | lease + heartbeat + orphan retirement | ✅ Restart-safe |
| Supervisor (queue) | `server/__init__.py` + `queue/status.py` | crash-window incident file | ✅ Durable incident/quarantine record |
| Gateway | `gateway/run.py`, `gateway/delivery.py`, `gateway/supervisor.py` | GatewayRunner | ✅ Deadline on every run (P02), ingress dedupe, durable outbound ledger, delivery-failure notification (P11) |
| Security | `security/`, `sandbox/`, `safety/` | secret scanner, risk scorer, 3-tier sandbox | ✅ Fail-closed; redaction at envelope/checkpoint/queue boundaries |
| Events | `nexus/events.py` | CanonicalEvent | ✅ Canonical vocabulary + deprecated set + non-canonical warnings |
| Server API | `server/__init__.py` (FastAPI) | :8000 | ✅ Queue worker health 503 when advertised-but-absent; hive consolidation (P03) |
| Control plane | `nexus/control_store.py`, `nexus/control_plane.py` | canonical run records | ✅ Runs dedupe + evidence |

## 4. Key flow maps

### Task-state flow (durable)
```
RECEIVED → QUEUED → LEASED (worker + lease token + heartbeat)
  → RUNNING (canonical control_run + queue task linked)
  → COMPLETED / FAILED / RETRYING / CANCELLED
  → crash ⇒ startup reap requeues expired leases; uncertain outcomes quarantined (never replayed)
```
Persistence: `queue/*.db` (SQLite WAL), `nexus/control_store.py`, run contexts, `.nexus_v5/{goals,state_machine,progress}/`, per-phase checkpoints, session JSONL.

### Failure flow
```
exception → FailureEnvelope (reliability/failure.py) → RecoveryEngine.recover()
  → user-action-required? → WAITING_FOR_USER (published)
  → non-recoverable? → BLOCKED_NON_RECOVERABLE (published + next_action)
  → component adapters → generic ladder (backoff → strategy switch → blocked)
  → verdict consumed by _consume_recovery_result → run status + goal bookkeeping
```
Every retry records attempt/strategy/delay/result; repeated identical failures freeze the strategy (circuit-breaker behavior).

### Permission flow
```
tool call → V5Permissions gate → sandbox risk scorer (8 rules, block ≥80)
  → threat patterns (41 regex) → approved / denied / ask
  → only the blocked operation parks; unrelated work continues
```

## 5. Capability map (unified registry status)

There is **no single unified capability registry** (mission §7): capabilities are
discovered from several sources — `tools/nexus_tools/registry.py` (tools, MCP
tools), `skills/registry.py`, `plugins/manager.py`, `mcp/`, `hive/`, providers
via the kernel MoE router, and the queue/gateway/service registries. Selection
today is per-path (registry for tools, factory for providers, hive engine for
sub-agents). This is the largest remaining architectural gap; see
`docs/audits/nexus_problem_register.md` (P26, P20) and the reliability research
docs for the follow-up plan.

## 6. What is NOT production-ready (honest list)

1. **Unified capability registry** — absent (multi-source discovery instead).
2. **MCP** — stdio only, no process-level cancellation, no configured servers.
3. **Queue ↔ Hive integration** — the driver has no hive supervision/consolidation.
4. **Plugin system** — beta; failure policy is log-and-disable.
5. **Gateway webhook surface** — second aiohttp app on :8080 (P24, functional but duplicated).
6. **Docs** — AGENTS.md/README carry stale tool/event counts (P45, P46).
