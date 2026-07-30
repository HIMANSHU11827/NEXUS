# NEXUS AI Capability Audit

Date: 2026-07-27  
Scope: backend loop, context, memory, providers, tools, MCP, Hive, safety, interfaces, and lifecycle.

## Status legend

- **Working** — reachable on the normal runtime path and covered by evidence/tests.
- **Partial** — implemented, but limited, optional, or not consistently wired into the main path.
- **Missing** — no production implementation on the normal path.
- **Risk** — behavior can mislead users, lose state, or weaken safety/recovery.

## End-to-end execution path

```text
prompt
  -> server/session adapter
  -> NexusLoop.stream_run()
  -> context grounding (rules, memory, skills, code context)
  -> optional todo.md plan
  -> provider/model stream
  -> tool-call extraction and fallback classifiers
  -> permission/risk audit
  -> ToolRegistry / MCP / Hive execution
  -> observations and evidence
  -> verification and bounded retries
  -> checkpoint + session memory
  -> canonical events + SSE
  -> TUI/GUI/gateway render
```

The main loop is authoritative. GUI/TUI text-marker parsing is compatibility telemetry only; canonical work events should remain the source of truth.

## Capability matrix

| Area | Current behavior | Status | Main gap / risk | Priority |
|---|---|---:|---|---:|
| Main agent loop | `orchestrators/loop.py` grounds, plans, calls models, extracts tools, executes, verifies, retries, checkpoints, saves memory, and closes run events | Working | Very large single owner (~3k lines) makes state changes hard to reason about | P1 |
| Provider routing | Many adapters, factory, profiles, health, overrides, and fallback behavior exist | Partial | Breadth is high; capability/health selection is not proven uniformly for every provider | P1 |
| Context assembly | Rules, memory, skills, code context, RAG, failure vaccines, and knowledge are gathered | Partial | `context/NexusContextCompressor` is not on the main loop path; compressor assumes 200k tokens | P0 |
| Context compaction | Compressor can prune tool output, summarize, repair tool pairs, and persist a vault fact | Partial | No verified automatic trigger in normal `stream_run`; model-specific context limits are hard-coded | P0 |
| Session memory | JSON session history plus `MemoryManager` and `.opencode/memory` compatibility | Partial | MemoryManager keeps only a short prefetch view; `.opencode/memory/learned.md` is appended only if the file already exists | P1 |
| RAG / knowledge | Parallel prefetch calls RAG and KnowledgeVault | Partial | Failures are swallowed into empty context; no user-visible evidence that retrieval was attempted or unavailable | P1 |
| Skills | Registry/discovery, `.opencode/skills`, skill tools, enable/disable endpoints, and background evolution hooks | Partial | Automatic skill selection and reliable skill-learning loop are not demonstrated | P1 |
| Tool registry | Metadata discovery, handler loading, availability checks, defaults, type coercion, schema validation, concurrency limits, cooldowns, streaming adapter | Working | Some metadata-only tools have no handler; dynamic import isolation/error reporting can be improved | P1 |
| Tool execution | Built-in tools execute through registry; results are cached by name + sorted params within a run | Working | Cache is run-local; tool outputs can be large and tool cancellation boundaries need more proof | P1 |
| Permission policy | AUTO/AI_DECIDE/ASK_ALL/CHECKLIST-style audit and sandbox/risk controls exist | Partial | Denial now emits `guardrail.blocked`, but terminal run status still records failure for compatibility | P0 |
| Sandbox | Three tiers and command risk/threat pattern checks exist | Partial | Docker/remote isolation depends on installed runtime and is not uniformly smoke-tested | P1 |
| MCP client integration | Config-driven subprocess MCP clients register exposed tools into the registry | Partial | Startup-only connection model; no robust reconnect/health/handshake telemetry on the normal path | P1 |
| MCP server | Minimal stdio JSON-RPC server exposes read-focused code graph tools with bounds | Working | It is a separate server surface; broad external MCP discovery/management is not equivalent to a full MCP host | P1 |
| Hive / subagents | Single and parallel subagents emit lifecycle events and can consolidate results | Partial | Subagents use a provider fallback and do not share the full parent tool/permission/context lifecycle | P0 |
| Deep research | Tool decomposes research and uses Hive workers | Partial | Quality depends on provider availability and source/tool configuration; evidence/citation guarantees are limited | P1 |
| Planning | `todo.md` plan creation and plan events; TUI/GUI plan panels | Working | Plan state is file-based and can be stale; no typed persistent plan store or step IDs | P1 |
| Verification | Parallel targeted verification, failure vaccines, retries, checkpoint saves | Working | Verification strategy is heuristic and task classification can miss required tests | P0 |
| Checkpoints / rewind | Checkpoint saving exists in loop; TUI `/rewind` is explicitly unsupported | Partial | Recovery is backend-capable but not exposed as a reliable user action | P0 |
| Canonical events | Validated envelopes, statuses, stable IDs, parent IDs, sequences, SSE adapters | Working | Event type/status coverage is newer than some consumers; replay/reconnect semantics need broader fixtures | P0 |
| SSE transport | Server streams text, work events, done/error frames; TUI deduplicates work-event replay | Working | No WebSocket; reconnect/resume cursor protocol is absent | P1 |
| Ink TUI | Conversation, activity cards, plan, Hive, usage, question mode, commands, voice/status/footer | Partial | Permission requests are not a dedicated interactive dock; command output is mostly summarized rather than streamed into a bounded log panel | P0 |
| GUI | React workspace, files, terminal drawer, activity/work events, SSE | Partial | Full acceptance across all panels is not freshly proven; some panels remain beta/placeholder-prone | P1 |
| Gateway | Telegram/Discord/WhatsApp/Slack and adapters exist | Partial | Platform setup and delivery/retry behavior require per-platform live configuration | P1 |
| Voice | STT/TTS/pipeline and status endpoints exist | Partial | Requires local drivers/provider configuration; not a core agent-loop guarantee | P2 |
| Scheduling | Scheduler/reminder management surfaces exist in parts of runtime/config | Partial | No single verified default scheduler lifecycle comparable to Hermes cron | P1 |
| Plugins/hooks | Plugin manager, trust model, lifecycle hooks, tool hooks | Partial | Hook failure handling is generally best-effort; plugin capability isolation and provenance need stronger evidence | P1 |
| Evolution/neural | Memory/tool forge hooks and multiple evolution/neural packages | Partial / Missing | Several modules are constructor-only or explicit stubs; do not treat them as active learning | P0 |
| Legacy architect | Compatibility module with stub imports | Missing | Not a viable second orchestrator; keep out of production routing | P2 |
| Local brain/training | Stub local image brain, trainer, nerve center | Missing | No offline inference/training/RL loop supplied by these modules | P2 |
| Observability | Logger, mission replay, canonical events, status APIs | Partial | No unified run trace viewer/export with event lineage and tool evidence | P1 |

## What works reliably today

1. The normal `NexusLoop` path is a real model/tool loop, not only a chat wrapper.
2. Tool calls are audited before execution and validated through registry metadata.
3. Tool results are verified and can trigger bounded retries.
4. Run/message completion and failure events are closed in the streaming boundary.
5. Hive and MCP tools can participate in the same registry/event pipeline.
6. TUI activity rows have stable IDs, bounded retention, and replay deduplication.
7. Context compaction has a useful implementation, but it is not proven to be automatically invoked by the main loop.

## What is only partial or misleadingly advertised

- “Self-improving,” neural, ensemble, horizon, and omni-kernel language describes a roadmap/extension surface more than a guaranteed runtime behavior.
- “30+ providers” means adapters exist; it does not mean every provider is configured, healthy, streaming-compatible, tool-capable, or tested.
- “MCP support” currently means config-driven subprocess clients plus a focused stdio server, not a complete reconnecting MCP host ecosystem.
- “Memory” is a collection of JSON/session, RAG, knowledge, failure, forge, and compatibility stores—not one durable, queryable memory model with provenance everywhere.
- “Hive” is real parallel isolated LLM work, but not yet full parent-session delegation with inherited permissions, context, cancellation, and shared checkpoints.
- “Checkpoint/rewind” exists in backend pieces, but the main TUI explicitly does not expose rewind.

## Highest-value improvement order

### P0 — reliability and truth

1. Put automatic context compaction on the main loop path using the active provider/model context limit.
2. Add typed permission request/response events and an interactive TUI permission dock: deny, allow once, allow for session/pattern.
3. Give Hive children inherited cancellation, parent permission constraints, context provenance, and result evidence.
4. Add a real checkpoint list/diff/restore API and wire `/rewind` to it.
5. Add end-to-end fixtures for run replay, event ordering, blocked tools, cancellation, tool output chunks, and reconnect.

### P1 — capability depth

1. Replace startup-only MCP connections with health state, reconnect/backoff, and tool provenance.
2. Add typed plan/step IDs and persist plan state independently from `todo.md`.
3. Add a bounded command-output stream panel and final run summary with changed files, tests, failures, and next action.
4. Add provider capability negotiation: streaming, tools, vision, context limit, and health score.
5. Add memory provenance, source labels, recency, and user-visible retrieval diagnostics.

### P2 — breadth and polish

1. Finish or quarantine explicit stubs in evolution/neural/local-brain/architect modules.
2. Add a scheduler lifecycle and testable delivery ledger.
3. Add gateway integration fixtures and per-platform retry/dead-letter behavior.
4. Expand manual TUI/GUI acceptance at narrow, normal, and wide terminal sizes.

## Immediate safe changes already made in this audit series

- Canonical `blocked` status is preserved rather than collapsed into `failed`.
- Permission-denied tool calls emit `guardrail.blocked` with reason, tool names, parent run, and stable event ID while retaining legacy `plan.failed` compatibility.
- TUI work-event replay is deduplicated with bounded retention.
- TUI custom question answers have an explicit input mode with submit/cancel behavior.

## Recommended next command

```powershell
python -m pytest tui/test_tui_e2e.py tui/test_runtime.py -v
```

If the global pytest installation reports a `pydantic`/`pydantic-core` mismatch, use the project virtual environment or repair that dependency before interpreting failures as NEXUS failures.
