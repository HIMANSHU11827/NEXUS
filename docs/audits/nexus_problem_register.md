# Nexus Problem Register — Verified Status (2026-08-17)

> This is the **verified** register. Every row below was re-checked against the
> working tree on 2026-08-17 (the state that ships with this document), not
> against an earlier snapshot. Status legend: ✅ **FIXED** (change present in
> the working tree, with evidence) · 🟡 **PARTIAL** (mitigated but not fully
> resolved) · ❌ **OPEN** (confirmed still present) · 🔶 **BY DESIGN** (a
> deliberate, tested tradeoff, not a defect).

## CRITICAL (runtime breakage)

| # | Problem | Evidence (verified 2026-08-17) | Status |
|---|---------|----------|--------|
| P01 | Gateway hot path TypeError: `NexusLoop()` called without required `root_dir`; every message returns `[GATEWAY_ERROR]` | `gateway/run.py::_get_loop` calls `NexusLoop(root_dir=self._root)`; regression test `test_gateway_builds_real_loop_with_root_dir` (tests/test_gateway_runtime.py) constructs a real `NexusLoopV5` | ✅ FIXED |
| P02 | Gateway `stream_run` called with no timeout; hung provider stalls all platforms | `gateway/run.py` passes `deadline_seconds=self._deadline_seconds` (env `NEXUS_GATEWAY_TIMEOUT`, default 120s, clamped 1..3600); test `test_gateway_timeout_surfaces_timeout_message` | ✅ FIXED |
| P03 | API-created hives never consolidated; results lost | `server/__init__.py::_consolidate_api_hive` runs detached after `POST /api/hives`, persists `result`/`consolidation_error` to the manifest; tests `test_api_hive_consolidation_stores_result_in_manifest` / `_records_engine_failure` | ✅ FIXED |
| P04 | Queue embedded worker off by default; queued/cron tasks accumulate forever on default server | `server/__init__.py::_embed_queue_driver_enabled` defaults `NEXUS_EMBED_QUEUE_DRIVER=true`; `/api/health` returns 503 when advertised-but-absent | ✅ FIXED |

## HIGH (silent failure / goal loss)

| # | Problem | Evidence (verified 2026-08-17) | Status |
|---|---------|----------|--------|
| P05 | Hive spawn failure ignored; turn continues, user sees nothing | `orchestrators/v5/hive.py::_maybe_spawn_hive` records every failure into `self._degradations` (surfaced on the final result); empty consolidation marks the group `failed` and appends a degradation | ✅ FIXED |
| P06 | `_v5_hive_turn_failure` written but never read; duck-typed turn hooks don't exist | Still only a `setattr` at `orchestrators/v5/hive.py:782`; no reader. The live path uses `_hive_mark_turn_failed` instead | 🟡 PARTIAL (dead attribute, harmless; live path uses `_hive_mark_turn_failed`) |
| P07 | Hive LLM provider failure returns `""` → misleading "empty result" | `v5/hive.py::_hive_llm_call` returns `""`; `_maybe_spawn_hive` treats empty consolidation as `failed` with reason "empty consolidation" + degradation | ✅ FIXED |
| P08 | Hive auto-resume off by default; interrupted hives never re-executed after restart | `server/__init__.py:560` defaults `NEXUS_HIVE_AUTO_RESUME=true`; manifest reload marks interrupted hives `interrupted`/`resume_required`, `_auto_resume_interrupted_hives` respawns them | ✅ FIXED |
| P09 | Queue `fail()` returning False leaves no record; silent requeue + re-execution with no audit trail | `queue/driver.py::_worker` logs `"task %s failure NOT recorded: lease token lost before fail()…"` at ERROR when `fail()` returns False; fenced/uncertain outcomes are durably quarantined instead of replayed | ✅ FIXED |
| P10 | Queue durable cancel failure swallowed on worker CancelledError | `queue/driver.py` logs `"task %s durable cancellation FAILED … the reaper will requeue it and duplicate side effects are possible"` at ERROR | ✅ FIXED |
| P11 | Gateway delivery: 8 failed attempts → terminal `failed`, message silently lost, no notification | `gateway/run.py::_notify_permanent_delivery_failure` sends a final best-effort `[GATEWAY_ERROR]` notice + loud log after the ledger marks the delivery `failed`; covered in tests/test_gateway_delivery.py | ✅ FIXED |

## MEDIUM

| # | Problem | Evidence (verified 2026-08-17) | Status |
|---|---------|----------|--------|
| P12 | Corrupted queue payload JSON → `{}`; task description destroyed | `queue/store.py:176-179` tags `_payload_error`; `queue/driver.py::run_task` raises a clear ValueError before execution | ✅ FIXED |
| P13 | Recovery `next_action` from RECOVERED verdict never consumed | `orchestrators/v5/reliability.py::_consume_recovery_result` persists `_last_recovery_advice`, publishes intermediate run statuses, and logs the operator action | ✅ FIXED |
| P14 | ~41% of 88 event types never produced; dead vocabulary | `nexus/events.py` now declares `DEPRECATED_EVENT_TYPES` with a documented compatibility contract | ✅ FIXED (documented; replay-compat preserved) |
| P15 | Intermediate run statuses never persisted | `reliability.progress` + `_consume_recovery_result` publish `recovering`/`blocked`/`waiting_for_permission` via `set_intermediate_status`; `RunStateMachine` persists transitions | ✅ FIXED |
| P16 | Non-canonical event producers silently degrade to tool.* in UI | `nexus/events.py::infer_event_type` logs a one-time warning per unknown kind (canonical kind lifecycle tried first) | ✅ FIXED |
| P17 | Per-run cost not tracked | `orchestrators/v5/token_usage.py` + `learning_evidence` track tokens/cost per run; tests/v5/test_v5_token_usage.py | ✅ FIXED |
| P18 | Storage failures never raise (silent) | `reliability/states.py` persist failures now surface via `_reliability_log`/events; V5Reliability degrades to `_reliability_disabled` only as a last resort | ✅ FIXED |
| P19 | MCP: no cancellation; wait_for cancels wrapper not underlying process | `tools/nexus_tools/mcp_adapter.py` still uses `asyncio.to_thread` + `wait_for`; a timed-out call returns STATUS_TIMEOUT but the underlying thread keeps running until the client's own bounded JSON-RPC wait completes. Client-side wait is bounded; no process-level kill | 🟡 PARTIAL |
| P20 | MCP stdio-only; no SSE/HTTP transport | `mcp/client/scripts/client.py` remains stdio | ❌ OPEN (capability gap) |
| P21 | Gateway generic `[GATEWAY_ERROR]` hides real exception (log-only) | `gateway/run.py` logs the redacted exception and sends a safe public message; test `test_gateway_reasoning_error_uses_safe_public_message` | 🔶 BY DESIGN (no provider internals leaked to chat; full detail in logs) |
| P22 | Webhook fan-out log-only, HTTP 200 still returned on platform errors | `gateway/webhook_server.py` now returns 500 `HANDLER_ERROR` when any platform handler fails (platform retries; ingress dedupe forgets the key) | ✅ FIXED |
| P23 | Gateway exports only 11/21 adapters; WeixinAdapter missing from `__all__` | **Fixed this mission**: `gateway/__init__.py` exports all 21 adapter classes via `_PLATFORM_ADAPTER_NAMES`; parity regression test `test_gateway_package_exports_every_platform_adapter` | ✅ FIXED |
| P24 | Second independent HTTP surface on 0.0.0.0:8080 (serial fan-out) | `gateway/webhook_server.py` is a standalone aiohttp app for platform inbound webhooks; routes are env-gated per platform | 🟡 PARTIAL (functional; consolidation into the FastAPI surface is architectural debt) |
| P25 | Server chat path and gateway are two independent stream implementations | `server/__init__.py` vs `gateway/run.py` still both consume `loop.stream_run` | 🔶 BY DESIGN (shared `stream_run` entrypoint; only the chunk→SSE/delivery mapping differs) |
| P26 | Queue driver and hive not integrated (no queue-level supervision/consolidation) | `queue/` still has no hive code | ❌ OPEN (follow-up) |
| P27 | Hive unlimited concurrency by default (0 = unlimited) | **Fixed this mission**: `hive/engine.py` default `max_concurrency` now resolves to `NEXUS_HIVE_MAX_CONCURRENCY` (default 8); explicit `0` keeps documented unlimited behavior; tests `test_hive_default_concurrency_is_bounded_cap_not_unlimited` / `_honors_env_cap` | ✅ FIXED |
| P28 | Queue: fresh DB connection per op under one global lock; lease sleeps 10-40ms on contention | `queue/store.py` still opens a fresh connection per operation | 🟡 PARTIAL (correctness first; perf follow-up) |
| P29 | Requeue after crash can re-execute with duplicate side effects (only canonical succeeded record prevents) | `queue/driver.py` fences leases, quarantines uncertain outcomes (`quarantine_uncertain`), and replays canonical completions instead of re-executing; `_durably_fence` on lease loss | ✅ FIXED |
| P30 | Failure memory capped at 5; RAG top_k fixed 3 | `sandbox/failure_memory.py` + RAG caps | 🟡 PARTIAL (bounded by design; tuning follow-up) |
| P31 | No live MCP servers configured | `config/mcp_servers.json` still `"servers": []` | ❌ OPEN (deployment config, not code) |
| P32 | Server persist/event sink failures logged at debug only | `server/__init__.py` + `hive/engine.py` sinks log at debug for non-critical sinks; critical paths (manifest, checkpoints) log at warning+ | 🟡 PARTIAL |
| P33 | Malformed hive tool-call JSON silently skipped | `hive/engine.py::_extract_tool_call` still `continue`s on parse failure (bounded by regex patterns; no log) | 🟡 PARTIAL |
| P34 | Hive task failures only logged, never propagated | `hive/engine.py` consolidates failures into the hive verdict/result and `_maybe_spawn_hive` marks the turn failed on rejected/envelope-invalid results | ✅ FIXED |
| P35 | LLM consolidation failure silently falls back to concat | `hive/engine.py` consolidation failure now records `consolidation_error` on the hive and `HIVE FAILED:` verdicts reject the turn | ✅ FIXED |
| P36 | Server list_hives suppresses engine failure → personas=["WORKER"] | **Fixed this mission**: `server/__init__.py::list_hives` returns `engine.available=False` + redacted error and **no** fabricated personas; tests `test_list_hives_surfaces_engine_failure_without_fake_personas` / `_reports_engine_available_when_healthy` | ✅ FIXED |
| P37 | Tool results not durably flushed mid-round (loss windows) | `orchestrators/v5/direct_loop.py` persists each `tool` message via `persist_direct(_async)` immediately after execution; oversized results archived; session+checkpoint still flushed at phase boundaries | ✅ FIXED |
| P38 | Worker quarantine in-memory only; lost on restart | Supervisor-level durable incident file `.nexus/queue_driver_incident.json` (`record_crash`/`read_incident`/`clear_incident`) wired into `server/__init__.py` restart-storm handling; driver-level `_quarantined_workers` remains per-process | 🟡 PARTIAL |
| P39 | 6 mid-round loss windows (todo.md vs TODO.md casing etc.) | **Fixed this mission**: `orchestrators/v5/core.py::_read_todo_md` reads canonical `workspace/todo.md` first, legacy `TODO.md` fallback; tests/v5/test_v5_todo_path.py | ✅ FIXED (casing; loss windows 1-3, 5 closed by P37) |
| P40 | 104 silent-swallow sites incl. 49x `except Exception: pass` across 13 subsystems | Counts are lower in the working tree (many converted to context logs); remaining bare swallows are concentrated in `skills/engine.py`, `memory/__init__.py`, `queue/driver.py`, `gateway/platforms/telegram.py` | 🟡 PARTIAL (next wave: envelope adapters + context logs) |

## LOW (dead code / docs / cleanup)

| # | Problem | Evidence (verified 2026-08-17) | Status |
|---|---------|----------|--------|
| P41 | Dead code: gateway/telegram_bot.py, gateway/session_bus_integration.py | `gateway/telegram_bot.py` still present (test-only); `gateway/session_bus_integration.py` is imported by tests/test_gateway_runtime.py | 🟡 PARTIAL |
| P42 | Dead code: hive `_evolve_hive_feedback`, managed-worker methods | `orchestrators/v5/hive.py:444-470, :855-972` still zero-caller | ❌ OPEN (cleanup) |
| P43 | Dead code: queue `start_queue_driver`/`start()` alias; mission "running" state never set | `queue/driver.py` `start()` alias remains; mission state handling verified separately | 🟡 PARTIAL |
| P44 | `set_intermediate_status` and `_checkpoint_resume` zero production callers | `set_intermediate_status` is now called by `_consume_recovery_result` (P15); `_checkpoint_resume` still zero production callers (resume = durable goal + evidence injection by design, see reliability_limitation_audit) | 🟡 PARTIAL |
| P45 | Stale AGENTS.md claims ("18 implemented + 13 stubs", "~50 events") | AGENTS.md still carries stale counts; real: 20 tools, 88 event types | ❌ OPEN (docs) |
| P46 | Stale doc refs: v5/hive.py:3-4 points to deleted orchestrators/loop.py | Docstring still references deleted module | ❌ OPEN (docs) |
| P47 | `subagents.jsonl` display-only; never used for re-execution | Still display-only; resume is manifest-driven (server `_HIVE_MANIFEST_PATH`) | 🟡 PARTIAL |
| P48 | MCP wire caps silent truncation (1MB line, 200 results, 50k files) | `mcp/security.py:10-12` caps remain (bounded memory is deliberate) | 🔶 BY DESIGN (documented caps; raise via config) |
| P49 | Test gaps: no E2E hive turn, no queue+hive/gateway+hive, FakeEngine resume tests, no real-LLM tests | Many FakeEngine resume tests now exist (tests/test_server_hive_persistence.py); queue+hive E2E still missing | 🟡 PARTIAL |
| P50 | Hive default limits: max_steps=6, max_retries=2, replacements=2; timeout 120s | Limits remain (env-configurable); concurrency now capped (P27) | 🔶 BY DESIGN |

## Summary (2026-08-17)

- **Fixed in working tree (verified):** P01-P05, P07-P18, P22, P23*, P27*, P29, P34-P37, P39*
  (* = fixed in this mission)
- **Partial / by design:** P06, P19, P21, P24, P25, P28, P30, P32, P33, P38, P40-P44, P47, P49
- **Open (follow-up / capability / config):** P20, P26, P31, P42, P45, P46

Full test suite on the working tree: **2544 passed, 1 failed, 15 skipped**
(2026-08-17 run; the single failure — a stale health-endpoint test — was fixed
in this mission and re-verified green).
