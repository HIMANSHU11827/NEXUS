# Nexus AI Engineering State

Last updated: 2026-08-11 (Asia/Calcutta)

## Active mission

Continuously improve Nexus AI through source-backed comparison, reproducible audits,
incremental fixes, and verification. Preserve existing user work in the dirty
worktree; do not reset or bulk-clean it.

## Baseline

- Repository: `https://github.com/HIMANSHU11827/NEXUS.git`
- Branch: `main`
- HEAD: `5ba0fb161b2047762ed98eb6eb905d1d0a3e581e`
- Working tree: heavily modified with prior audit waves and untracked evidence;
  changes are pre-existing at mission start.
- Runtime contract currently documented as V5 `NexusLoop` → provider/router →
  native/direct tool loop → permission/sandbox → tool results → verification →
  persistence/events → response.
- Prior verification recorded in `MULTI_AGENT_TASKS.md`: full Python suite had
  passed in an approved Windows environment, with later focused resilience work
  added on 2026-08-10. Re-run focused checks before relying on those claims.

## Reference revisions

| Project | Local checkout | Upstream | Revision observed | Status |
|---|---|---|---|---|
| Hermes Agent | `references/hermes-agent` | `NousResearch/hermes-agent` | `3f832978d30e0e14437edbf7a3f63315f08bad36` | clean; primary research checkout |
| Hermes Agent | `external/hermes-agent` | `NousResearch/hermes-agent` | `03fa32c92dd445eb64c7f67434dd91b32c40701d` | preserve existing untracked `.lease-probe/` |
| OpenCode | `references/opencode` | `anomalyco/opencode` | `550d1ffd24718454925c4636e937878f0274de48` (2026-08-10 22:00 +1000) | clean, current `dev` branch |
| OpenClaw | `references/openclaw` | `openclaw/openclaw` | `86fe45ce17918dfd2bb62edc9c3e58b47a47cb35` (2026-08-10 13:29 -0400) | clean, `main`; blob-filtered checkout |

Official upstream URLs:

- OpenCode: https://github.com/anomalyco/opencode
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- OpenClaw: https://github.com/openclaw/openclaw

## Existing evidence to verify

- `NEXUS_CODEBASE_MAP.md`, `docs/ARCHITECTURE.md`, and `docs/AGENT_LOOP.md`
- `docs/NEXUS_RUNTIME_GAP_MATRIX.md`
- `docs/AGENT_FRAMEWORK_COMPARISON_2026-08.md`
- `docs/AGENT_BENCHMARK_COMPARISON_2026-08.md`
- `MULTI_AGENT_TASKS.md`
- `ISSUE_LIST.md`

These are evidence inputs, not assumed truth. Claims must be checked against
runtime code and tests.

## Ranked next work

1. Continue the async-boundary audit for remaining synchronous filesystem work
   in tools and orchestrators; `ShortcutsTool` and `PlanningTool` are already
   covered by focused regressions.
2. Trace remaining live request paths from `nexus` entry points and API surfaces
   into `orchestrators/v5`, with file/line evidence and tests.
3. Re-run focused loop, queue, provider, tool, security, and recovery tests using
   a writable Windows pytest temp root where needed.
4. Verify the open P1/P2 items in `ISSUE_LIST.md` rather than assuming they remain
   valid; prioritize only reproducible failures.
5. Implement the highest-value reproducible fix, add a regression test, review
   second-order effects, and append verification evidence here and to the issue
   backlog.

## Change discipline

- Never reset, checkout, or delete existing work without explicit authorization.
- Keep reference repositories isolated and read-only for research.
- Prefer small patches with focused tests.
- Treat claims of completion as unverified until a command produces evidence.

## Verification log

- 2026-08-10: focused queue/V5/provider regression command initially hit the
  managed Windows ACL (`sqlite3.OperationalError: unable to open database file`
  and pytest fixture `WinError 5`); this is an environment failure, not a code
  verdict.
- 2026-08-10: rerun with the repository's approved host-permission procedure:
  `46 passed, 8 warnings` across `tests/test_queue_driver.py`,
  `tests/v5/test_v5_direct_model_tool_loop.py`, and
  `tests/test_provider_attempts.py`.
- 2026-08-10: post-fix verification passed `73 tests` across server chat/work
  item/Hive persistence, V5 direct-loop, queue-driver, and provider-attempt
  regressions; `server/__init__.py` also passed `py_compile`.
- Remaining warning: `datetime.utcnow()` deprecation in V5 paths; it is a
  maintainability item to assess after checking serialization compatibility.

## Verified fix: streamed chat terminal-state propagation

- Problem: the server streaming `/api/chat` route could persist a timed-out or
  provider-failed stream as `done` because `pump_run()` kept failure state in a
  local variable while the cleanup `done` marker set `stream_completed=True`.
- Evidence: `server/__init__.py` previously initialized `stream_succeeded=True`,
  emitted an ordinary cleanup marker from `timed_pump()`, and did not propagate
  generic/timeout failures to the outer status variable.
- Root cause: terminal state ownership was split between the producer's local
  `run_succeeded` and the consumer's `stream_succeeded`.
- Fix: failure branches now propagate `stream_succeeded=False`; the outer
  timeout handler does the same before requesting abort. Cleanup markers remain
  transport-only and cannot turn failure into success.
- Files: `server/__init__.py`,
  `tests/test_server/scripts/test_chat_runtime_parity.py`.
- Verification: `13 passed` in the chat parity suite, including new timeout and
  provider-disconnect workflow-status tests.
- Remaining risk: the full server aggregate suite is slow/unstable under the
  current host when several subprocess-heavy files are combined; each affected
  file and the focused regression suite passes independently.

## Current next work

1. Continue controlled queue/provider/server partitions and capture runtime
   evidence rather than relying on the historical full-suite claim.
2. Audit context budgeting/compaction for critical-memory truncation and verify
   that UI/backend terminal-state parity remains intact.
3. Continue the disconnected-subsystem audit across background tasks,
   gateway supervision, and durable task recovery; next inspect supervisor
   concurrent-tick and stop/start ownership boundaries. Then continue the
   tool/MCP execution boundary audit.

## Verified fix: bounded provider streaming retry

- Problem: a transient primary-provider failure before the first streamed
  chunk bypassed the configured retry policy and immediately entered fallback
  or returned an error.
- Root cause: `ModelRouter.stream_generate()` protected the stream with circuit
  breaking and fallback, but did not apply `RetryPolicy` to the primary stream.
  Retrying after output begins would be unsafe because it could splice a second
  answer into the first, so the retry boundary must be explicit.
- Fix: primary streaming now retries only before any output is emitted, with the
  configured bounded delay/attempt policy. Once output exists, it reports the
  failure without splicing another stream. An explicitly requested provider
  remains authoritative and is never silently replaced.
- Files: `providers/router.py`,
  `tests/test_main/scripts/test_provider_router_stream.py`.
- Verification: `17 passed` across provider streaming, attempts, reliability,
  and V5 routing tests; `providers/router.py` passed `py_compile`.
- Remaining risk: fallback streams do not independently retry after a clean
  pre-output failure; provider profile lease replacement has one previously
  observed but non-reproducible Windows concurrent-write failure.

## Verified fix: MCP multi-server lifecycle callback binding

- Problem: with multiple configured MCP servers, a degraded/recovered server
  could park or restore the final server's tools because callbacks created in
  the configuration loop captured mutable loop variables late.
- Root cause: `ToolRegistry.init_mcp_tools()` assigned lambdas that referenced
  `server_name`, `client`, and `requires_env` from the surrounding loop.
- Fix: callbacks now bind each server's values at creation time, preserving
  per-server tool parking and recovery.
- Files: `tools/nexus_tools/registry.py`,
  `tests/test_mcp_registry_lifecycle.py`.
- Verification: `22 passed` across the new lifecycle regression, MCP config,
  MCP server, and MCP tool suites.
- Remaining risk: MCP reconnect remains synchronous and bounded; a slow
  restart can occupy the invoking worker during backoff, so cancellation and
  reconnect observability remain follow-up audit items.

## Verified fix: MCP timeout error classification

- Problem: an MCP JSON-RPC timeout returned by `MCPClient` was converted by
  `MCPToolAdapter` into a permanent generic MCP error, so the tool execution
  layer could not recognize it as retryable.
- Root cause: the adapter treated every dictionary containing `error` the same,
  even though `MCPClient` uses a structured error result for bounded call
  timeouts.
- Fix: `Timeout calling ...` results now become `STATUS_TIMEOUT` with a
  retryable `TimeoutError` envelope; genuine MCP errors retain permanent error
  semantics.
- Files: `tools/nexus_tools/mcp_adapter.py`,
  `tests/test_mcp_tool_adapter.py`.
- Verification: `23 passed` across the MCP adapter, multi-server lifecycle,
  config, server, and tool suites.
- Remaining risk: a timed-out underlying synchronous client call can remain in
  its worker thread until the client's own timeout; cancellation/resource
  cleanup is still part of the MCP follow-up audit.

## Verified fix: single-agent Hive terminal persistence

- Problem: `spawn_agent()` creates a one-agent Hive control record but did not
  refresh it when the agent finished, failed, or was cancelled. The durable
  record could remain `running` after the work had ended.
- Root cause: multi-agent spawning has an aggregate `_hive_tasks` runner that
  calls `_refresh_hive_control()`, while the single-agent path tracks only the
  agent task.
- Fix: the shared `_run_agent_with_retry()` boundary now refreshes the owning
  Hive control state in `finally`, covering all terminal outcomes without
  duplicating lifecycle logic.
- Files: `hive/engine.py`, `tests/test_hive_single_agent_lifecycle.py`.
- Verification: `15 passed` across single-agent lifecycle, Hive control,
  event delivery, dependency, and budget suites.
- Remaining risk: control files are durable lifecycle metadata; rebuilding an
  in-memory engine after restart still depends on the server's resume scan and
  remains part of the checkpoint/recovery audit.

## Verified fix: fast Hive creation terminal-state reconciliation

- Problem: API-created Hive agents start before `create_hive()` writes the
  summary manifest. A very fast agent could finish and emit its terminal event
  before the summary existed; the endpoint then persisted a new `running`
  summary, losing the terminal state.
- Root cause: event-driven projection and initial manifest insertion were not
  reconciled at the handoff boundary.
- Fix: `create_hive()` now derives the initial Hive status from the returned
  agent states before persisting, so terminal results observed during startup
  cannot be overwritten by a stale `running` value.
- Files: `server/__init__.py`,
  `tests/test_server_hive_persistence.py`.
- Verification: `13 passed` across server Hive persistence, single-agent
  lifecycle, and Hive control tests; server module passed `py_compile`.
- Remaining risk: a later event can still race with a manifest write across
  multiple server processes; the event log remains the detailed source of
  truth and cross-process manifest locking is a follow-up reliability item.

## Checkpoint/resume audit result

- The workspace checkpoint path is bounded by checkpoint-id sanitization,
  manifest integrity validation, session ownership checks, workspace/snapshot
  containment checks, atomic per-file replacement, and per-checkpoint restore
  locks. Snapshot traversal skips generated/runtime trees and source symlinks;
  restore removes symlink entries without following them.
- Verification: `24 passed, 1 warning` across server checkpoint create/list/
  restore/delete and conflict cases, Hive checkpoint survival, continuity
  persistence, and release-boundary resume tests.
- No new checkpoint defect was patched in this pass. The remaining recovery
  risk is semantic rather than file-safety related: reconstructing live model,
  tool, and provider resources after a process restart must be represented by
  explicit durable state rather than serialized transient handles.

## Verified fix: provider profile persistence temp-path collision

- Problem: concurrent or externally observed profile writes could fail during
  `profiles.json` replacement on Windows (`WinError 5`). Every save used the
  same predictable `profiles.tmp` path.
- Root cause: the fixed temporary filename created a collision surface even
  though Nexus writers used an advisory lock; external file observers can hold
  or race a predictable path.
- Fix: saves now use a unique same-directory temporary filename containing the
  process id and random token, then atomically replace the destination and
  clean up the temporary file.
- Files: `providers/profiles.py`,
  `tests/test_provider_profiles_routing.py`.
- Verification: `25 passed` across profile lease, provider retry, reliability,
  and streaming-router suites; `providers/profiles.py` passed `py_compile`.
- Remaining risk: host security software can still deny a destination replace;
  the unique temp path removes the observed collision mechanism but does not
  eliminate all external filesystem interference.

## Verified fix: provider profile lease release after requests

- Problem: factory-acquired profile leases were attached to provider objects but
  normal router calls never released them. Cached providers could therefore
  hold an exclusive profile claim until the 120-second TTL, even after success,
  failure, or completed streaming.
- Root cause: lease ownership had acquisition in `NexusProviderFactory` but no
  corresponding request-lifecycle boundary in `ModelRouter`.
- Fix: `ModelRouter` now centrally releases and clears attached leases after
  synchronous provider calls and normal/failed streaming provider attempts.
  Release is best-effort and never masks the provider result or error.
- Files: `providers/router.py`,
  `tests/test_provider_router_attempts.py`,
  `tests/test_main/scripts/test_provider_router_stream.py`.
- Verification: `23 passed` across lease, factory, retry, reliability, and
  streaming-router tests; a focused synchronous/streaming lease suite passed
  `9 tests`; `providers/router.py` passed `py_compile`.
- Remaining risk: a consumer that abandons a streaming generator during an
  in-flight provider iterator still needs explicit generator-finalization
  coverage; this is the next streaming-resource audit item.

## Verified fix: queue lease-reaper compare-and-update

- Problem: `TaskQueue.requeue_expired_leases()` selected expired leases and
  later updated rows by task id alone. A worker could renew or complete the
  task between those operations, allowing the reaper to overwrite newer state
  or results.
- Root cause: the reaper lacked an ownership/version predicate on its write.
- Fix: reaping now updates only when the row is still `leased`, has the exact
  lease token observed by the selector, and remains expired. A zero-row guarded
  update is treated as a concurrent ownership change and is not counted as
  reaped.
- Files: `queue/store.py`, `tests/test_queue_store.py`.
- Verification: `27 passed` across queue store, driver, control identity, cron,
  and server queue-supervisor suites; `queue/store.py` passed `py_compile`.
- Remaining risk: external side effects remain at-least-once around a worker
  crash; the lease guard prevents stale result overwrite but cannot undo an
  already-issued external operation.

## Verified fix: abandoned provider-stream lease cleanup

- Problem: closing a router streaming generator after a partial response could
  bypass normal terminal cleanup and leave its profile lease attached until
  expiry.
- Root cause: cleanup existed only on normal success/error branches after the
  provider iterator returned; generator finalization can happen earlier.
- Fix: provider iterators now run through a `try/finally` forwarding wrapper
  that releases and clears the profile lease on completion, provider failure,
  or explicit consumer close.
- Files: `providers/router.py`,
  `tests/test_main/scripts/test_provider_router_stream.py`.
- Verification: `19 passed` across streaming cleanup, router attempts, and
  profile lease suites; `providers/router.py` passed `py_compile`.
- Remaining risk: a provider implementation that ignores generator close may
  retain its own underlying network resource; router-side lease ownership is
  nevertheless released deterministically.

## Verified fix: gateway delivery lease recovery

- Problem: a gateway process crash after claiming an outbound delivery left
  the row in `leased` state permanently; subsequent workers only claimed
  `pending` or `retrying` rows, so the response was never retried.
- Root cause: delivery claim selection and its guarded update omitted expired
  `leased` records from the recovery state machine.
- Fix: claim now considers `leased` rows whose lease deadline has expired and
  atomically replaces the old owner/token with the recovering worker.
- Files: `gateway/delivery.py`, `tests/test_gateway_delivery.py`.
- Verification: `13 passed` across gateway delivery and queue-supervisor/
  alert regression tests; `gateway/delivery.py` passed `py_compile`.
- Remaining risk: a crash after external acceptance but before acknowledgement
  remains at-least-once and can duplicate a platform message; platform-native
  idempotency keys remain the correct second-order mitigation.

## Verified fix: V5 memory-context preservation

- Problem: the direct V5 execution path fetched memory after perception,
  planning, and Hive enrichment, then replaced `context_summary` with only the
  memory fields. The model lost intent, plan, and delegated-agent context.
- Root cause: memory enrichment was implemented as an assignment rather than a
  merge at the second prefetch boundary.
- Fix: `_merge_memory_context()` appends bounded session/RAG/failure/knowledge/
  episodic/procedural context to the existing turn summary, preserving both
  execution context and durable memory evidence.
- Files: `orchestrators/v5/core.py`,
  `tests/v5/test_v5_memory_context_merge.py`.
- Verification: `38 passed` across the new merge regression, MemoryManager,
  memory-secret-boundary, and episodic-routing suites; `core.py` passed
  `py_compile`.
- Remaining risk: the 10,000-character bound is still a rough budget rather
  than model-specific token accounting; adaptive context budgeting remains a
  follow-up capability audit.

## Verified fix: timeout terminal-state parity

- Problem: the GUI recognized `run.timed_out` as terminal, while server and
  GUI Python run summaries only recognized success/failed/cancelled statuses;
  the main chat duration calculation also omitted timed-out runs.
- Root cause: terminal-state aliases were duplicated across backend and
  frontend projections without a complete shared terminal vocabulary.
- Fix: both Python summaries now recognize `timed_out`, `canceled`, and error
  terminal aliases (and the explicit timeout event type); the GUI duration
  path includes `run.timed_out`.
- Files: `server/__init__.py`, `gui/api.py`,
  `gui/src/components/MainChat.tsx`,
  `tests/test_run_summary_terminal_aliases.py`.
- Verification: `43 passed, 1 warning` across terminal-parity, server work-item,
  and GUI work-event suites; both Python modules passed `py_compile`.
- Remaining risk: terminal vocabulary is still represented in multiple
  language boundaries; a shared generated contract would reduce future drift.

## Verified fix: GUI timeout status label

- Problem: `useStreamChat` correctly classified timeout events as
  `timed_out`, but `MainChat`'s status-label switch had no matching case and
  displayed the user-facing state as generic `Stopped`.
- Fix: `MainChat` now renders the explicit `Timed out` label for that terminal
  status.
- Files: `gui/src/components/MainChat.tsx`,
  `tests/gui/scripts/test_timeout_status_contract.py`.
- Verification: `36 passed, 1 warning` across GUI work-event and timeout
  contract tests; `npm.cmd run build --prefix gui` passed TypeScript and Vite
  production build. Vite emitted only the existing large-chunk warning.
- Remaining risk: the frontend lifecycle vocabulary remains duplicated across
  TypeScript and Python; a shared generated contract remains desirable.

## Verified fix: canonical timeout event vocabulary

- Problem: `run.timed_out` was present in the canonical event type list and
  frontend projections, but `nexus.events.EVENT_STATUSES` rejected the
  corresponding `timed_out` status. A timeout event could therefore fail while
  being normalized into the shared event envelope.
- Root cause: timeout support had been added at the route/UI projection layers
  without extending the canonical status validator.
- Fix: `timed_out` is now an accepted canonical status and is preserved by
  `CanonicalEvent.from_work_event()`.
- Files: `nexus/events.py`, `tests/test_canonical_event_terminal_status.py`,
  `tests/gui/scripts/test_work_event_updates.py`.
- Verification: `37 passed, 1 warning` across canonical-event, timeout-summary,
  and GUI work-event tests.
- Remaining risk: lifecycle status sets are still duplicated across Python and
  TypeScript; generating them from one contract would reduce future drift.

## Verified fix: provider lease release on credential rejection

- Problem: a profile-selected provider could acquire its exclusive lease and
  then fail credential validation before entering the router retry/finally
  boundary. The lease remained held until expiry, unnecessarily blocking other
  workers from using that profile.
- Root cause: the early credential guard raised directly before the existing
  request-lifecycle cleanup.
- Fix: the credential-rejection path now releases the attached profile lease
  before raising the classified provider error.
- Files: `providers/router.py`, `tests/test_provider_router_attempts.py`.
- Verification: `20 passed` across provider attempt, streaming cleanup, and
  profile persistence/routing suites.
- Remaining risk: a provider can still hold a profile lease during a long
  stream until the fixed TTL unless renewal is added; this remains a separate
  long-stream lifecycle decision.

## Verified fix: long-stream profile lease renewal

- Problem: a named profile lease had a finite TTL for crash recovery, but a
  healthy streaming request longer than that TTL could continue after expiry;
  another worker could then claim the same profile concurrently.
- Root cause: lease cleanup existed at stream termination, but no renewal
  occurred while the provider iterator was still actively producing chunks.
- Fix: the router's leased-stream forwarding boundary renews an attached lease
  when it is within 30 seconds of expiry, updates the opaque lease token, and
  always releases the current token on completion, failure, or consumer close.
  If ownership cannot be renewed, the stream stops with an explicit provider
  error rather than continuing under uncertain ownership. Providers without a
  profile lease are unchanged.
- Files: `providers/router.py`,
  `tests/test_main/scripts/test_provider_router_stream.py`.
- Verification: `22 passed` across streaming renewal/cleanup, router attempt,
  and profile persistence/routing suites; `providers/router.py` passed
  `py_compile`.
- Remaining risk: renewal occurs between produced chunks; a provider that
  stalls without yielding longer than the lease TTL still needs a transport
  timeout or a dedicated heartbeat contract to avoid an idle-iterator gap.

## Verified fix: cross-process approval resolution

- Problem: the durable approval broker allowed one process to resolve a
  request in SQLite, but a waiter in another process slept only on its local
  `asyncio.Event`. The decision was durable yet invisible to the waiting loop
  until the full approval timeout elapsed.
- Root cause: the event notification path was process-local and the durable
  store was consulted only during setup/expiry, not while waiting.
- Fix: persistent waiters now keep the local event as the low-latency path and
  poll the approval row at a bounded 250 ms cadence. A cross-process decision
  is returned promptly, while expiry still fails closed to denial.
- Files: `permissions/approval_broker.py`,
  `tests/core/test_approval_broker.py`.
- Verification: `34 passed` across durable approval broker and permission
  integration tests.
- Remaining risk: SQLite polling is intentionally simple and bounded; a future
  multi-process notification mechanism could reduce polling overhead at high
  approval volume.

## Verified fix: PAORR approval failure closes safely

- Problem: the compatibility PAORR planner treated an exception from a
  configured approval callback as approval and proceeded to tool execution.
  This contradicted the canonical V5 approval path, which fails closed.
- Root cause: the callback wrapper was designed around avoiding freezes and
  converted an unknown authorization result into `True`.
- Fix: an absent callback still means approval is not configured and passes
  through; a configured callback that raises now returns denial, clears plan
  steps, and prevents tool execution.
- Files: `orchestrators/v5/paorr.py`,
  `tests/v5/test_v5_plan_visibility.py`.
- Verification: `35 passed` across PAORR plan visibility/execution-integrity
  and durable approval broker tests.
- Remaining risk: PAORR remains a compatibility layer alongside the direct V5
  loop; future consolidation would reduce duplicated authorization semantics.

## Verified fix: cross-process run cancellation refresh

- Problem: a running V5 process loaded durable cancellation only during run
  registration. A cancellation issued by another API/runtime process was
  persisted but did not set the local control event, so the active loop could
  continue until another local state transition or deadline.
- Root cause: `RunControlRegistry.get()` was memory-only after registration;
  the cooperative `_abort_requested()` boundary never re-read the durable
  cancellation record.
- Fix: `RunControlRegistry.refresh_cancel()` imports an existing durable
  cancellation without rewriting it, and V5 abort checks invoke that refresh
  before evaluating the current control. In-memory callers retain the fast
  event path.
- Files: `nexus/run_control.py`, `orchestrators/v5/control.py`,
  `tests/v5/test_v5_run_control.py`.
- Verification: `44 passed, 8 warnings` across run-control, direct-model-loop,
  and cancellation-token tests.
- Remaining risk: cancellation remains cooperative; a blocking provider or
  subprocess must still honor its own bounded timeout for prompt interruption.

## Verified fix: active provider/tool waits observe durable cancellation

- Problem: phase-boundary refresh fixed cancellation between phases, but the
  active model-stream loop and tool wait loop read only their cached
  `RunControl`. A stop request from another runtime process could therefore
  wait until the provider/tool yielded or its timeout elapsed.
- Root cause: both loops bypassed the canonical durable refresh while waiting
  on streaming or asynchronous work.
- Fix: model streaming now invokes the canonical abort check (with a direct
  refresh fallback for the mixin in isolation), and `_await_run_budget()`
  refreshes durable cancellation on each bounded wait interval before checking
  the control event. Existing local in-memory cancellation remains immediate.
- Files: `orchestrators/v5/model.py`, `orchestrators/v5/tools.py`,
  `tests/v5/test_v5_run_control.py`.
- Verification: `70 passed, 8 warnings` across run-control, model/tool loop,
  and tool-registry suites.
- Remaining risk: truly blocking synchronous provider or subprocess code can
  still require its own transport/process timeout; Python cannot safely kill an
  arbitrary worker thread.

## Verified fix: sandbox child cleanup on cancellation

- Problem: cancelling a V5 command while `SovereignSandbox.stream_execute()`
  was blocked in `stdout.read()` closed the async generator without entering
  its timeout handler. The child process could remain alive and retain pipes
  after the tool had returned cancellation.
- Root cause: process termination existed only in the explicit
  `asyncio.TimeoutError` branch; generator close/cancellation had no owning
  `finally` cleanup.
- Fix: the sandbox now has an idempotent kill-and-reap helper and invokes it in
  `finally` whenever the subprocess is still running. Timeout behavior remains
  unchanged, while cancellation and early generator close now release the
  child resource.
- Files: `sandbox/sandbox_manager.py`,
  `tests/test_main/scripts/test_shell_tools_sandbox.py`.
- Verification: `30 passed` across sandbox workspace, shell-tool, and V5
  cancellation tests.
- Remaining risk: killing a shell process may not terminate independently
  detached descendants on every platform; process-group/job-object ownership
  is a follow-up hardening target.

## Verified fix: sandbox descendant process ownership

- Problem: direct-child kill/reap did not guarantee cleanup of descendants
  spawned by a shell, leaving a path for orphaned workers and inherited pipes.
- Root cause: host subprocesses were launched without an explicit process-group
  boundary, so cleanup had no safe ownership scope beyond the immediate child.
- Fix: host commands now launch with a Windows new process group or a POSIX
  new session. Cleanup attempts Windows `taskkill /T /F` or POSIX process-group
  termination, then performs the direct-child kill fallback and always waits
  for the child to be reaped. Docker launch behavior is unchanged because the
  container runtime owns its process tree.
- Files: `sandbox/sandbox_manager.py`,
  `tests/test_main/scripts/test_shell_tools_sandbox.py`.
- Verification: `36 passed` across shell sandbox, workspace-security, and V5
  cancellation suites.
- Remaining risk: detached processes that deliberately escape the process
  group/job boundary remain outside ordinary cleanup guarantees.

## Verified fix: effective model timeout propagation

- Problem: V5 wrapped synchronous model calls in an asyncio timeout, but the
  underlying router/provider request did not receive that deadline. A caller
  could return while a provider thread continued using sockets and holding a
  profile lease until the provider's own fixed timeout.
- Root cause: the timeout existed only at the `asyncio.wait_for()` boundary and
  was not part of the model request contract.
- Fix: text, structured, and final-answer streamed V5 model calls now pass the
  effective, run-budget-clamped timeout through the router as `timeout`,
  allowing providers that honor request kwargs (including
  OpenRouter/Universal/CommandCode paths) to stop at the same deadline.
  Existing provider/model kwargs remain intact.
- Files: `orchestrators/v5/model.py`,
  `tests/v5/test_v5_run_control.py`.
- Verification: `60 passed, 8 warnings` across run-control, direct-model-loop,
  and provider lifecycle/streaming suites.
- Remaining risk: several legacy HTTP adapters still use hard-coded request
  timeouts and need adapter-by-adapter migration to consume the shared value;
  Python cannot forcibly stop a thread whose transport ignores its timeout.

## Verified fix: common provider adapters honor transport deadlines

- Problem: the V5/router timeout contract reached providers as `timeout`, but
  common adapters still replaced it with fixed 30/60/120-second values.
- Root cause: timeout policy was duplicated inside each HTTP adapter instead of
  being normalized at the shared provider boundary.
- Fix: `NexusBaseProvider.request_timeout()` validates the caller value and
  falls back safely for invalid/non-positive input. OpenAI, Anthropic, Gemini,
  Groq, DeepSeek, Azure OpenAI, Fireworks, Cohere, Hugging Face, LM Studio,
  Mistral, NVIDIA, xAI, VLM, Universal, Together, SambaNova, Replicate, Qwen,
  Perplexity, and Ollama unary/streaming adapters now use it for `requests`
  calls where supported.
- Files: `providers/base.py` and the migrated provider adapters,
  `tests/test_provider_request_timeout.py`.
- Verification: `52 passed` across adapter timeout, provider reliability,
  profile/lease, router lifecycle, and V5 run-control tests; all migrated
  provider modules passed `py_compile`.
- Remaining risk: CLI/subprocess adapters have separate timeout contracts and
  need their own process-tree audit rather than a blind HTTP timeout rewrite.

## Verified fix: CommandCode CLI process cleanup

- Problem: CommandCode's unary CLI path relied on `subprocess.run()` timeout
  behavior, while its streaming path killed on timeout without waiting and had
  no cleanup when the generator was abandoned. Shell descendants could remain
  alive with inherited pipes.
- Root cause: CLI process ownership was not shared with the sandbox/provider
  process-tree contract, and the streaming generator lacked a `finally` path.
- Fix: `NexusBaseProvider` now provides process-group launch options and a
  terminate-and-reap helper. CommandCode unary and streaming CLI paths use
  `Popen`, bounded communicate/wait timeouts, process-tree termination, and
  final cleanup.
- Files: `providers/base.py`, `providers/commandcode.py`,
  `tests/test_commandcode_process_cleanup.py`.
- Verification: `19 passed` across CommandCode cleanup, OpenCode CLI
  compatibility, provider timeout, and router lifecycle tests.
- Remaining risk: HTTP CommandCode remains covered by the shared adapter
  timeout helper; local CLI behavior still depends on the installed CLI's
  output contract.

## Verified fix: OpenCode CLI process ownership and footer compatibility

- Problem: OpenCode CLI used a synchronous `subprocess.run()` path with no
  explicit process-group ownership. Its footer cleaner also depended on one
  particular encoding of the `> plan` terminal footer, allowing a correctly
  decoded footer to leak into model output.
- Root cause: the adapter predated the shared provider process lifecycle
  contract, and treated the footer separator as stable data rather than
  terminal metadata.
- Fix: the adapter now uses `Popen` with process-group launch options,
  bounded `communicate(timeout=...)`, shared terminate-and-reap cleanup on
  timeout and finalization, and the shared validated request timeout. Footer
  removal matches the stable prefix so both Unicode and mojibake separators
  are handled.
- Files: `providers/opencode_cli.py`,
  `tests/test_main/scripts/test_opencode_cli_provider.py`.
- Verification: `20 passed` across OpenCode CLI cleanup/compatibility,
  CommandCode process cleanup, provider timeout, and router attempt tests.
- Remaining risk: the installed OpenCode CLI itself was not available for a
  live subprocess integration run in this environment; tests cover the
  adapter contract with controlled process fixtures.

## Verified audit: FAISS fallback warning and lazy initialization

- Finding: the historical P1 report claimed 19 repeated FAISS warnings during
  import/startup. Current source does not load FAISS or the transformer model
  in `NATE_Route.__init__`; `_lazy_load_faiss()` runs on registration/query and
  guards its fallback warning with a process-wide class attribute.
- Reproduction: forcing every FAISS import to raise `ImportError` across 19
  router instances produced exactly one warning. All routers retained the
  NumPy fallback (`_index is None`), and normal construction took `0.01 ms` in
  the measured run; 19 registrations completed in `7.59 ms`.
- Verification: `33 passed` across NATE routing-quality and adaptive-schema
  tests, including the new repeated-instance warning regression.
- Decision: mark P1-1 resolved in `ISSUE_LIST.md`; do not add another warning
  suppression layer. The separate server-startup audit is recorded below.

## Verified fix: server launcher process-tree ownership

- Finding: the historical P1 startup report was not reproducible in the
  current checkout. Importing `server` took about `346 ms`, lifespan entry
  about `3 ms`, TestClient startup about `254 ms`, and a real
  `python -m nexus --server` reached port 8000 in `1302 ms`.
- Problem found during that real run: `--server` launched `python -m server`
  as a child but only terminated the launcher wrapper. On Windows, the child
  could survive and keep port 8000 open after the wrapper stopped.
- Root cause: no process-group ownership or `finally`-based terminate/reap
  boundary around the launcher-owned API child.
- Fix: server, GUI-backend, and Ink-TUI-backend children now start in an owned
  process group/session and the launcher terminates the tree and waits for the
  child on interruption or normal cleanup. The GUI frontend now uses the same
  owned foreground-process wrapper instead of an unowned `subprocess.run()`.
- Files: `nexus/__init__.py`, `tests/test_boot_setup_marker.py`.
- Verification: `36 passed` across boot, queue-supervisor, and command-timeout
  surfaces. The test-run process tree was explicitly checked and cleaned up;
  the foreground wrapper also has a controlled reaping regression test.
- Remaining risk: a live npm/Vite integration run was not performed because
  the GUI dev server would require a separate interactive process and port;
  stale-port behavior still needs an end-to-end test with the frontend toolchain.

## Verified fix: cross-platform GUI stale-port cleanup

- Problem: `_kill_windows_port()` returned immediately on Linux/macOS, so a
  stale Nexus API or Vite listener could survive GUI/TUI restart and cause a
  bind failure or attachment to the wrong process.
- Root cause: cleanup was implemented as a Windows-only `netstat`/`taskkill`
  path even though the launcher exposes the same designated ports on all
  platforms.
- Fix: the compatibility-named helper now uses `psutil` on every platform,
  identifies listeners on the designated 8000/5173 ports, filters to Nexus API
  or GUI-toolchain command lines, terminates descendants and parents, waits,
  and force-kills only processes that remain alive. Unrelated listeners are
  left untouched.
- Files: `nexus/__init__.py`, `tests/test_boot_setup_marker.py`.
- Verification: `37 passed` across boot, queue-supervisor, and command-timeout
  surfaces, including a forced non-Windows Vite listener fixture.
- Remaining risk: live Vite restart behavior still needs an end-to-end test;
  the controlled process-discovery and cleanup contract is covered.

## Verified fix: Windows command compatibility guard

- Problem: the default Windows `cmd.exe` execution path could receive common
  Unix commands such as `cat` and `grep`, producing a failed subprocess with
  no platform-specific recovery guidance.
- Root cause: the compatibility guard only recognized `head` and `tail`, while
  the live prompt and tool layer still allow models to propose broader Unix
  read/search commands.
- Fix: `SovereignSandbox._windows_cmd_compatibility_error()` now detects
  unquoted `cat`, `grep`, `sed`, `awk`, `head`, `tail`, `ls`, `pwd`, and `which`
  tokens before spawning `cmd.exe`. Explicit `shell='powershell'`/`bash`
  requests remain unchanged, and the error recommends native alternatives.
- Files: `sandbox/sandbox_manager.py`,
  `tests/test_main/scripts/test_sandbox_workspace_scope.py`.
- Verification: simulated Windows execution of `cat README.md | grep Nexus`
  was rejected before process creation; `20 passed` across sandbox, shell,
  and command-timeout tests.
- Remaining risk: arbitrary user-authored commands remain intentionally
  explicit; the guard is a recovery aid, not a silent command rewriter.

## Verified audit: ToolRegistry structured metadata contract

- Finding: the historical P2-1 report claimed `ToolRegistry.list_tools()`
  returned strings. Current implementation returns a keyed structured summary
  for each tool, with availability, missing environment, handler presence,
  version/description, and execution constitution fields.
- Call-site trace: server `/api/tools`, GUI `build_tool_state`, V5 planning,
  grounding, direct-loop, compatibility, and core paths either intentionally
  iterate mapping keys or consume summary values; no caller was found treating
  a current summary value as a bare string.
- Fix: clarified the return annotation and docstring so the contract is
  explicit, and added a regression covering the structured summary shape.
- Files: `tools/nexus_tools/registry.py`,
  `tests/test_tool_registry/scripts/test_tool_registry.py`.
- Verification: `112 passed, 8 warnings` across registry, MCP lifecycle/tool,
  security-boundary, and V5 direct-loop caller suites.
- Decision: mark P2-1 resolved as a stale issue-list entry; no compatibility
  rewrite was necessary.

## Verified fix: advertised intelligence adapters no longer fake success

- Problem: `ModelRouter`'s synchronous `HYBRID` path called
  `MixtureOfArchitects.aggregate()`, which returned an empty OpenAI-shaped
  response. The optional local-brain optimization called a nonexistent
  `generate()` method, so it could never produce local inference.
- Root cause: both compatibility modules were placeholders disconnected from
  the already-working provider factory/MoE routing path.
- Fix: the MOA facade now delegates to the configured MoE provider mesh and
  returns explicit `[MOA_ERROR]` results on unavailable/empty failure. The
  local brain now lazily selects configured local providers (LM Studio,
  Ollama, llama.cpp, or Zupra), tries bounded local fallbacks, supports unary
  and streaming generation, and returns `[LOCAL_BRAIN_ERROR]` rather than a
  fake answer. Image scanning reports unsupported local vision explicitly.
- Files: `intelligence/moa.py`, `intelligence/local_brain.py`,
  `tests/test_intelligence_adapters.py`, `intelligence/read.md`, `README.md`.
- Verification: `57 passed` across intelligence adapters, kernel loading,
  provider routing/streaming, skills, and plugins.
- Remaining capability gap: no true multi-model ensemble policy or local VLM
  backend is silently implied; those are explicit future capabilities.

## Live execution trace (source-backed)

The current request path is:

1. `nexus/__main__.py` delegates to `nexus.boot()` in `nexus/__init__.py`.
2. The server route `server/__init__.py:2762` parses `/api/chat`, resolves the
   session loop, normalizes provider/model/profile, and calls
   `NexusLoop.stream_run()`.
3. The GUI route `gui/api.py:1697` resolves a session loop through
   `gui/api.py:1460`, attaches `bind_live_work_event_sink()` at line 1493, and
   runs the same `stream_run()` contract on a worker thread/event loop adapter.
4. `orchestrators/v5/core.py:1701` enters `stream_run()`, which delegates to
   `_turn_events()` at line 1800. The loop owns run locking, deadlines,
   checkpoints, lifecycle events, and terminal persistence.
5. The live tool path is
   `orchestrators/v5/direct_loop.py:643` → `_stream_model()` in
   `orchestrators/v5/model.py:274` → model/tool-call parsing → permission and
   tool execution in `orchestrators/v5/tools.py` →
   `tools/nexus_tools/registry.py:726`.
6. Registry execution applies availability, concurrency, cancellation, timeout,
   result normalization, output persistence, and structured error status before
   the observation is appended to the model transcript.
7. Canonical events flow through the route sink into durable work-event storage;
   the server and GUI streams expose public events, while workflow completion
   records the terminal task status.

This trace is now verified from current source and the V5/server regression
tests, not inferred from directory names. Remaining work is to exercise the
same path with real local-provider/tool fixtures and continue the disconnected
subsystem audit.

## Verified fix: Ink TUI cancellation reaches the durable backend run

- Problem: GUI Stop already posted `/api/chat/{session_id}/cancel`, but Ink
  Escape and `/stop` only aborted the local `fetch()` reader. The provider,
  tool, and sandbox work owned by the server could therefore continue after
  the TUI reported cancellation.
- Root cause: the TUI had no active server-run identity and no cancellation
  request at its local abort boundary.
- Fix: `tui/nexus-tui.tsx` and the maintained `_repro-app.tsx` compatibility
  copy now track the first observed canonical `run_id`/`turn_id`, post the
  durable cancel endpoint with that identity, and then abort local rendering.
  Escape, `/stop`, and `/retry` use the same path; backend errors are
  best-effort because the local stream must still be able to stop.
- Files: `tui/nexus-tui.tsx`, `tui/_repro-app.tsx`,
  `tui/cancellation-contract.test.ts`, `tui/package.json`.
- Verification: `npm.cmd run build` passed; `npm.cmd test` passed with the
  new cancellation contract included (25 modular/component checks plus the
  existing TUI suites).
- Remaining risk: cancellation is still cooperative for an external provider
  that ignores request cancellation; the backend wait/cleanup hardening is
  covered separately in the V5 and sandbox tests.

## Verified fix: server cancellation route reaches a live V5 tool wait

- Problem: route-level cancellation coverage used inert fake loops, while V5
  cancellation coverage called the executor directly. A regression between
  those boundaries could return `cancelled` to the UI while an actual tool
  wait continued.
- Fix: the server parity suite now connects `server.cancel_chat()` to a shared
  durable `RunControlRegistry`, runs a real `V5ToolExecutor._await_run_budget`
  wait, invokes the route handler, and asserts the wait exits with the
  operator cancellation reason.
- Files: `tests/test_server/scripts/test_chat_runtime_parity.py`.
- Verification: the server chat-parity, V5 run-control, and GUI work-event
  partitions passed together: `64 passed, 1 warning` in 64.44 seconds.

## Verified fix: gateway delivery leases renew during slow sends

- Problem: expired-lease recovery was present, but a live external send had no
  heartbeat. A platform call longer than the default 60-second lease could be
  reclaimed by another worker and sent twice before the original worker
  acknowledged it.
- Root cause: the ledger had claim/ack/fail transitions but no guarded lease
  extension, and `GatewayRunner._drain_deliveries()` awaited adapters without
  renewing ownership.
- Fix: `DeliveryLedger.renew()` performs a compare-and-update scoped to the
  current owner and leased state. `GatewayRunner` starts a bounded heartbeat
  task for each send and cancels it after ack/fail, preserving at-least-once
  semantics without stale workers reviving reclaimed rows.
- Files: `gateway/delivery.py`, `gateway/run.py`,
  `tests/test_gateway_delivery.py`.
- Verification: gateway delivery/runtime and reliability partitions passed:
  `25 passed` in 9.23 seconds.
- Remaining risk: at-least-once delivery still permits duplicates across a
  crash after remote acceptance and before acknowledgement; platform-level
  idempotency remains the correct final defense.

## Verified fix: all memory channels reach V5 planning context

- Problem: `MemoryManager.prefetch_all()` populated eight memory channels, but
  V5 perception injected only session, RAG, and failure context; its `[:3]`
  slice also dropped knowledge. Planning could therefore choose a plan without
  episodic, working, semantic, procedural, or knowledge evidence even though
  execution later received a broader merge.
- Root cause: the perception boundary manually rebuilt a partial memory list
  instead of treating the prefetched snapshot as the canonical bounded input.
- Fix: V5 perception now includes all non-empty memory channels in a
  per-channel bounded recall block, so large session/RAG text cannot starve
  procedural or episodic evidence. It also preserves the full snapshot in turn
  metadata for the later execution merge.
- Files: `orchestrators/v5/core.py`,
  `tests/v5/test_v5_memory_context_merge.py`.
- Verification: the memory-context regression now covers all-channel injection
  and starvation, and the memory-manager, continuity, direct-loop, and
  task-identity partitions passed; `py_compile` passed for the changed Python
  modules.
- Remaining risk: the wider model transcript still uses separate compaction
  paths; context-budget/compaction audit remains next to verify critical
  evidence is preserved across provider overflow and retry.

## Verified fix: context compaction enforces budget on recent-only transcripts

- Problem: `context.compact_messages()` returned unchanged messages when all
  non-system messages were within `keep_recent`, even if the system prompt
  plus those recent messages exceeded the configured token budget. This could
  send an oversized request without compaction or an explicit boundary.
- Root cause: the `not head` early return bypassed `_fit_budget`; `_fit_budget`
  also shallow-copied messages and could mutate the caller's live system
  message while trimming.
- Fix: recent-only transcripts now pass through the budget fitter. Fitting uses
  a deep copy, preserves tool-call/result pairing while removing non-system
  entries, and marks system truncation when the hard budget leaves room for a
  marker.
- Files: `context/__init__.py`, `tests/test_redesign_context.py`.
- Verification: context, prompt-context, and V5 compaction partitions passed:
  `33 passed` in 0.97 seconds.
- Remaining risk: a system prompt larger than the configured budget cannot be
  preserved in full and still meet the hard limit; callers should treat that
  explicit truncation marker as a configuration/budget signal.

## Verified fix: billing/quota failures no longer retry as rate limits

- Problem: provider text containing `quota` was classified as retryable
  `rate_limit`, so exhausted credits, payment requirements, and spending
  limits could trigger repeated calls to a provider that could not recover via
  backoff.
- Fix: `FailureClass.BILLING_QUOTA` is now distinct, mapped to HTTP 402 and
  billing/quota phrases such as `quota exceeded`, `credits exhausted`, and
  `spending limit`; its policy fails fast for the current provider and selects
  a provider fallback. Ordinary 429/"too many requests" remains retryable
  `RATE_LIMIT`.
- Files: `providers/reliability.py`, `tests/test_redesign_reliability.py`.
- Verification: reliability, provider-attempt, provider-status, and profile
  routing partitions passed: `31 passed` in 8.32 seconds.
- Remaining risk: provider-specific billing wording not covered by the phrase
  classifier may still resolve to `UNKNOWN`; future telemetry should add safe
  vendor examples without logging secrets.

## Verified fix: provider health registry is concurrency-safe

- Problem: the router shares `ProviderHealthRegistry` across concurrent
  provider calls, but its dictionary reads/writes were unsynchronized. Health
  telemetry and routing decisions could race during simultaneous failures and
  successes.
- Fix: health state mutations, snapshots, lookups, and degradation checks now
  use a reentrant lock while retaining existing decay and capability behavior.
  Capability preservation no longer constructs a throwaway default record on
  every update.
- Files: `providers/health.py`,
  `tests/test_provider_health_routing_loop.py`.
- Verification: provider-health, attempts, router-attempt, and streaming
  partitions passed: `23 passed` in 0.40 seconds.
- Remaining risk: the in-memory fallback is process-local; when the optional
  SQLite store is unavailable, separate workers rely on their own circuit
  breakers and cannot share advisory health.

## Verified fix: provider health crosses runtime process boundaries

- Problem: provider health was synchronized within one process, but separate
  Nexus server/GUI/gateway runtimes each maintained an independent registry.
  One worker could mark a provider unhealthy while another immediately retried
  it.
- Fix: `ProviderHealthRegistry` now accepts an optional SQLite store, persists
  redacted health/capability/latency records, reloads newer records on reads,
  and retains in-memory operation if persistence is unavailable. `ModelRouter`
  wires its kernel root to `.nexus/provider_health.sqlite3`; the existing
  60-second degradation TTL still prevents stale failures from becoming a
  permanent ban.
- Files: `providers/health.py`, `providers/router.py`,
  `tests/test_provider_health_routing_loop.py`.
- Verification: provider-health cross-instance/concurrency, router, profile,
  attempt, and streaming partitions passed: `35 passed` in 1.90 seconds.
- Remaining risk: SQLite health is advisory telemetry; circuit breakers remain
  process-local and protect each worker independently during database outages.

## Verified fix: provider router compacts once on context overflow

- Problem: direct V5 model calls had a compact-and-retry path, but
  `ModelRouter.generate()` and `stream_generate()` treated provider context
  overflow as an ordinary failure and retried/fell back with the same
  oversized transcript.
- Root cause: router fallback selection had failure classification but no
  context-recovery boundary; streaming retry limits also left no room for a
  compaction-specific attempt when `max_attempts` was one.
- Fix: both sync and streaming router paths now use the shared
  call/result-safe compactor for one bounded overflow retry. The streaming
  path grants only that extra attempt when compaction actually reduced the
  transcript, preserves explicit-provider authority, and continues to reject
  fallback splicing after partial output.
- Files: `providers/router.py`, `tests/test_provider_router_attempts.py`,
  `tests/test_main/scripts/test_provider_router_stream.py`.
- Verification: router attempt, streaming-router, and direct-loop overflow
  partitions passed: `25 passed` in 2.01 seconds.
- Remaining risk: a provider with an unknown context limit uses a 70% retry
  target; provider-specific metadata should improve that target where exposed.

## Verified fix: durable watchdog cannot be frozen by cancellation-resistant work

- Problem: stale durable-job recovery cancelled local runner tasks and awaited
  them without a bound. A task that swallowed `CancelledError` could therefore
  freeze the watchdog indefinitely, preventing recovery of unrelated jobs.
- Root cause: cancellation was treated as an immediately terminal operation,
  even though external subprocesses and libraries may stop only cooperatively.
- Fix: `watchdog_durable_background_tasks()` now uses bounded
  `asyncio.wait()` cancellation handling. Completed tasks are drained; still
  pending tasks remain fenced in the active task map, so the stable task ID is
  not scheduled a second time while the old owner is alive. A later recovery
  pass can rehydrate it after the old task exits.
- Files: `orchestrators/v5/background_runner.py`,
  `tests/v5/test_v5_background_runner.py`.
- Verification: the complete durable background runner partition passed:
  `12 passed` in 1.82 seconds, including a regression where the factory
  deliberately ignores cancellation until released.
- Remaining risk: a cancellation-resistant task can still consume resources
  until its underlying operation exits; process-level ownership and sandbox
  cleanup remain the correct escalation boundary for untrusted subprocesses.

## Verified fix: V5 edit quality gates validate the written result

- Problem: the V5 registry-tool path ran `_lint_source()` before
  `modifying`/`creating` executed, so it validated the old file. An invalid
  edit could then be reported as successful. If the validator itself failed,
  the broad exception handler also returned success.
- Root cause: quality validation was placed at the request preflight boundary
  instead of the mutation commit boundary, with fail-open error semantics.
- Fix: V5 captures the target before mutation, keeps the preflight check, then
  validates the post-write target before emitting `done`. Failed validation
  restores the captured bytes (or removes a newly created file) and emits an
  explicit tool error. Validator failures now fail closed for existing files.
- Files: `orchestrators/v5/tools.py`, `tests/v5/test_v5_tool_gates.py`.
- Verification: tool-gate, registry, and redesign-tool partitions passed:
  `60 passed` in 1.38 seconds; `py_compile` and `git diff --check` passed.
- Remaining risk: validation currently covers syntax/parse checks supported by
  `_lint_source`; semantic test execution remains a separate verification
  stage and must not be silently substituted for syntax validation.

## Verified fix: MCP process lifecycle is single-owner per client

- Problem: MCP tool calls are dispatched through worker threads. Concurrent
  first calls could both observe an absent/dead process and launch separate
  child servers for one configured MCP client. Concurrent transport failures
  could also enter overlapping reconnect cycles.
- Root cause: the response lock protected request bookkeeping only; start,
  stop, and recovery had no shared lifecycle ownership boundary.
- Fix: `MCPClient` now uses a reentrant lifecycle lock around start, stop, and
  bounded recovery. The reentrant form permits initialization/recovery to call
  the nested transport methods without deadlock while preventing duplicate
  process creation and overlapping reconnect/parking transitions.
- Files: `mcp/client/scripts/client.py`,
  `tests/test_main/scripts/test_tool_security_boundaries.py`.
- Verification: MCP security, lifecycle, adapter, and redesign-tool partitions
  passed: `54 passed` in 0.54 seconds; `py_compile` and `git diff --check`
  passed.
- Remaining risk: a blocking MCP call still relies on its bounded queue timeout;
  cancelling the surrounding `asyncio.to_thread()` cannot forcibly stop the
  underlying Python worker, so process-level stop remains the escalation path.

## Verified fix: provider reliability preserves cancellation control flow

- Problem: `call_with_reliability()` caught `BaseException` around async and
  sync provider calls. In modern Python, `asyncio.CancelledError` is a
  `BaseException`; operator cancellation was therefore classified as an
  unknown/retryable provider failure and could be retried or rewritten as a
  `ProviderCallError`.
- Root cause: the retry wrapper treated every non-success signal as an
  operational provider failure instead of separating caller control flow from
  provider faults.
- Fix: async cancellation is explicitly re-raised, and both wrappers now
  classify ordinary `Exception` failures only. Provider retries remain bounded
  while cancellation reaches the run-control boundary immediately.
- Files: `providers/reliability.py`, `tests/test_redesign_reliability.py`.
- Verification: reliability, provider-attempt, sync-router, and streaming
  router partitions passed: `32 passed` in 6.20 seconds; `py_compile` and
  `git diff --check` passed.
- Remaining risk: provider implementations that catch cancellation internally
  can still delay shutdown; the router cannot override a provider that refuses
  to cooperate, so stream/process ownership remains the escalation boundary.

## Verified fix: streaming fallback releases rejected profile leases

- Problem: streaming fallback resolution can acquire a credential profile lease
  before credential validation. When the fallback provider was rejected by
  `_provider_credentials_usable()`, the router skipped it without releasing
  the lease, pinning that profile until TTL expiry and reducing future routing
  capacity.
- Root cause: the success/exception paths released leases, but the early
  credential-rejection branch had no terminal cleanup path.
- Fix: the stream fallback branch now explicitly releases the provider lease
  before continuing to the next fallback candidate.
- Files: `providers/router.py`,
  `tests/test_main/scripts/test_provider_router_stream.py`.
- Verification: streaming-router, provider-attempt, and profile-routing
  partitions passed: `25 passed` in 1.71 seconds; `py_compile` and
  `git diff --check` passed.
- Remaining risk: a provider factory that leaks a lease before returning an
  object cannot be cleaned by the router because no provider object is exposed;
  factory acquisition should remain exception-safe as a separate boundary.

## Verified fix: Discord gateway task failures reach supervision

- Problem: `DiscordAdapter.connect()` launched `client.start()` as a detached
  task and immediately returned healthy. A later gateway failure became an
  unobserved task exception, leaving the supervisor believing the platform was
  running; disconnect also cancelled the task without awaiting it.
- Root cause: the long-lived SDK task had no owner callback or shutdown join.
- Fix: the adapter now owns the task, projects unexpected completion/failure to
  `unavailable`/`recovering` with a diagnostic error, and awaits cancellation
  during disconnect. Intentional shutdown cancellation is ignored.
- Files: `gateway/platforms/discord.py`,
  `tests/test_gateway_telegram_discord.py`.
- Verification: Discord/Telegram adapter, gateway lifecycle, and delivery
  partitions passed: `37 passed, 2 skipped` in 6.74 seconds; `py_compile` and
  `git diff --check` passed.
- Remaining risk: other optional adapters with long-lived SDK tasks may still
  need the same ownership audit; Slack Socket Mode is covered below.

## Verified fix: Slack Socket Mode task failures reach supervision

- Problem: Slack `connect()` launched `SocketModeClient.connect()` with a
  detached task and returned success before the socket transport had a
  lifecycle owner. Socket failures were therefore invisible to the gateway
  supervisor, and shutdown did not await the task.
- Root cause: the adapter tracked the SDK client but not its long-lived async
  task or terminal state.
- Fix: the adapter now owns `_socket_task`, projects unexpected completion or
  failure to `unavailable`/`recovering`, and joins cancellation during
  `disconnect()`. Intentional shutdown cancellation is ignored.
- Files: `gateway/platforms/slack.py`,
  `tests/test_gateway_slack_adapter.py`.
- Verification: Slack, Discord/Telegram, gateway lifecycle, and delivery
  partitions passed: `39 passed, 2 skipped` in 4.51 seconds; `py_compile` and
  `git diff --check` passed.
- Remaining risk: other optional adapters with long-lived SDK tasks still need
  the same ownership audit; the next pass will inspect their task registries
  and disconnect joins.

## Verified fix: optional gateway adapters join owned background tasks

- Problem: Mattermost WebSocket, Matrix sync, Email IMAP, Signal receipt poll,
  and SMS webhook tasks were cancelled during disconnect but not awaited.
  Closed clients could therefore race still-running tasks, leak task
  exceptions, or leave work alive after the supervisor reported shutdown.
- Root cause: each adapter duplicated cancellation without a common ownership
  contract, and most paths discarded the task reference immediately.
- Fix: `BasePlatformAdapter._cancel_task()` now performs bounded cooperative
  cancellation by requesting cancellation, awaiting the task, and logging any
  unexpected shutdown exception. The affected adapters clear their reference
  only after transferring it to this join helper.
- Files: `gateway/base.py`, `gateway/platforms/mattermost.py`,
  `gateway/platforms/matrix.py`, `gateway/platforms/email.py`,
  `gateway/platforms/signal.py`, `gateway/platforms/sms.py`.
- Verification: the complete gateway adapter/lifecycle partition passed:
  `217 passed, 2 skipped` in 4.37 seconds; all changed modules passed
  `py_compile` and `git diff --check`.
- Remaining risk: the SMS webhook runs a blocking Flask development server in
  an async task; the dedicated-thread fix is recorded below.

## Verified fix: SMS webhook no longer blocks the asyncio runtime

- Problem: `SMSAdapter._run_webhook()` called Flask `app.run()` directly from
  an asyncio task. Flask's development server blocks the event-loop thread,
  starving gateway delivery, supervision, and all other adapters. Its request
  callback also attempted `asyncio.get_event_loop()` from the Flask worker
  thread, where no loop is guaranteed.
- Root cause: a synchronous WSGI server was treated as an async coroutine and
  the event-loop owner was not captured before crossing the thread boundary.
- Fix: the adapter now builds a stoppable Werkzeug server, runs
  `serve_forever()` through `asyncio.to_thread()`, captures the owning loop for
  `run_coroutine_threadsafe()`, reports dispatch failures, and calls
  `shutdown()` before joining the task.
- Files: `gateway/platforms/sms.py`,
  `tests/test_gateway_sms_adapter.py`.
- Verification: SMS/security/gateway adapter partitions passed:
  `186 passed` in 3.48 seconds; `py_compile` and `git diff --check` passed.
- Remaining risk: the webhook remains an embedded HTTP listener and should be
  deployed behind the project gateway/reverse proxy for production TLS and
  process isolation.

## Verified fix: V5 readiness probes do not block the event loop

- Problem: programmatic verification called synchronous `urllib.request.urlopen`
  and `time.sleep()` directly from the async verification coroutine. A slow or
  unavailable local health endpoint could therefore starve active runs,
  gateway heartbeats, and UI streaming for the entire readiness timeout.
- Root cause: the probe was implemented as a synchronous retry loop but invoked
  as though it were non-blocking async work.
- Fix: readiness probing now runs through `asyncio.to_thread()`, preserving the
  bounded retry semantics while keeping the event loop responsive.
- Files: `orchestrators/v5/programmatic_verify.py`,
  `tests/v5/test_v5_programmatic_verify.py`.
- Verification: programmatic verification and server endpoint partitions passed:
  `12 passed` in 0.76 seconds; `py_compile` and `git diff --check` passed. The
  regression confirms an async heartbeat continues during a deliberately slow
  readiness probe.
- Remaining risk: other synchronous workspace-summary and snapshot operations
  are intentionally exposed through synchronous FastAPI routes or background
  workers; their call sites remain under review before any broader migration.

## Verified fix: web-search DNS and response reads stay off-loop

- Problem: `WebSearchTool._fetch_url()` performed synchronous DNS resolution
  in the SSRF guard and synchronously consumed the urllib response after only
  moving the initial open into an executor. Slow name resolution or response
  bodies could still starve V5 streaming and gateway heartbeats.
- Root cause: the blocking network operation was split at the wrong boundary;
  only connection setup was offloaded while security resolution and body reads
  remained in the coroutine.
- Fix: the complete SSRF probe runs through `asyncio.to_thread()`, and a
  bounded helper opens, consumes, and closes the response in the worker thread.
  Existing private-address and metadata blocking remains unchanged.
- Files: `tools/web_search/scripts/web_search.py`,
  `tests/test_security/test_web_fetch_ssrf.py`.
- Verification: web-search and security partitions passed: `37 passed` in
  0.33 seconds; `py_compile` and `git diff --check` passed. The new regression
  confirms an async heartbeat continues during deliberately slow DNS work.
- Remaining risk: network cancellation cannot forcibly interrupt a blocking
  resolver on every platform; bounded request timeouts and worker completion
  remain the containment boundary.

## Verified fix: gateway supervisor serializes overlapping ticks

- Problem: the periodic supervisor and public `tick(once=True)` diagnostic
  calls could overlap. Both could observe the same runtime as restartable and
  invoke `adapter.connect()` concurrently; registration during an awaited tick
  could also invalidate direct dictionary iteration.
- Root cause: supervision had no lifecycle lock and iterated the live runtime
  mapping across awaits.
- Fix: `GatewaySupervisor` now serializes tick, start, and stop passes with an
  async lock and snapshots registered runtimes before awaiting adapter work.
  This preserves one-at-a-time connection decisions, makes shutdown wait for
  an in-flight connect before disconnecting/persisting `stopped`, and allows
  later registrations to be handled by the next pass.
- Files: `gateway/supervisor.py`,
  `tests/test_redesign_gateway_lifecycle.py`.
- Verification: gateway lifecycle plus durable background partitions passed:
  `21 passed` in 2.85 seconds; `py_compile` and `git diff --check` passed,
  including an in-flight-connect shutdown regression.
- Remaining risk: `register_runtime()` remains a synchronous mutation; a future
  dynamic gateway-management API should use the same ownership boundary if
  runtime registration becomes live at high rate.

## Verified fix: bounded code search stays off-loop

- Problem: `CodeSearchTool.execute()` was declared async but performed recursive
  `os.walk`, file `stat`, and full text reads synchronously. A large repository
  scan could therefore starve V5 streaming, gateway heartbeats, and cancellation
  handling despite the tool's existing byte limits.
- Root cause: bounded work was mistaken for non-blocking work; the scan had safety
  limits but no async execution boundary.
- Fix: the containment checks, ignored-directory filtering, byte budgets, and
  result limits remain in `_execute_sync()`, while the public async entry point
  delegates the complete scan to `asyncio.to_thread()`.
- Files: `tools/code_search/scripts/code_search.py`,
  `tests/test_security/test_path_traversal.py`.
- Verification: path-containment, code-search, and web-search partitions passed
  `18 passed` in 0.57 seconds; changed modules passed `py_compile` and
  `git diff --check`. The regression confirms an async heartbeat continues while
  a deliberately slowed search runs.
- Remaining risk: cancellation cannot forcibly interrupt an individual blocking
  filesystem call on every platform; existing scan byte/file/result limits bound
  the worker's work and result size.

## Verified fix: shortcut filesystem operations stay off-loop

- Problem: `ShortcutsTool.execute()` performed directory listing, recursive tree
  traversal, metadata reads, and recursive globbing synchronously inside an async
  tool method. Large trees could starve active runs and gateway heartbeats.
- Root cause: the tool exposed an async contract without moving its blocking
  filesystem implementation off the event-loop thread.
- Fix: the public async method now delegates the complete operation to
  `asyncio.to_thread()` while preserving workspace containment, action behavior,
  and output limits. The synchronous implementation is isolated in
  `_execute_sync()` for direct callers such as the task tool.
- Files: `tools/shortcuts/scripts/shortcuts.py`,
  `tests/test_security/test_path_traversal.py`.
- Verification: path-security, task-tool, and web-search partitions passed
  `26 passed` in 0.68 seconds; changed modules passed `py_compile` and
  `git diff --check`. The regression confirms an async heartbeat continues
  during a deliberately slowed shortcut operation.
- Remaining risk: direct internal callers of `_execute_sync()` remain synchronous
  by design and must only be used from worker/background contexts.

## Verified fix: planning and task persistence stay off-loop

- Problem: plan creation/update and checklist task operations performed local
  file I/O plus durable work-item reconciliation synchronously inside async tool
  methods. SQLite contention or a large migrated checklist could stall the main
  agent loop even though the operations were exposed as awaitable tools.
- Root cause: the async tool boundary stopped before the blocking persistence
  implementation; `TaskTool` also called planning's private synchronous helpers
  directly.
- Fix: `PlanningTool.execute()` and `TaskTool.execute()` now delegate their full
  persistence operations to worker threads, while retaining synchronous private
  helpers for already-offloaded internal callers and tests.
- Files: `tools/planning/scripts/planning.py`, `tools/task/scripts/task.py`,
  `tests/test_planning_work_items.py`, `tests/test_task_tool.py`.
- Verification: planning/task/V5 planning partitions passed `23 passed` in
  1.77 seconds; the broader planning, task, path-security, and V5 planning
  partition passed `39 passed` in 2.04 seconds. Changed modules passed
  `py_compile` and `git diff --check`; heartbeat regressions confirmed both
  tool boundaries remain responsive during deliberately slowed persistence.
- Remaining risk: concurrent plan/task writes still require the existing
  work-item/file consistency semantics; this change removes event-loop blocking
  but does not introduce a new transaction or per-workspace write lock.

## Verified fix: core file tools stay off-loop

- Problem: `ReadingTool`, `ModifyingTool`, `CreatingTool`, and `DeletingTool`
  synchronously opened, consumed, rewrote, created, or removed workspace files
  from async tool methods. Large source files or slow filesystem operations
  could block streaming, cancellation, and gateway heartbeats.
- Root cause: filesystem safety checks and file operations were implemented
  directly in the coroutine instead of behind a worker boundary.
- Fix: all four tools keep their existing containment and file semantics in
  `_execute_sync()` and delegate the complete operation through
  `asyncio.to_thread()` from the public async method.
- Files: `tools/reading/scripts/reading.py`,
  `tools/modifying/scripts/modifying.py`, `tools/creating/scripts/creating.py`,
  `tools/deleting/scripts/deleting.py`,
  `tests/test_security/test_path_traversal.py`.
- Verification: security/tool-boundary/task partitions passed `76 passed` in
  1.62 seconds; changed modules passed `py_compile` and `git diff --check`.
  Heartbeat regressions confirm the audited read/modify path remains responsive
  while deliberately slowed file work runs; create/delete retained all focused
  security and behavior regressions.
- Remaining risk: file content remains returned in full by the reading tool;
  output-size budgeting is a separate context-safety item.

## Verified fix: system diagnostics and context loading stay off-loop

- Problem: `SystemTool.execute()` could recursively enumerate the workspace,
  inspect processes, or query disk synchronously. `ContextManager.load_context()`
  synchronously discovered and read all context files from an async method.
  Either path could starve the live V5 loop.
- Root cause: potentially unbounded local inspection and context-file I/O were
  exposed through async APIs without a worker boundary.
- Fix: both public async methods now delegate their complete synchronous
  implementations to `asyncio.to_thread()`. Existing secret redaction,
  discovery, and context-cache semantics are preserved.
- Files: `tools/system/scripts/system.py`,
  `orchestrators/v5/context_manager.py`,
  `tests/test_security/test_env_redaction.py`,
  `tests/v5/test_v5_repair_compaction.py`.
- Verification: system/context/compaction partitions passed `23 passed` in
  0.76 seconds; changed modules passed `py_compile` and `git diff --check`.
  Heartbeat regressions confirm both diagnostic and context-loading paths remain
  responsive during deliberately slowed work.
- Remaining risk: `SystemTool` audit still has no explicit traversal/output
  budget beyond the underlying filesystem; a later safety slice should bound
  audit depth and result metadata.

## Verified fix: system audit has bounded traversal

- Problem: the `system audit` action materialized every path below the root with
  `Path.rglob("*")`, allowing a large repository or generated tree to consume
  unbounded memory and scan time.
- Root cause: diagnostic inventory had no entry budget, ignored-directory policy,
  or explicit truncation state.
- Fix: audit now walks without following directory symlinks, skips generated
  dependency/cache directories, caps results at a configurable but bounded
  `max_entries` value (default 10,000; hard maximum 100,000), and reports when
  the cap was reached.
- Files: `tools/system/scripts/system.py`,
  `tests/test_security/test_env_redaction.py`.
- Verification: system/context partitions passed `16 passed` in 0.72 seconds;
  `py_compile` and `git diff --check` passed. The new regression verifies both
  bounded output and explicit truncation reporting.
- Remaining risk: the audit is intentionally a count-only diagnostic; it does
  not yet expose per-directory or permission-error telemetry.

## Verified fix: V5 edit quality gates do not block the event loop

- Problem: V5 edit execution synchronously captured file snapshots, ran
  `py_compile`/`node --check` via `subprocess.run`, and restored invalid edits
  from inside the async tool executor. A slow validator could freeze the main
  agent loop for its full timeout.
- Root cause: the post-write quality gate was made fail-closed but its blocking
  validation and rollback operations remained on the event-loop thread.
- Fix: snapshot capture, preflight lint, post-write lint, and rollback now run
  through `asyncio.to_thread()`. The existing fail-closed behavior and rollback
  semantics remain unchanged.
- Files: `orchestrators/v5/tools.py`, `tests/v5/test_v5_tool_gates.py`.
- Verification: V5 tool-gate/direct-loop/PAORR partitions passed `61 passed` in
  4.94 seconds; changed modules passed `py_compile` and `git diff --check`.
  A new regression confirms heartbeats continue during deliberately slowed
  validators while edits still complete and remain quality-gated.
- Remaining risk: validator subprocess cancellation is bounded by the existing
  subprocess timeout; forcibly terminating a validator after coroutine
  cancellation is a separate process-ownership improvement.

## Verified fix: self-evolution deployment failure is truthful

- Problem: in `safe_mode=False`, `SelfEvolutionLayer.evolve()` ignored the
  boolean returned by `_deploy_candidate()`, marked the candidate deployed, and
  returned success even when the write failed. Partial writes were not rolled
  back on that branch.
- Root cause: the unsafe-mode branch had a separate terminal-state path that
  treated an attempted deployment as a completed deployment.
- Fix: unsafe mode now records success only when deployment returns true and
  invokes rollback plus `rollback_performed` on failure, matching the safe-mode
  failure semantics.
- Files: `orchestrators/v5/self_evolution.py`,
  `tests/v5/test_v5_self_evolution.py`.
- Verification: self-evolution and V5 tool-gate partitions passed `20 passed` in
  1.51 seconds; changed modules passed `py_compile` and `git diff --check`.
  The regression proves a failed unsafe deployment returns `success=False`, no
  deployed candidate, and a rollback attempt.
- Remaining risk: deployment still writes multiple targets sequentially; a
  future transaction-hardening slice should make the multi-file write itself
  atomic or guarantee rollback on process termination.

## Verified fix: self-evolution multi-file deployment is staged and reversible

- Problem: candidate deployment wrote target files directly one at a time. A
  failure during the second or later write could leave a mixed-version
  workspace, and a process interruption during a write could leave truncated
  content.
- Root cause: backups existed, but there was no staged commit boundary and the
  async method performed blocking filesystem mutation directly.
- Fix: deployment now validates every target against the evolution root, creates
  backups, writes and `fsync`s per-target temporary files, commits with atomic
  `os.replace`, and restores the transaction on any failure. Deployment and
  rollback filesystem work run through worker threads. Empty candidate entries
  cannot misalign commit targets and staged files.
- Files: `orchestrators/v5/self_evolution.py`,
  `tests/v5/test_v5_self_evolution.py`.
- Verification: self-evolution and evolution-ledger partitions passed
  `27 passed` in 0.32 seconds; `py_compile` and `git diff --check` passed. The
  regression injects a failure on the second atomic replacement and verifies all
  originals are restored, new files are removed, and backup state is cleared.
- Remaining risk: a hard process termination between `os.replace` operations
  still relies on the persisted `.bak` files and a later recovery coordinator;
  in-process failures are fully rolled back.

## Verified fix: self-evolution commits recover after process restart

- Problem: an interrupted self-evolution commit had no durable transaction
  state, so a new Nexus process could not distinguish a complete deployment
  from a partially replaced workspace or clean up staged files safely.
- Root cause: `.bak` files were created as implementation details, without a
  journal describing the target/backup/staged-file set and commit phase.
- Fix: deployment now fsyncs a transaction manifest before replacement, marks
  it `committed` only after all replacements finish, and removes it afterward.
  `SelfEvolutionLayer` startup recovers any `commit_started` journal inside the
  configured root, restores backups, removes newly-created targets and staged
  files, and retains malformed/out-of-root journals for manual diagnosis.
- Files: `orchestrators/v5/self_evolution.py`,
  `tests/v5/test_v5_self_evolution.py`.
- Verification: self-evolution and evolution-ledger partitions passed
  `28 passed`; changed modules passed `py_compile` and `git diff --check`.
  The restart regression constructs an interrupted journal and verifies the
  original file is restored, a new file is removed, and the journal is cleared.

## Verified fix: self-evolution backup files are transaction-owned and cleaned up

- Problem: every successful deployment left `target.bak` files behind. Repeated
  evolution could grow the workspace indefinitely, and overwriting a user-owned
  `.bak` file made cleanup unsafe.
- Root cause: backups used a fixed target suffix and were treated as an
  in-memory rollback detail rather than lifecycle-owned transaction artifacts.
- Fix: existing targets are copied to unique transaction-scoped backup files;
  committed transactions record those paths in the durable journal, remove the
  backups, clear the active rollback map, and then remove the journal. Startup
  recovery cleans committed backup artifacts and restores/cleans uncommitted
  transactions. Cleanup refuses paths outside the configured root.
- Files: `orchestrators/v5/self_evolution.py`,
  `tests/v5/test_v5_self_evolution.py`.
- Verification: the self-evolution partition passed `5 passed`; regressions
  verify successful deployments leave no backup artifacts and committed
  restart recovery removes only the journal-owned backup.
- Remaining risk: a backup-copy failure before the transaction journal is
  published is handled by the surrounding deployment rollback path; broader
  cross-process serialization of simultaneous evolution runs remains separate.

## Verified fix: oversized tool-result archives do not block the live loop

- Problem: when a tool returned more than the transcript budget, the direct
  model/tool loop created directories and wrote the full archive synchronously
  on the event-loop thread.
- Root cause: the compatibility-preserving `_bounded_tool_result()` helper was
  synchronous and the live loop called it directly even though archiving is
  filesystem I/O.
- Fix: added `_bounded_tool_result_async()` as an offloaded boundary and
  switched the live direct loop to await it. The synchronous helper remains for
  existing callers/tests.
- Files: `orchestrators/v5/direct_loop.py`, `tests/test_redesign_loop.py`.
- Verification: direct-loop and V5 model/tool-loop partitions passed `47
  passed`; the new regression slows archive work deliberately and confirms
  heartbeat progress continues while it runs. Changed modules passed
  `py_compile` and `git diff --check`.
- Remaining risk: normal-sized results still take the worker-thread boundary;
  this is deliberate for a uniform path, and persistence methods elsewhere in
  V5 remain under audit.

## Verified fix: direct-loop transcript fsyncs do not block async execution

- Problem: the live direct model/tool loop persisted each assistant tool call
  and tool result by synchronously serializing and fsyncing the complete
  session transcript on the event-loop thread.
- Root cause: `_persist_direct_message()` combined in-memory deduplication with
  its filesystem durability boundary, and the loop only had a synchronous
  callback path.
- Fix: `_persist_direct_message_async()` performs the same in-memory update
  synchronously, then moves the session-bus write to `asyncio.to_thread()`.
  The direct loop prefers this async boundary and retains the legacy callback
  fallback for compatible hosts. A regression also caught and fixed an
  existing deduplication indentation bug that could return before recording a
  new observation.
- Files: `orchestrators/v5/core.py`, `orchestrators/v5/direct_loop.py`,
  `tests/test_redesign_loop.py`.
- Verification: direct-loop and V5 model/tool-loop partitions passed `48
  passed`; regressions deliberately slow both archive and transcript writes
  and confirm heartbeat progress continues. Changed modules passed
  `py_compile` and `git diff --check`.
- Remaining risk: one user-turn write before model execution remains on the
  synchronous compatibility path; concurrent independent turns still share
  the session write lock and need a broader session-bus ownership audit.

## Verified fix: live user/final turn persistence is off-loop

- Problem: the initial user message and final assistant message were still
  serialized and fsynced synchronously inside the async streamed V5 turn.
- Root cause: `_persist_turn_message()` exposed only a synchronous durability
  boundary even after direct tool observations gained an async adapter.
- Fix: added `_persist_turn_message_async()` with the same pattern: update the
  in-memory transcript synchronously, then await the session-bus write in a
  worker thread. The existing synchronous method remains available to legacy
  callers.
- Files: `orchestrators/v5/core.py`, `tests/test_redesign_loop.py`.
- Verification: direct-loop and V5 model/tool-loop partitions passed `49
  passed`; the new regression deliberately slows the session write and
  confirms heartbeat progress continues. Changed modules passed `py_compile`
  and `git diff --check`.
- Remaining risk: the legacy synchronous API is still used by non-streaming
  paths, and cross-session write ownership remains a separate audit item.

## Verified fix: session-bus replacement is cross-process serialized

- Problem: `_session_write_lock` only protected threads within one Nexus
  process. Separate GUI, gateway, CLI, or worker processes could replace the
  same session file concurrently; atomic replacement prevented torn JSON but
  provided no filesystem-level ownership boundary.
- Root cause: session persistence had an in-process `threading.Lock` but no
  interprocess mutex, unlike the existing work-item and verifier stores.
- Fix: `_write_session_bus()` now acquires a retained sidecar SQLite mutex and
  uses `BEGIN IMMEDIATE` around the temporary-file/fsync/replace sequence.
  The async adapters use the same protected writer, and voice-mode persistence
  now uses the async boundary too.
- Files: `orchestrators/v5/core.py`, `tests/test_redesign_loop.py`.
- Verification: redesign-loop, direct-loop, V5 model/tool-loop, and continuity
  partitions passed `60 passed`; the new concurrency regression holds the
  mutex from one loop instance and proves a second instance waits before
  replacing the session. Changed modules passed `py_compile` and
  `git diff --check`.
- Remaining risk: writers serialize but still use each process's in-memory
  transcript snapshot, so semantic last-writer-wins merging across truly
  concurrent independent turns remains a separate design decision.

## Verified fix: V5 session identifiers cannot traverse filesystem paths

- Problem: `NexusLoopV5` copied raw session identifiers into
  `logs/sessions/<session>.json`; a separator or `..` segment could redirect
  transcript persistence outside the intended session directory.
- Root cause: the canonical `nexus.runtime.safe_session_id()` helper existed
  but V5 construction did not apply it before creating runtime and persistence
  paths.
- Fix: V5 now normalizes the session identifier at construction and uses the
  normalized value consistently for runtime state, recovery, locks, and
  transcript files.
- Files: `orchestrators/v5/core.py`, `tests/test_redesign_loop.py`.
- Verification: redesign-loop and V5 direct-loop partitions passed `51
  passed`; the regression attempts `../../outside.json` and confirms the
  transcript remains under the configured session directory. Changed modules
  passed `py_compile` and `git diff --check`.
- Remaining risk: other non-V5 adapters must continue using their own shared
  session-path helpers; a repository-wide raw session-id path audit remains.

## Verified fix: non-V5 session archives and gateway paths reject traversal

- Problem: `context.NexusFilePersistence` and
  `GatewaySessionManager` interpolated caller-provided session IDs directly
  into archive, checkpoint, lookup, delete, and path-reporting filenames.
- Root cause: these older adapters predated the shared runtime session-ID
  normalization and trusted IDs that are normally generated by gateways.
- Fix: context archives normalize session IDs and checkpoint components before
  path construction and store normalized identifiers in payload metadata;
  gateway lookup/disconnect/path APIs normalize IDs as well. V5 `load_memory()`
  now applies the same normalization when changing sessions after
  construction and updates runtime state consistently.
- Files: `context/persistence.py`, `gateway/session_bus_integration.py`,
  `orchestrators/v5/core.py`, `tests/test_session_path_security.py`,
  `tests/test_redesign_loop.py`.
- Verification: path-security, continuity, gateway-runtime, redesign-loop, and
  V5 direct-loop partitions passed `70 passed`; traversal regressions confirm
  archive and gateway paths remain inside their configured roots. Changed
  modules passed `py_compile` and `git diff --check`.
- Remaining risk: raw session-derived filenames remain in less frequently used
  integrations and require continued repository-wide review.

## Verified fix: shared memory and active-session paths are normalized

- Problem: `MemoryManager` accepted raw session IDs, `utils.session_bus` could
  reuse one cached active-session path for different project roots, and
  `MemoryForge` accepted path separators in memory names.
- Root cause: older integrations relied on generated identifiers and used
  process-global path state without applying the canonical runtime safety
  helper.
- Fix: memory sessions and forge names are bounded to safe single components;
  active-session state now caches paths per normalized project root and
  normalizes IDs on read/write. This prevents both traversal and cross-project
  active-session contamination.
- Files: `memory/__init__.py`, `utils/session_bus.py`,
  `evolution/memory_forge/scripts/forge.py`,
  `tests/test_session_path_security.py`.
- Verification: session-security, memory-forge, continuity, gateway-runtime,
  redesign-loop, and V5 direct-loop partitions passed `75 passed`; traversal,
  project-root isolation, and forge-name regressions all pass.
- Remaining risk: the repository still contains non-path session metadata
  consumers that may need semantic normalization, but confirmed filesystem
  boundaries in this slice are contained.

## Verified fix: session identity stays consistent across V5 metadata layers

- Problem: `V5Orchestrator` retained a raw session ID while its V5 loop used a
  normalized one, and run-context/continuity/programmatic-verification paths
  used a different sanitizer. This could split one logical session across
  event metadata, recovery lookup, and persisted directories.
- Root cause: multiple generations of session helpers evolved independently;
  path safety was added without a single metadata normalization boundary.
- Fix: V5 orchestrator, continuity inspection, run-context paths/recovery, and
  programmatic verification now use the shared `safe_session_id()` contract.
  Run IDs continue using their separate bounded identifier sanitizer.
- Files: `orchestrators/v5/orchestrator.py`, `memory/continuity.py`,
  `nexus/run_context.py`, `orchestrators/v5/programmatic_verify.py`,
  affected tests.
- Verification: continuity, session-security, run-evidence, and programmatic
  verification partitions passed `35 passed`; the existing `team/alpha`
  recovery regression now resolves the same normalized session directory.
- Remaining risk: legacy event payloads already written with older session
  naming may require migration or alias lookup if backward compatibility with
  those artifacts is required.

## Verified fix: continuity reads legacy session directories after normalization

- Problem: unifying new session identity on `alpha` could make existing
  `team_alpha` run-context directories invisible to restart continuity and
  orphan recovery.
- Root cause: the continuity reader had its own legacy `_safe_component`
  directory rule and normalized the requested ID before it could derive the
  old alias.
- Fix: continuity now retains the requested ID for lookup, checks both the
  canonical and legacy directory aliases, and matches checkpoint metadata
  through the same alias set. New run-context writes remain canonical.
- Files: `nexus/run_context.py`, `memory/continuity.py`,
  `tests/test_continuity_persistence.py`.
- Verification: continuity, run-context recovery, session-security, and
  programmatic-verification partitions passed `28 passed`; a regression reads
  a pre-existing `team_alpha` context through the `team/alpha` request.
- Remaining risk: old event streams may use legacy session labels in payloads;
  those require presentation-layer aliasing if clients query by the new ID.

## Verified fix: observer and voice entry points use canonical session identity

- Problem: the standalone event observer used a separate underscore-based
  sanitizer, while the server voice-start endpoint forwarded a raw session ID
  into process-launch metadata. Their identities could diverge from V5 and
  server session paths.
- Root cause: these entry points bypassed the shared runtime normalization
  boundary even though their generated paths/metadata were session-scoped.
- Fix: observer path construction and voice-start session handling now use
  `safe_session_id()`.
- Files: `nexus/observer.py`, `server/__init__.py`, `tests/test_observer.py`.
- Verification: observer, voice, session-security, and continuity partitions
  passed `29 passed`; traversal observer-path coverage passes.
- Remaining risk: historical event files under legacy names need alias lookup
  if operators observe them through the new canonical session ID.

## Verified fix: GUI/server event readers preserve legacy session streams

- Problem: event writers now use canonical session filenames, but GUI and
  server readers opened only that filename. Older `team_alpha.jsonl` streams
  became invisible when queried as `team/alpha`.
- Root cause: read paths had no alias compatibility even though continuity and
  run-context readers had already gained it.
- Fix: GUI/server event readers aggregate canonical and legacy alias files,
  sort through the existing safe sequence normalizer, and retain canonical
  paths for all new writes and compaction.
- Files: `gui/api.py`, `server/__init__.py`,
  `tests/gui/scripts/test_work_event_updates.py`,
  `tests/test_server/test_work_items_api.py`.
- Verification: GUI work-event, server work-item/event, and observer partitions
  passed `48 passed`; explicit legacy `team_alpha` replay regressions pass.
- Remaining risk: if canonical and legacy files contain overlapping sequence
  ranges, presentation ordering is best-effort by sequence/timestamp and a
  future migration may be needed for exact historical ordering.

## Verified fix: Hive plan review parses explicit verdicts

- Problem: active Hive plan gating rejected a plan whenever reviewer output
  contained the substring `BLOCK`, including benign text such as “no blocking
  issues”.
- Root cause: the reviewer parser used an unanchored substring test instead of
  the protocol it explicitly requested (`VERDICT: APPROVE` or
  `VERDICT: BLOCK`).
- Fix: gating now recognizes only an explicit verdict line with a word-boundary
  `BLOCK` token; concerns remain informational unless the reviewer emits that
  protocol verdict.
- Files: `orchestrators/v5/active_loop.py`,
  `tests/v5/test_v5_active_loop.py`.
- Verification: active-loop partition passed `20 passed`; the regression
  confirms narrative “blocking” text does not veto a safe plan while explicit
  `VERDICT: BLOCK` behavior remains covered.
- Remaining risk: malformed reviewer output currently defaults to approval in
  Hive mode for low-risk plans; high-risk plans now fail closed when the
  reviewer emits no explicit verdict.

## Verified fix: high-risk Hive plans fail closed on missing reviewer verdicts

- Problem: after explicit verdict parsing was added, malformed or absent
  reviewer output still left `approved=True`, allowing a high-risk plan to
  proceed without a safety decision.
- Root cause: parser correctness and safety policy were separate; only an
  explicit `BLOCK` changed the initial approval state.
- Fix: only the REVIEWER agent can veto a plan, and a high-risk plan is
  rejected when that agent emits no explicit `VERDICT: APPROVE` or
  `VERDICT: BLOCK`. Low-risk plans retain compatibility with non-verdict
  informational reviews.
- Files: `orchestrators/v5/active_loop.py`,
  `tests/v5/test_v5_active_loop.py`.
- Verification: active-loop partition passed `21 passed`; explicit block,
  benign narrative, approval, and missing-verdict cases are covered.
- Remaining risk: Hive agent identity is currently persona-string based; a
  future typed review-envelope contract would make role attribution stronger.

## Verified fix: Hive plan-gating exceptions fail closed for high-risk work

- Problem: an unexpected exception in `_gate_plan()` returned the original
  plan, allowing high-risk tools to execute without a successful safety review.
- Root cause: the outer defensive catch was designed for loop availability and
  degraded all failures to pass-through, conflating safe-plan availability
  with authorization to perform risky work.
- Fix: the exception path now re-runs deterministic risk classification and
  blocks high-risk plans; low-risk plans still pass through when review is
  unavailable.
- Files: `orchestrators/v5/active_loop.py`,
  `tests/v5/test_v5_active_loop.py`.
- Verification: active-loop partition passed `22 passed`; explicit review
  failures, missing verdicts, benign narrative, and normal approvals are
  covered.
- Remaining risk: deterministic risk classification remains tool-name based;
  newly introduced high-impact tools must be added to the risk taxonomy or
  expose accurate `ToolEntry.is_read_only(params)` metadata.

## Verified fix: Hive plan gating recognizes mutating tool metadata and actions

- Problem: the high-risk plan gate covered shell/delete/edit aliases only
  through a fixed list, so a newly registered mutating tool could be treated
  as safe and bypass the Hive fail-closed path. `creating` was also absent,
  despite being a file-writing tool already available to Nexus.
- Root cause: plan gating had no connection to the canonical tool registry's
  `is_read_only(params)` contract and did not inspect action-bearing tools such
  as memory/task operations.
- Fix: the deterministic classifier now covers common mutation aliases,
  mutation actions, command-bearing steps, and registered tools whose metadata
  declares them non-read-only. Metadata failures are treated conservatively as
  mutating rather than silently downgrading the step.
- Files: `orchestrators/v5/active_loop.py`,
  `tests/v5/test_v5_active_loop.py`.
- Verification: focused active-loop partition passed `24 passed`; regressions
  cover `creating`, action-based deletion, and an unlisted registry tool with
  `is_read_only() == False`.
- Remaining risk: tools with inaccurate metadata or destructive behavior hidden
  in free-form parameters still require tool-specific risk scoring before
  execution; the plan gate is a preflight defense, not the final permission
  boundary.

## Verified fix: active Hive plan review is connected to live planning

- Problem: `V5ActiveLoop._gate_plan()` had unit coverage but no production
  caller. The live planner persisted generated steps and injected them into
  context without applying Hive review, so the safety gate could not block
  execution.
- Root cause: the V5 planning mixin and active-loop mixin were implemented as
  parallel features, but the planning boundary never invoked the active-loop
  contract.
- Fix: `_plan_with_tool()` now invokes `_gate_plan()` when the existing
  `NEXUS_HIVE` + `NEXUS_V5_ACTIVE_MODE` flags enable active mode. A rejected
  plan is returned as empty before persistence or plan-context exposure;
  ordinary planning behavior remains unchanged when active mode is disabled.
- Files: `orchestrators/v5/planning.py`,
  `tests/v5/test_v5_planning_gate.py`.
- Verification: active-loop plus planning/registry/parallel integration
  partitions passed `96 passed` in total (`24` active-loop and `72` related
  integration tests across the two verification runs).
- Remaining risk: Hive self-repair remains a separate optional helper; the live
  direct loop already owns bounded failure repair, so enabling both engines
  requires an explicit deduplication/side-effect policy.

## Verified fix: live direct loop records stall history and surfaces one Hive replan

- Problem: the active task ledger and stall detector were implemented but had
  no production writer or caller. Repeated tool failures/successes therefore
  could not trigger the documented Hive replan path.
- Root cause: direct-loop action records were persisted in `actions` only; the
  active-loop ledger remained empty, and its description field did not fall
  back to the action's tool/name shape.
- Fix: the direct loop initializes the per-turn ledger, records every tool
  action, and invokes the Hive stall-replan helper once when active mode is on.
  A returned proposal is bounded and inserted as model-visible guidance; it is
  never executed blindly. Ledger entries now use `description`, `name`, or
  `tool` identity so repeated tool actions are detectable.
- Files: `orchestrators/v5/direct_loop.py`, `orchestrators/v5/active_loop.py`,
  `tests/v5/test_v5_direct_model_tool_loop.py`.
- Verification: direct-loop, active-loop, and planning partitions passed
  `73 passed`; the live regression proves the replan callback is reached only
  after three recorded entries and that the proposal appears in the transcript.
- Remaining risk: the direct loop's native bounded repair remains the authority
  for failed tool execution; Hive self-repair is still not invoked as a second
  competing repair engine, avoiding duplicate retries and side effects.

## Verified fix: Hive recovery proposals are normalized and reviewed

- Problem: `REPAIR_PLAN` and `NEW_PLAN` JSON from Hive agents was returned as
  arbitrary lists. Malformed entries, unknown tools, non-object parameters, or
  high-risk recovery steps could therefore reach the live-loop guidance path
  without the canonical plan contract or safety review.
- Root cause: recovery parsing was implemented separately from initial plan
  parsing and bypassed both registry metadata and `_gate_plan()`.
- Fix: both recovery paths now use a shared normalizer that requires bounded
  descriptions, canonicalizes tool/params fields, drops unknown registered
  tools, and then routes the result through the plan gate. Rejected or invalid
  proposals become unavailable rather than being suggested to the model.
- Files: `orchestrators/v5/active_loop.py`,
  `tests/v5/test_v5_active_loop.py`.
- Verification: active-loop, direct-loop, and planning partitions passed
  `75 passed`; regressions cover malformed entries, unknown tools, canonical
  params, and explicit safety-gate rejection.
- Remaining risk: Hive self-repair remains advisory and is not a second tool
  executor; the direct loop must still validate every model-selected call at
  its normal permission and risk boundaries.

## Verified fix: Hive self-repair is a bounded escalation after native repair

- Problem: the direct loop exhausted its native repair budget and returned a
  failure without ever using the already-reviewed Hive self-repair helper.
  Conversely, invoking Hive alongside every retry would duplicate side effects
  and inflate model/tool work.
- Root cause: the two repair systems had no ownership boundary or escalation
  contract.
- Fix: after native repair exhaustion, active mode may request exactly one
  reviewed Hive repair proposal and grant one additional model decision. The
  proposal is advisory, the failed batch still stops immediately, and the
  normal permission/risk/tool validation path remains authoritative. If Hive
  fails or returns no proposal, the original exhausted-repair failure is
  preserved.
- Files: `orchestrators/v5/direct_loop.py`,
  `tests/v5/test_v5_direct_model_tool_loop.py`.
- Verification: direct-loop, active-loop, and planning partitions passed
  `76 passed`; regressions cover successful one-shot escalation and the
  existing no-escalation repair budget behavior.
- Remaining risk: the extra model decision is intentionally bounded to one
  Hive escalation per turn; repeated failures remain terminal and durable.

## Verified fix: checkpoint resume restores bounded turn history

- Problem: checkpoint files stored only `turn_history_len`, so a restarted
  Nexus instance could restore plan/actions/memory while losing the prior-turn
  context needed for continuity and progress evaluation.
- Root cause: the checkpoint serializer treated history as a count rather than
  durable state, and the resume path had no reconstruction for turn records.
- Fix: checkpoints now persist a bounded, secret-redacted snapshot of recent
  turn identity, input, metadata, timestamps, and terminal state. Resume
  rehydrates those snapshots as inert turn records without importing the core
  module or restoring transient resources.
- Files: `orchestrators/v5/checkpoint.py`,
  `tests/v5/test_v5_checkpoint_resume_loop.py`.
- Verification: checkpoint, run-context, continuity, and run-evidence
  partitions passed `32 passed`; the restart regression verifies restored
  turn identity, user input, metadata, and terminal state.
- Remaining risk: restored timestamps are serialized strings and transient
  provider/tool handles are intentionally not reconstructed; a resumed turn
  must reacquire those resources through normal runtime initialization.

## Verified fix: run-context heartbeat and recovery transitions are ownership-safe

- Problem: a delayed/stale `RunContext` object could heartbeat after another
  process had completed the run, reopening its lease and potentially causing
  recovery or UI state to regress. Orphan recovery also scanned first and
  finished later without rechecking the durable record.
- Root cause: run-context JSON writes were atomic but transitions were not
  serialized or compared against the current durable status/owner.
- Fix: heartbeat and terminal finish now use a per-run SQLite sidecar mutex,
  re-read the durable record under lock, reject terminal or foreign-owner
  transitions, and update from the current payload. Orphan recovery honors a
  rejected finish and emits no stale recovery event.
- Files: `nexus/run_context.py`, `tests/test_run_context_recovery.py`.
- Verification: run-context, checkpoint, and continuity partitions passed
  `23 passed`; regressions cover stale heartbeat after completion and stale
  owner renewal/finish attempts.
- Remaining risk: event-log append and work-item projection remain separate
  durable operations; their idempotency guards must continue to reject late
  events after a run transition.

## Verified fix: public WorkItem persistence shares the projection mutex

- Problem: event projection and checklist reconciliation serialized their
  load/transition/save cycle with a SQLite sidecar, but the public
  `persist_work_item()` API bypassed that mutex and used only an in-process
  lock. A planner/task worker could therefore overwrite a concurrently
  projected terminal state.
- Root cause: the atomic JSON writer and the interprocess transaction boundary
  were fused into one function, forcing locked callers to bypass the public
  API and leaving independent callers unprotected.
- Fix: split `_persist_work_item_unlocked()` from the public writer. The public
  API now acquires the same interprocess mutex, while callers already inside a
  projection transaction use the unlocked primitive to avoid nested SQLite
  locks.
- Files: `nexus/work_items.py`.
- Verification: WorkItem, planning, run-context, server work-item, and GUI
  event partitions passed `57 passed`.
- Remaining risk: append-only event-log writes and WorkItem projection are
  still two durable operations; replay remains the recovery path for a crash
  between them, and must remain idempotent.

## Verified fix: replay isolates individual WorkItem projection failures

- Problem: `replay_work_item_event_log()` stopped at the first projection
  exception. One corrupt WorkItem or transient lock/I/O failure could prevent
  later terminal events in the same durable log from being recovered.
- Root cause: replay treated projection as an all-or-nothing loop even though
  each event is independently idempotent and the log is the retry source.
- Fix: replay now catches and logs failures per event, continues projecting
  subsequent records, and leaves the failed record in the append-only log for
  a later retry.
- Files: `nexus/work_items.py`, `tests/v5/test_work_items.py`.
- Verification: WorkItem, planning, run-context, server, and GUI event
  partitions passed `58 passed`; the regression proves a later `run.started`
  event still projects after an earlier projection exception.
- Remaining risk: the append and projection operations remain intentionally
  separate; startup/replay is the durable repair mechanism for a crash window.

## Verified fix: WorkItem projection failures are durable and backoff-aware

- Problem: append-time projection failures were swallowed at debug level, and
  replay retried every failed event on every request without a durable pending
  status. Operators could not distinguish a recoverable projection delay from
  a permanently malformed event.
- Root cause: the append-only event log was treated as the only recovery
  state; projection attempt history and next retry time were not persisted.
- Fix: server and GUI append paths now record failed projections in a per-log
  atomic sidecar ledger. Replay retries due entries with bounded exponential
  backoff (1s, 5s, 30s, then 5m), clears the entry after successful projection,
  and exposes pending failures from the WorkItem API. Error text is bounded
  to avoid turning malformed tool/event output into unbounded durable state.
- Files: `nexus/work_items.py`, `server/__init__.py`, `gui/api.py`,
  `tests/v5/test_work_items.py`.
- Verification: WorkItem persistence/replay partition passed `6 passed`;
  compilation passed for all three runtime modules. Coverage proves later
  events still recover, failure attempts persist, backoff metadata is present,
  and successful projection cleanup removes the pending record.
- Regression verification: the broader event/recovery partition reached
  `104 passed, 1 failed`; the lone failure was the existing timing-sensitive
  `tests/test_queue_store.py::test_retry_backoff_is_respected`. Its isolated
  rerun plus the affected API/GUI partitions passed `57 passed`.
- Remaining risk: replay is request/startup driven rather than a separate
  background worker; if no WorkItem API is used, a due failure waits for the
  next recovery trigger. The append log remains the source of truth.

## Verified fix: GUI event reads trigger WorkItem projection recovery

- Problem: the GUI append path recorded projection failures, but the GUI
  event-read endpoint never invoked WorkItem replay. A GUI-only process could
  therefore leave a recoverable projection pending until a separate server
  process happened to read the same session.
- Fix: GUI `/api/work-events` now normalizes the session, replays due durable
  WorkItem events before serving the timeline, and returns the pending failure
  ledger for diagnostics.
- Files: `gui/api.py`.
- Verification: GUI event, server WorkItem API, and WorkItem persistence
  partitions passed `50 passed` with one existing FastAPI/httpx deprecation
  warning; GUI module compilation passed.
- Remaining risk: replay remains demand-driven and does not create an
  always-on background repair thread.

## Verified fix: SkillExecutor no longer reports provider failures as success

- Problem: the LLM-backed `SkillExecutor` caught provider/LLM exceptions and
  returned `STATUS_OK` with fallback prompt text. The tool registry and agent
  loop could therefore record a failed skill invocation as successful and
  continue with unverified work.
- Root cause: the fallback instruction behavior from the prompt-injection
  adapter was copied into the full execution adapter, where an exception is a
  terminal execution result rather than a valid instruction response.
- Fix: failed LLM skill execution now returns the canonical `STATUS_ERROR`
  envelope, bounded classified error information, and explicit
  `execution_failed` metadata. The no-LLM compatibility path remains an
  intentional successful instruction injection.
- Files: `tools/nexus_tools/skill_adapter.py`,
  `tests/test_redesign_skills.py`.
- Verification: skill, tool-result, registry, and V5 tool-gate partitions
  passed `71 passed`; the module compiled successfully. The regression proves
  provider failure is not represented as success and preserves its error type
  and message.
- Remaining risk: skill prompt injection and full LLM-backed execution remain
  separate adapters; future changes must preserve their distinct success
  contracts.

## Silent-success boundary scan: adjacent tool/provider paths

- Scope: `tools/`, `tools/nexus_tools/`, `orchestrators/v5/`, `providers/`,
  `gateway/`, and `mcp/`, with emphasis on exceptions returning success,
  `STATUS_OK`, or fallback output.
- Finding: the only reproducible core execution defect in this scan was the
  `SkillExecutor` provider-failure path documented above. Registry execution,
  result normalization, MCP adaptation, and V5 tool-event handling preserve
  error/timeout/blocked statuses. Remaining broad `pass` handlers are
  optional cleanup, typing indicators, lifecycle bookkeeping, or compatibility
  fallbacks and were not changed without a concrete user-visible failure.
- Next work: continue the async-boundary and provider/MCP lifecycle audit,
  then verify remaining P1/P2 backlog claims against runtime behavior.

## Verified fix: server workspace file APIs offload blocking I/O

- Problem: async FastAPI handlers for workspace write/create/rename/delete/
  move/zip/unzip/list performed filesystem, recursive traversal, compression,
  and extraction work inline on the event loop. Large workspace operations
  could delay chat streaming, cancellation, health checks, and other clients.
- Root cause: endpoint validation and the blocking mutation/read operation were
  implemented in one async function without an explicit worker boundary.
- Fix: extracted synchronous operation helpers and dispatches the actual I/O
  through `asyncio.to_thread`; request parsing, path containment, archive
  safety validation, and verifier invalidation remain in the endpoint contract.
  Existing HTTP error semantics are preserved, including unsafe ZIP rejection.
- Files: `server/__init__.py`,
  `tests/test_server/scripts/test_file_async_boundary.py`.
- Verification: server module compilation passed; async-boundary, smoke, and
  WorkItem API tests passed `19 passed, 5 skipped`. The broader server/chat
  file partition passed `32 passed, 5 skipped` before the explicit boundary
  regression was added.
- Remaining risk: lightweight path validation still runs on the event loop;
  recursive checkpoint/snapshot endpoints require a separate async-boundary
  audit.

## Async-boundary audit: checkpoint paths verified

- Evidence: automatic run snapshots execute `_create_workspace_checkpoint`
  inside a dedicated `checkpoint-snapshot` daemon thread; restore uses
  `await asyncio.to_thread(_restore_workspace_checkpoint, ...)`; list/delete
  are synchronous FastAPI handlers and therefore run in the server threadpool.
- Decision: no checkpoint patch was needed in this wave. Changing the already
  isolated path would add risk without improving the runtime contract.
- Remaining risk: checkpoint snapshot failures are logged and the guard moves
  to `done`, so a later automatic retry policy may be useful for transient
  filesystem failures.

## Verified fix: GUI upload persistence offloads blocking writes

- Problem: the async GUI upload endpoint read the underlying upload file and
  wrote chunks directly with synchronous file I/O. Large uploads could stall
  GUI streaming and other async requests.
- Fix: upload chunks are read through Starlette's async interface, bounded by
  the existing 10 MiB limit, then atomically persisted through
  `asyncio.to_thread`. The existing filename containment and size checks remain
  unchanged.
- Files: `gui/api.py`, `tests/gui/scripts/test_upload_async_boundary.py`.
- Verification: GUI upload-boundary, work-event, and command-execution tests
  passed `41 passed` with one existing FastAPI/httpx deprecation warning;
  GUI compilation passed.
- Remaining risk: the GUI website-import endpoint still performs blocking
  urllib fetch/parsing inline and is the next async network-boundary candidate.

## Verified fix: GUI website import offloads network, parsing, and persistence

- Problem: `/api/sources/website` performed DNS validation, urllib network I/O,
  bounded response reads, HTML parsing, and file writes inline in an async
  handler. A slow public site could stall GUI chat/event streaming.
- Fix: URL validation, fetch/extraction, and bounded atomic text persistence
  now run through `asyncio.to_thread`. Existing public-URL/SSRF checks,
  redirect rejection, 12-second fetch timeout, and 10 MiB response limit are
  preserved.
- Files: `gui/api.py`,
  `tests/gui/scripts/test_website_import_async_boundary.py`.
- Verification: website-boundary, upload-boundary, and release-security tests
  passed `9 passed, 1 skipped`; the GUI work-event regression file passed
  independently with `36 passed`; GUI compilation passed. A combined command
  also encountered three unrelated `401` auth-state failures in that existing
  file, which did not reproduce in the isolated rerun.
- Remaining risk: synchronous source-library update and RAG indexing after the
  file write remain separate follow-up boundaries.

## Verified fix: GUI source ingestion serializes metadata and RAG work

- Problem: after the network/file boundary was fixed, upload and website
  handlers still performed source-library JSON mutation and RAG indexing inline.
  Moving those operations into workers without coordination could also allow
  concurrent ingestion requests to lose metadata updates or observe a partial
  JSON file.
- Fix: source-library mutation now uses a re-entrant process-local lock and
  atomic temporary-file replacement. Upload and website ingestion dispatch
  metadata upsert and RAG indexing through `asyncio.to_thread`, preserving
  ordering: file write → source metadata → index attempt.
- Files: `gui/api.py`, `tests/gui/scripts/test_source_ingestion_boundaries.py`.
- Verification: GUI source-ingestion, website-boundary, upload-boundary, and
  work-event partitions passed `40 passed` with one existing FastAPI/httpx
  deprecation warning; GUI compilation passed.
- Remaining risk: reads from legacy/external callers remain synchronous when
  invoked directly, although API mutation paths now use the cross-process
  mutex and async worker boundary.

## Verified fix: source-library mutations are cross-process safe

- Problem: the GUI source-library lock serialized threads within one worker but
  did not protect the load–modify–save transaction across multiple GUI worker
  processes. Concurrent upsert/update/delete requests could lose each other's
  changes.
- Fix: source-library mutation transactions now acquire the existing SQLite
  interprocess mutex in addition to the local re-entrant lock. Async patch and
  delete endpoints also dispatch their mutations through `asyncio.to_thread`.
- Files: `gui/api.py`, `tests/gui/scripts/test_source_ingestion_boundaries.py`.
- Verification: source-ingestion, website, upload, and work-event partitions
  passed `40 passed`; GUI compilation passed. The regression asserts all
  mutation handlers retain the worker boundary and the cross-process lock.
- Remaining risk: this protects the shared JSON transaction, but RAG index
  updates remain an external side effect and may be at-least-once under a
  worker crash after metadata persistence.

## Verified fix: RAG surgical and batch indexing is serialized

- Problem: `NexusAtlasRAG` is a process-local singleton shared by GUI tasks,
  but `store_document()` and `index_workspace()` mutated `_doc_store`, vector
  state, and `_rag_index.json` without using the existing lock. Concurrent
  ingestion could lose one document or leave the persisted index inconsistent.
- Root cause: the lock only guarded stale-entry cleanup; mutation methods were
  added later without a transaction boundary.
- Fix: use a re-entrant lock, wrap individual document writes, and serialize
  each complete workspace/surgical indexing transaction. The unlocked helpers
  keep existing batch behavior and avoid self-deadlock.
- Files: `rag/engine.py`, `tests/test_rag_concurrency.py`.
- Verification: RAG concurrency and GUI ingestion-boundary tests passed
  `5 passed`; RAG and GUI modules compiled successfully. The regression runs
  two concurrent surgical indexes and verifies both in-memory and persisted
  documents survive.
- Remaining risk: retrieval reads are not yet wrapped in the same lock, and
  cross-process RAG writers still need a file/SQLite transaction if multiple
  processes share one RAG vault.

## Verified fix: RAG retrieval shares the mutation lock

- Problem: even after indexing was serialized, `retrieve_as_text()` and
  `hybrid_search()` could read `_doc_store`, inverted indexes, or vector state
  while another ingestion thread mutated them.
- Fix: both retrieval paths now execute under the same re-entrant RAG lock;
  unlocked helpers preserve the existing lazy-index behavior without
  self-deadlock.
- Files: `rag/engine.py`, `tests/test_rag_concurrency.py`.
- Verification: concurrent RAG indexing/retrieval and GUI ingestion-boundary
  tests passed `4 passed`; RAG compilation passed. The regression exercises
  simultaneous surgical indexing and retrieval and confirms stable evidence
  remains queryable.
- Remaining risk: the RAG lock is process-local; independent processes still
  require a shared-vault merge/transaction protocol to avoid last-writer
  replacement.

## Verified fix: RAG shared-vault writes use a durable transaction mutex

- Problem: the process-local RAG lock prevented thread races but did not stop
  separate Nexus/GUI worker processes from loading the same JSON index,
  applying different updates, and overwriting one another.
- Root cause: RAG persistence had no cross-process transaction boundary, and
  the lazy curated-index path called the public per-document method repeatedly,
  which could reload an incomplete transaction between documents.
- Fix: RAG mutation transactions now acquire a SQLite sidecar mutex, reload the
  latest persisted store before applying changes, and use unlocked helpers for
  the whole batch. Index writes are also atomic (temporary file, flush/fsync,
  replace), and curated lazy indexing now commits as one transaction.
- Files: `rag/engine.py`, `tests/test_rag_concurrency.py`.
- Verification: RAG concurrency, shared-vault mutex, and GUI ingestion-boundary
  tests passed `5 passed`; RAG compilation passed. The new regression confirms
  concurrent transactions cannot overlap.
- Remaining risk: an already-running process refreshes its vector cache when it
  enters a shared-vault mutation transaction; passive readers do not poll for
  external changes until their next mutation or restart.

## Verified fix: persisted RAG documents rehydrate the turbo vector cache

- Problem: `_rag_index.json` survived restart, but the optional SimHash vector
  engine was initialized empty. Hybrid/turbo search therefore silently lost
  semantic results after a process restart even though BM25 data was present.
- Fix: initialization and persisted-index reload now rebuild the process-local
  vector cache from every stored document. The existing mutation lock keeps
  cache rebuilds consistent with BM25 state.
- Files: `rag/engine.py`, `tests/test_rag_concurrency.py`.
- Verification: RAG concurrency/cache tests passed `4 passed`; RAG compilation
  passed. The regression writes a document, resets the singleton, and verifies
  its vector entry is restored.
- Remaining risk: passive readers do not detect another process's update until
  a refresh boundary; a future vault-generation marker could make external
  read refreshes explicit without rebuilding on every query.

## Verified fix: RAG rebuild and turbo search honor lifecycle locks

- Problem: `rebuild_index()` cleared in-memory state and then called the public
  indexing method, which reloaded the old persisted index and could reintroduce
  stale documents. `turbo_search()` and stale cleanup also had unprotected
  access around mutable vector/index state.
- Fix: rebuild now clears and scans within one local/interprocess transaction;
  cleanup reloads and saves within the same transaction; turbo search shares
  the RAG read lock.
- Files: `rag/engine.py`, `tests/test_rag_concurrency.py`.
- Verification: RAG concurrency, cache rehydration, rebuild, and mutex tests
  passed `5 passed`; RAG compilation passed. The rebuild regression confirms a
  persisted missing document is not resurrected.
- Remaining risk: the full RAG API still has legacy synchronous callers; they
  are safe for state consistency but can consume request threads when invoked
  directly from async surfaces.

## Verified fix: ShortcutsTool resolves symlinks for workspace containment

- Problem: lexical `commonpath` validation accepted an in-workspace symlink
  pointing outside the configured workspace. The recursive tree operation also
  followed child directory symlinks, allowing external content exposure or
  traversal cycles.
- Root cause: containment checked the requested string path but not its
  filesystem-resolved target; tree recursion treated links as ordinary
  directories.
- Fix: target validation now compares the realpath against the real workspace
  root, `find` filters resolved matches, and tree output marks but does not
  recurse into child symlinks.
- Files: `tools/shortcuts/scripts/shortcuts.py`,
  `tests/test_security/test_path_traversal.py`.
- Verification: shortcut security tests passed `4 passed, 2 skipped` (Windows
  symlink privileges account for the skips); the combined path, SSRF, and
  environment-redaction security set passed `36 passed, 2 skipped`.
- Remaining risk: symlink creation is platform/permission dependent, so the
  skipped tests should also run in a privileged Windows security job.

## Verified fix: planning and task mutations use durable plan transactions

- Problem: PlanningTool and TaskTool performed read/modify/write operations on
  the shared `todo.md` without a transaction lock. Concurrent agents could
  allocate the same task number or overwrite a sibling's plan update.
- Root cause: async execution was offloaded to worker threads, but the worker
  boundary did not provide synchronization across threads or processes.
- Fix: both tools now share a per-plan re-entrant process lock plus a SQLite
  sidecar interprocess mutex. Plan writes use an atomic temporary-file flush,
  fsync, and replace sequence; task mutations use the same transaction helper.
- Files: `tools/planning/scripts/planning.py`, `tools/task/scripts/task.py`,
  `tests/test_task_tool.py`.
- Verification: planning/work-item and task-tool tests passed `13 passed`,
  including concurrent task creation preserving both updates; both modified
  modules compiled successfully.
- Remaining risk: legacy direct callers of `_write_plan()` bypass the
  transaction helper, although their writes are now atomic; those callers need
  migration if they become concurrent mutators.

## Verified fix: server and GUI plan adapters share the plan transaction

- Problem: standalone server and GUI each had a duplicate
  `write_workspace_todo_plan()` implementation that atomically replaced
  `todo.md` but bypassed PlanningTool/TaskTool locking. API workflow updates
  could therefore race with agent tool mutations.
- Fix: both adapters now use the shared plan transaction mutex and fsync their
  temporary file before replacement; plan clearing uses the same lock.
- Files: `server/__init__.py`, `gui/api.py`.
- Verification: server/GUI plan-adjacent, planning, task, and work-item tests
  passed `22 passed` with one existing FastAPI/httpx deprecation warning; all
  four modified Python modules compiled successfully.
- Remaining risk: server and GUI still duplicate workflow logic; future
  changes should converge on a shared plan-storage module to prevent semantic
  drift.

## Verified fix: V5 checkpoint persistence no longer blocks state transitions

- Problem: async `NexusLoopV5._transition_to()` called checkpoint serialization
  synchronously. Each checkpoint performs JSON sanitization, file fsync/replace,
  and retention pruning, so slow filesystem activity could stall streaming,
  heartbeat delivery, and cancellation.
- Fix: checkpoint save now runs through `asyncio.to_thread` while preserving
  the existing state-transition ordering and checkpoint-path bookkeeping.
- Files: `orchestrators/v5/core.py`,
  `tests/v5/test_v5_checkpoint_resume_loop.py`.
- Verification: checkpoint-resume plus direct-loop regressions passed
  `46 passed` with 10 existing datetime deprecation warnings. The new heartbeat
  test injects an 80 ms checkpoint delay and confirms the async loop continues
  making progress.
- Remaining risk: checkpoint reads used by explicit resume commands remain
  synchronous in legacy command paths; they are short bounded reads but should
  be audited separately for large checkpoint payloads.

## Verified fix: V5 continuation checkpoint reads leave the event loop free

- Problem: explicit `continue`/`resume` requests synchronously inspected
  continuity files and loaded/restored checkpoint JSON inside the async direct
  loop. Large or slow checkpoint storage could delay the next model request and
  stream heartbeat.
- Fix: continuity inspection and checkpoint load/rehydration now run through a
  worker-thread helper. The existing evidence envelope, fallback to read-only
  load, and failure isolation are preserved.
- Files: `orchestrators/v5/core.py`.
- Verification: V5 checkpoint, direct-loop, and continuity persistence tests
  passed `57 passed` with 10 existing datetime deprecation warnings; core
  compilation passed.
- Remaining risk: checkpoint state restoration is still performed by the
  worker helper as one atomic pre-model operation; future concurrent runtime
  consumers should not invoke it while a turn is mutating shared state.

## Verified fix: GUI todo persistence leaves the async event loop free

- Problem: `/api/todo` synchronously rewrote the session event log, performed
  fsync, and emitted plan-phase events from an async FastAPI handler. Large
  plans or event histories could delay chat streaming and cancellation.
- Fix: request parsing remains async, while the complete ordered todo/event
  persistence transaction runs through `asyncio.to_thread` in a dedicated sync
  helper. The shared plan and event locks remain in force.
- Files: `gui/api.py`, `tests/gui/scripts/test_todo_async_boundary.py`.
- Verification: todo-boundary, source-ingestion, and work-event GUI tests
  passed `40 passed` with one existing FastAPI/httpx deprecation warning; GUI
  compilation passed.
- Remaining risk: several less frequently used GUI configuration endpoints
  still perform small synchronous JSON/YAML writes inline and need a separate
  endpoint-by-endpoint audit.

## Verified fix: GUI artifact persistence leaves the async event loop free

- Problem: `/api/artifacts` accepted artifacts up to 2 MiB but synchronously
  created directories, wrote the file, and appended file/verification events
  inside an async handler.
- Fix: validation and path checks remain in the endpoint; file persistence and
  event emission now run in `_create_artifact_sync` through `asyncio.to_thread`.
- Files: `gui/api.py`, `tests/gui/scripts/test_artifact_async_boundary.py`.
- Verification: artifact, todo, source-ingestion, and work-event GUI tests
  passed `42 passed` with one existing FastAPI/httpx deprecation warning; GUI
  compilation passed.
- Remaining risk: small session metadata writes in GUI `chat`/`rename_session`
  and a few configuration endpoints remain inline and are next async-boundary
  candidates.

## Verified fix: GUI provider probes leave the event loop free

- Problem: `/api/providers/ping` performed blocking DNS/TCP/TLS `urllib` I/O
  inline in an async handler with a five-second timeout. An unreachable provider
  could stall GUI chat/event streaming for the full timeout.
- Fix: endpoint authorization and request extraction remain on the async path;
  the bounded network probe now runs in `_ping_provider_sync` via
  `asyncio.to_thread`. Existing URL validation and success/error payloads are
  unchanged.
- Files: `gui/api.py`,
  `tests/gui/scripts/test_provider_ping_async_boundary.py`.
- Verification: provider configuration, ping-boundary, artifact, and todo
  boundary tests passed `8 passed` with one existing FastAPI/httpx warning;
  GUI compilation passed.
- Remaining risk: GUI `save_config` and provider add/configure still perform
  synchronous YAML writes inline and are next configuration-mutation targets.

## Verified fix: GUI provider configuration mutations are serialized and offloaded

- Problem: provider add/configure/delete endpoints performed YAML load/modify/
  save inline and without a transaction boundary. Concurrent requests could
  lose an instance update and a slow filesystem operation could block GUI
  streaming.
- Fix: provider mutations now run in worker threads, share a local re-entrant
  lock plus SQLite interprocess mutex, reload current YAML inside the
  transaction, and persist with fsync plus atomic replacement.
- Files: `gui/api.py`, `tests/gui/scripts/test_provider_config.py`.
- Verification: provider configuration and ping-boundary tests passed `5 passed`
  with one existing FastAPI/httpx warning, including concurrent updates to two
  provider instances; GUI compilation passed.
- Remaining risk: the generic `/api/config` save path still delegates to the
  synchronous kernel config implementation and needs a separate lifecycle-safe
  audit.

## Verified fix: generic configuration persistence contract is restored

- Problem: `NexusConfigLoader` exposed `data` only as a getter and had no
  `save()` method, while GUI configuration endpoints assigned
  `kernel.config.data` and called `kernel.config.save()`. Those routes could
  fail at runtime before persistence, and the generic async endpoint also ran
  disk I/O inline.
- Fix: the loader now validates a data setter and persists existing YAML/JSON
  cache entries with a SQLite cross-process mutex, fsync, and atomic replace.
  `/api/config` delegates assignment, save, and reload to a worker thread.
  Unknown mapping keys are not treated as filenames.
- Files: `config/config_loader.py`, `gui/api.py`,
  `tests/test_config_loader_persistence.py`,
  `tests/gui/scripts/test_config_async_boundary.py`.
- Verification: config round-trip, generic config boundary, and provider
  configuration tests passed `5 passed` with one existing FastAPI/httpx
  warning; both modified modules compiled successfully.
- Remaining risk: several specialized GUI endpoints still call
  `kernel.config.save()` inline; they now have a working persistence contract
  but require worker-boundary conversion for full event-loop isolation.

## Verified fix: specialized GUI config mutations use the worker boundary

- Problem: plugin, skill/tool-asset, and MCP configuration endpoints called
  `kernel.config.save()` directly from async handlers. Once the loader contract
  was repaired, these writes were functional but still blocked the event loop.
- Fix: a shared `_mutate_kernel_config_sync` helper now holds the kernel lock,
  applies the mutation, saves, and reloads in the worker thread. All remaining
  async GUI config mutation endpoints use it.
- Files: `gui/api.py`, `tests/gui/scripts/test_config_async_boundary.py`.
- Verification: config loader, server MCP, plugin, GUI config, and provider
  tests passed `18 passed` with one existing FastAPI/httpx warning; GUI
  compilation passed. The AST regression confirms no async GUI endpoint calls
  `.save()` inline.
- Remaining risk: plugin disk removal and some non-kernel JSON/YAML endpoint
  mutations still need separate filesystem-boundary review.

## Verified fix: GUI plugin filesystem mutations leave the async loop free

- Problem: local plugin creation synchronously created directories, wrote the
  manifest and README, and could leave a partially-created plugin on failure.
  Disk-removable plugin deletion synchronously called `shutil.rmtree`; a large
  plugin tree could block unrelated GUI requests.
- Root cause: plugin filesystem lifecycle code lived directly in async route
  handlers and the create path had no worker-side race/rollback boundary.
- Fix: creation and removal now run through worker-thread helpers protected by
  a local re-entrant lock. Creation detects concurrent existence, fsyncs the
  manifest/README, and removes its exact target on partial failure. Deletion
  re-checks resolved realpath containment before removing the validated plugin
  tree.
- Files: `gui/api.py`, `tests/gui/scripts/test_config_async_boundary.py`.
- Verification: GUI configuration/async-boundary tests passed `4 passed`;
  `gui/api.py` compiled successfully.
- Remaining risk: session metadata writes in GUI `chat`/`rename_session` and
  equivalent server-side JSON mutations remain candidates for the next
  endpoint-level audit.

## Verified fix: server session rename persists metadata off-loop

- Problem: the server `/api/sessions/rename` route wrote session metadata
  directly from an async handler. Slow storage could delay unrelated API
  requests, and a process interruption could leave a truncated metadata file.
- Fix: metadata persistence now runs in a worker thread through an atomic
  temp-file, flush/fsync, and replace helper with cleanup of the exact temp
  path.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: server async-boundary plus GUI plugin/config boundary tests
  passed `6 passed`; `server/__init__.py` compiled successfully.
- Remaining risk: GUI session metadata and several server runtime-preference
  writes still need the same endpoint-level review.

## Verified fix: server runtime-preference writes are offloaded

- Problem: async server endpoints for mode, permissions, model, sandbox,
  thinking, workspace root/directories, and runtime management called the
  synchronous `_save_runtime_preferences()` persistence path inline. The path
  loads and rewrites configuration, so slow storage could stall API streaming
  and cancellation.
- Fix: async call sites now use `await asyncio.to_thread(...)`; synchronous
  route/helper call sites remain synchronous. An AST regression prevents a
  direct runtime-preference save from being reintroduced into an async route.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: server async-boundary tests passed `3 passed`; the server
  module compiled successfully.
- Remaining risk: the broad `/api/manage` route still performs several other
  config writes inline (`_save_nexus_config`, MCP/Claude settings), and GUI
  session metadata remains a separate candidate.

## Verified fix: `/api/manage` configuration I/O is isolated from the event loop

- Problem: the management route loaded and persisted Nexus config, Claude
  plugin settings, MCP server state, and task state directly from an async
  handler. A slow or contended filesystem could stall unrelated API traffic;
  MCP persistence also required preserving the save-then-sync ordering.
- Fix: management config loading and all branch-specific persistence now run
  through worker-thread calls. `_persist_manage_config_sync` preserves the
  ordered Nexus-config/MCP-file transaction, while plugin settings and task
  state use their existing persistence functions off-loop.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: server and GUI async-boundary tests passed `8 passed`; the
  server module compiled successfully. The AST regression confirms the route
  has no direct config/task persistence calls.
- Remaining risk: other server endpoints (`create_mcp`, workspace protected
  paths/instructions/import) still contain separate config mutations and need
  endpoint-specific transaction review; GUI session metadata remains pending.

## Verified fix: remaining server workspace config routes are offloaded

- Problem: MCP creation and workspace protected-path, instruction, and import
  routes still loaded or rewrote Nexus configuration directly in async
  handlers. This left avoidable event-loop stalls after `/api/manage` was
  hardened.
- Fix: these routes now offload configuration load/save operations; MCP uses
  the existing ordered config-plus-server-file persistence helper. Validation,
  cache invalidation, and activity-event ordering remain in the route.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: server async-boundary tests passed `5 passed`; the server
  module compiled successfully.
- Remaining risk: these routes still load/modify snapshots separately, so
  high-contention concurrent updates may require a full reload-mutate-save
  transaction rather than only an async boundary.

## Verified fix: GUI session metadata persistence is atomic and off-loop

- Problem: GUI rename and first-chat auto-title paths wrote `.meta` JSON
  directly from async handlers, allowing slow storage to delay streaming and
  interruption to leave truncated metadata.
- Fix: both paths now use a worker-thread helper with an exact temp file,
  flush/fsync, atomic replacement, and cleanup.
- Files: `gui/api.py`, `tests/gui/scripts/test_config_async_boundary.py`.
- Verification: combined GUI/server async-boundary tests passed `10 passed`;
  both modules compiled successfully.
- Remaining risk: GUI chat still performs small synchronous metadata reads
  while deciding whether to auto-title; persistence itself is isolated.

## Verified fix: protected-path updates are reload-mutate-save transactions

- Problem: workspace protected-path endpoints loaded settings before entering
  a worker, mutated a stale snapshot, and saved afterward. Concurrent add or
  remove requests could overwrite one another even though the writes were
  atomic individually.
- Root cause: the server had cross-process event locks for event logs but no
  shared transaction primitive for settings mutations.
- Fix: added `_mutate_nexus_config_sync`, combining a process-local reentrant
  lock with the settings sidecar SQLite mutex, reload, mutation callback, and
  atomic fsync-backed save. Protected-path add/remove now use that single
  transaction and preserve duplicate/not-found responses.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: config-loader, server, and GUI boundary tests passed `12
  passed`; server compilation passed.
- Remaining risk: MCP/workspace instruction/import routes are offloaded but
  still use snapshot mutation; migrating them to the same transaction helper
  is the next consistency improvement.

## Verified fix: MCP and workspace settings use the shared config transaction

- Problem: MCP creation and workspace instruction/import routes could still
  overwrite concurrent settings changes because their offloaded operations
  used independently loaded snapshots. MCP also updated YAML and its registry
  file as two separate route-level operations.
- Fix: MCP creation now reloads, mutates, saves, and synchronizes both stores
  under the settings lock. Workspace instructions and applied imports use the
  same reload-mutate-save transaction helper.
- Files: `server/__init__.py`.
- Verification: server boundary and config-loader tests passed `7 passed`;
  server compilation passed. Existing AST coverage confirms no direct config
  I/O remains in the affected async routes.
- Remaining risk: provider/runtime settings and some legacy configuration
  paths use separate persistence mechanisms and need compatibility/concurrency
  review.

## Verified fix: durable task writes are serialized and off-loop

- Problem: task create/update routes synchronously rewrote `logs/tasks.json`,
  and the writer used a shared fixed temp filename without an interprocess
  mutex or fsync. Concurrent task updates could block the event loop or leave
  persistence vulnerable to races and truncated data.
- Fix: task persistence now uses a process-local lock plus the task sidecar
  SQLite mutex, unique temporary files, flush/fsync, and atomic replacement.
  Async task routes call the writer through `asyncio.to_thread`.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: server boundary tests passed `7 passed`; server compilation
  passed.
- Remaining risk: the in-memory task mutation itself is still process-local;
  multi-worker task ownership/claim semantics require a broader durable queue
  design.

## Verified fix: runtime and plugin settings use transactional persistence

- Problem: runtime preference saves reloaded and rewrote settings without the
  shared config lock, and concurrent plugin-management requests could lose
  updates in `.claude/settings.json`. The Claude writer also used a fixed temp
  path without fsync.
- Fix: `_save_runtime_preferences` now delegates to the shared settings
  reload-mutate-save transaction. Claude plugin settings now have a matching
  cross-process transaction, process-local lock, unique temp files, fsync, and
  atomic replacement.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: server boundary tests passed `9 passed`; server compilation
  passed.
- Remaining risk: provider profile/config stores outside these two files may
  still have independent locking and need a separate provider-system audit.

## Verified fix: provider profile mutations merge stale store instances safely

- Problem: `ProviderProfileStore` already locked file writes, but mutation
  methods changed an in-memory snapshot before saving. Two long-lived store
  instances could therefore overwrite each other's newly-added profiles,
  defaults, or strategies.
- Fix: add/set-default/delete/set-strategy now acquire the existing process
  lock, reload current disk state, mutate, and save while the lock is held.
  Profile persistence also flushes/fsyncs unique same-directory temp files
  before atomic replacement.
- Files: `providers/profiles.py`,
  `tests/test_provider_profiles_routing.py`.
- Verification: provider profile and store tests passed `11 passed, 1
  skipped`, including a stale-store merge regression.
- Remaining risk: OAuth token storage and provider health persistence use
  separate stores and require an equivalent cross-process audit.

## Verified fix: OAuth token storage is cross-process safe

- Problem: OAuth credentials used atomic replacement but no lock or reload
  boundary. Concurrent refresh/login processes could overwrite each other's
  provider tokens; reads from a long-lived store could also be stale.
- Fix: reads and mutations now use a cross-platform file lock and reload the
  latest store. Writes use unique same-directory temp files, fsync, private
  permissions, and atomic replacement.
- Files: `providers/oauth/storage.py`,
  `tests/test_oauth/scripts/test_storage.py`.
- Verification: OAuth storage and provider profile tests passed `18 passed, 1
  skipped`; OAuth storage compiled successfully. A stale-store credential
  merge regression is covered.
- Remaining risk: provider health persistence remains a separate store and is
  the next provider reliability target.

## Verified fix: provider-health persistence rejects stale updates

- Problem: SQLite transactions serialized health writes, but a delayed health
  record from another registry could still overwrite a newer record because
  the upsert had no recency guard.
- Fix: the provider-health upsert now applies an update only when the incoming
  `checked_at` is at least as recent as the stored value. This preserves the
  latest observed health state across processes while retaining existing
  locking and read behavior.
- Files: `providers/health.py`,
  `tests/test_provider_health_routing_loop.py`.
- Verification: provider-health tests passed `10 passed`; health module
  compilation passed, including a stale-update regression.
- Remaining risk: health timestamps rely on wall-clock time; clock skew
  between hosts/processes could still affect ordering and may warrant a
  monotonic sequence in a future distributed-health design.

## Verified fix: reliability wrapper awaits async callable instances

- Problem: `inspect.iscoroutinefunction()` does not identify objects whose
  asynchronous behavior is implemented by `async __call__`. The reliability
  wrapper could therefore invoke such a provider/tool through its synchronous
  path and leak an un-awaited coroutine instead of applying retries.
- Fix: callable objects with an asynchronous `__call__` are now recognized as
  async callables and routed through the awaited retry path.
- Files: `providers/reliability.py`, `tests/test_redesign_reliability.py`.
- Verification: reliability, provider-attempt, and streaming-router tests
  passed `32 passed`; reliability module compilation passed.
- Remaining risk: provider-specific retry idempotency and side-effect
  handling still require workload-level review.

## Verified fix: Telegram message delivery does not replay non-idempotent sends

- Problem: the Telegram adapter retried `send_message` twice after transient
  failures. A timeout can occur after Telegram accepted the request, so replay
  could deliver duplicate user-visible responses.
- Fix: message delivery now uses one bounded attempt (`retry_policy=0`), while
  typing indicators retain retry behavior because they are disposable. The
  adapter still returns a structured failed `SendResult`.
- Files: `gateway/platforms/telegram.py`,
  `tests/test_gateway_telegram_discord.py`.
- Verification: Telegram gateway and reliability tests passed `40 passed, 2
  skipped`, including a timeout-after-send regression.
- Remaining risk: other gateway adapters need the same idempotency inventory;
  platform APIs with explicit idempotency keys can support safer retries.

## Verified fix: gateway delivery errors are redacted before durable storage

- Problem: outbound adapter errors were written directly into the durable
  delivery ledger. Provider URLs, bearer tokens, or platform credentials in an
  exception could therefore persist in `.nexus/gateway_delivery.sqlite3`.
- Fix: delivery result errors and raised exceptions now pass through the
  shared secret-redaction function before ledger persistence. Gateway reasoning
  errors are also redacted before logging.
- Files: `gateway/run.py`.
- Verification: gateway delivery and Telegram tests passed `29 passed, 2
  skipped`; `gateway/run.py` compiled successfully.
- Remaining risk: the user-facing gateway error payload still uses a legacy
  formatted error string and should be reviewed separately for safe detail
  levels.

## Verified fix: gateway reasoning failures expose safe public errors

- Problem: the gateway queued raw exception text as a user-visible response
  after reasoning failed. Even with durable ledger redaction, provider
  credentials or internal paths could leak to the chat platform.
- Fix: reasoning failures now log a redacted diagnostic but queue a stable,
  non-sensitive public error message. Detailed failure context remains in
  server-side logs only.
- Files: `gateway/run.py`, `tests/test_gateway_runtime.py`.
- Verification: gateway runtime and delivery tests passed `13 passed`; the
  regression confirms a secret-bearing provider error is not sent to users.
- Remaining risk: adapter-specific errors returned directly by individual
  platform implementations require a separate consistency review.

## Verified fix: gateway adapter lifecycle failures are isolated

- Problem: `GatewayRunner.run()` connected adapters serially without catching
  exceptions, so one broken platform could prevent every later adapter from
  starting. Shutdown similarly stopped at the first disconnect exception.
- Fix: per-adapter connect/disconnect helpers now isolate failures, record
  redacted diagnostics, update adapter health, and allow healthy adapters to
  continue. Successful connections explicitly restore healthy state.
- Files: `gateway/run.py`, `tests/test_gateway_runtime.py`.
- Verification: gateway runtime and delivery tests passed `15 passed`; the
  gateway runner compiled successfully, including failing-connect and
  failing-disconnect regressions.
- Remaining risk: reconnect scheduling is owned by `GatewaySupervisor` and
  needs an end-to-end test with a real runner lifecycle.

## Verification: supervisor reconnect lifecycle remains green

- Evidence: the existing supervisor suite exercises exponential backoff,
  crash-loop disable/cooldown, persisted disabled state, guarded polling, and
  reconnect recovery.
- Verification: `tests/test_redesign_gateway_lifecycle.py` passed `9 passed`
  after the per-adapter lifecycle isolation change.
- Remaining risk: a full production runner plus supervisor integration test is
  still useful to validate shared delivery draining during reconnects.

## Verified fix: supervised gateway starts durable delivery draining

- Problem: `GatewaySupervisor` owned a `GatewayRunner` but only started its
  lifecycle tick. The runner's durable delivery loop remained stopped, so
  queued outbound responses could wait indefinitely after restart unless a
  later inbound request triggered an opportunistic drain.
- Fix: `GatewayRunner` now exposes independent delivery-loop start/stop
  helpers, and the supervisor starts/stops that worker without taking ownership
  of adapter connect/disconnect. Legacy `GatewayRunner.run()` behavior remains
  unchanged.
- Files: `gateway/run.py`, `gateway/supervisor.py`,
  `tests/test_redesign_gateway_lifecycle.py`.
- Verification: gateway lifecycle, runtime, and delivery tests passed `24
  passed`; gateway modules compiled successfully. The new lifecycle regression
  confirms supervisor startup and shutdown control the delivery worker.
- Remaining risk: delivery draining and adapter reconnect now run as separate
  workers; a production integration test should exercise both during a
  platform outage.

## Verified fix: supervised delivery restart path is integration-tested

- Problem: unit tests proved the supervisor called delivery-loop hooks, but did
  not prove a real queued response was drained after supervisor startup.
- Fix: the delivery loop now has an explicit configurable interval for
  controlled operation/testing, and the supervisor lifecycle suite exercises a
  real `GatewayRunner` plus `DeliveryLedger` restart queue.
- Files: `gateway/run.py`, `tests/test_redesign_gateway_lifecycle.py`.
- Verification: lifecycle and delivery tests passed `16 passed`; gateway
  modules compiled successfully. The integration regression confirms a queued
  response reaches `sent` without a new inbound event.
- Remaining risk: platform reconnect during an in-flight delivery still needs
  a failure-injection test to validate lease renewal and reclaim behavior.

## Verified fix: expired delivery owners cannot mutate reclaimed work

- Problem: `DeliveryLedger.renew`, `ack`, and `fail` checked ownership but not
  lease expiry. A delayed worker could therefore renew or finalize an already
  expired lease before another worker reclaimed it.
- Fix: all three mutations now require `lease_until > now`, so expiry itself
  revokes authority. Existing compare-and-update ownership guards remain in
  place for races with a new owner.
- Files: `gateway/delivery.py`, `tests/test_gateway_delivery.py`.
- Verification: delivery and supervisor lifecycle tests passed `17 passed`;
  the stale-owner regression confirms renew/ack/fail all reject expired work.
- Remaining risk: external platform delivery remains intentionally
  at-least-once; remote idempotency keys are needed for exactly-once effects.

## Verified fix: adapter lifecycle diagnostics are redacted consistently

- Problem: shared polling and supervised connect failures stored raw exception
  text in adapter/runtime state. Those fields are persisted and exposed by
  diagnostics, creating a secret/path leakage path despite delivery-ledger
  redaction.
- Fix: the base adapter polling loop and `PlatformRuntime.connect_once` now
  use the shared secret-redaction function before assigning `last_error`.
- Files: `gateway/base.py`, `gateway/supervisor.py`,
  `tests/test_redesign_gateway_lifecycle.py`.
- Verification: gateway lifecycle, runtime, and reliability tests passed `22
  passed`; modified gateway modules compiled successfully.
- Remaining risk: several individual adapter `SendResult(error=...)` values
  remain raw in memory, although the delivery boundary redacts them before
  durable storage.

## Verified fix: `SendResult` normalizes adapter error text centrally

- Problem: platform adapters independently constructed `SendResult` objects
  with raw exception strings, leaving an inconsistent in-memory/API leakage
  path even after lifecycle and delivery-boundary redaction.
- Fix: the shared result contract now redacts and bounds `error` during
  dataclass initialization, covering every adapter without duplicated
  platform-specific patches.
- Files: `gateway/base.py`, `tests/test_gateway_runtime.py`.
- Verification: gateway runtime, delivery, Telegram, and supervisor tests
  passed `53 passed, 2 skipped`; the base module compiled successfully.
- Remaining risk: legacy script-level gateway APIs return plain dictionaries
  and need separate normalization if they are exposed to untrusted callers.

## Verified fix: gateway lifecycle snapshots are crash- and concurrency-safe

- Problem: `GatewayStateStore` used atomic replacement but did not serialize
  readers/writers across gateway processes, fsync the JSON before replacement,
  or fsync the containing directory afterward. Concurrent supervisors could
  overwrite snapshots nondeterministically, and a power loss could lose a
  successfully reported lifecycle update.
- Root cause: the state file had an atomicity guarantee but no durability or
  ownership protocol around the full snapshot transaction.
- Fix: state loads and saves now use a thread lock plus a sidecar SQLite
  `BEGIN IMMEDIATE` mutex, unique same-directory temporary files, file fsync,
  atomic replacement, and best-effort directory fsync. Existing soft-failure
  behavior for unreadable/corrupt state is preserved.
- Files: `gateway/state.py`, `tests/test_gateway_state_store.py`.
- Verification: state-store, supervisor lifecycle, and delivery tests passed
  `21 passed`; concurrent snapshot writes remained valid JSON and corrupt
  snapshots still returned an empty state.
- Remaining risk: snapshots are full-map replacements; multiple independent
  supervisors should not concurrently manage the same platform set unless
  their ownership policy is explicitly defined.

## Verification sweep: gateway persistence and provider reliability

- Command: `.venv\\Scripts\\python.exe -m py_compile gateway\\state.py` and
  the gateway, delivery, lifecycle, provider-health, OAuth, and provider
  profile routing families.
- Result: `232 passed, 1 skipped` in `13.83s`.
- Note: the repository-wide suite was previously bounded at 120 seconds and
  did not produce a usable report; this family result is the current reliable
  regression evidence, not a claim that the full suite is green.

## Verified fix: voice API no longer exposes internal exceptions

- Problem: active `/api/voice/*` endpoints returned raw exception strings in
  HTTP details, JSON error messages, and SSE frames. Provider paths, local
  filenames, TLS diagnostics, and credential-shaped values could therefore
  reach GUI or external clients.
- Root cause: voice handlers treated exception text as a user-facing status
  contract instead of separating diagnostics from public error semantics.
- Fix: voice failures now log redacted diagnostics and return stable
  operation-level messages (`Voice transcription unavailable`, etc.) across
  status, listening, speech, history, settings, listing, and streaming paths.
- Files: `server/__init__.py`, `tests/test_server_voice_error_contract.py`.
- Verification: voice error-contract and server work-item tests passed `10
  passed` with one pre-existing TestClient deprecation warning; the server
  module compiled successfully.
- Remaining risk: other non-voice server endpoints still contain legacy
  `str(e)` response paths and should be migrated through the same public-error
  boundary as their reachability and client contracts are confirmed.

## Verified fix: memory API no longer exposes storage exceptions

- Problem: active memory statistics/search/export/import/clear/session routes
  returned raw exception text to API clients, potentially exposing local paths,
  database details, or credential-shaped values.
- Root cause: legacy handlers used exception strings as their JSON error
  contract and logged with no shared public-error policy.
- Fix: added a shared `_public_api_failure` boundary that logs a redacted
  diagnostic and returns a stable operation-level message. Memory routes now
  use it consistently.
- Files: `server/__init__.py`, `tests/test_server_memory_error_contract.py`.
- Verification: voice, memory, and server work-item tests passed `11 passed`
  with one pre-existing TestClient deprecation warning; the server compiled.
- Remaining risk: other active server domains still need the same reachability
  review before their legacy error responses can be safely migrated.

## Audit finding: duplicate shadowed voice routes

- Evidence: runtime inspection of `server.app.routes` reports duplicate
  registrations for `GET /api/voice/status`, `/history`, `/voices`,
  `/languages`, and `POST /api/voice/settings`. The first handlers are the
  live routes; the later `get_*`/`update_*` handlers are shadowed but remain in
  the module.
- Impact: fixes and behavior changes can land in an unreachable implementation,
  while the dead block retains raw exception responses and duplicate voice
  configuration logic.
- Status: confirmed architectural debt; no deletion made yet because direct
  Python callers may still import the legacy function names. Next action is to
  inventory callers and consolidate the route contract with compatibility
  wrappers where required.

## Verified fix: shadowed voice routes consolidated without breaking names

- Problem: five duplicate voice routes were registered; FastAPI used the first
  handler while later legacy handlers remained unreachable. The live settings
  handler also changed only in-memory state, leaving the shadowed persistence
  implementation disconnected.
- Fix: removed duplicate route decorators while retaining legacy function
  names for direct Python compatibility. The live settings handler now
  persists an allowlisted subset of voice settings via the serialized config
  loader on a worker thread.
- Files: `server/__init__.py`, `tests/test_server_voice_error_contract.py`.
- Verification: voice contract tests passed `4 passed`; route introspection
  reported `duplicate_voice_routes=[]`; the server compiled successfully.
- Remaining risk: other server domains may contain similar duplicate route or
  shadowed implementation patterns and require the same runtime inventory.

## Verification sweep: server/API regression families

- Scoped async/API boundary tests passed `14 passed`.
- Hive persistence, MCP configuration, and provider-status tests passed `15
  passed`.
- Server test collection contains `88` tests. A broader combined server
  command exceeded the 120-second execution limit without a usable report, so
  it is intentionally not treated as green evidence.

## Verification: MCP failure isolation remains bounded

- Evidence: hung stdio-server, registry lifecycle, MCP adapter, and tool
  integration suites exercised unanswered handshakes, bounded discovery,
  breaker short-circuit/cooldown, tool parking, and recovery callbacks.
- Result: `25 passed` in `56.75s`. The slowest cases (~13s) intentionally pay
  the configured reconnect/backoff budget against a dead process; repeated
  calls then fail fast through the breaker.
- Assessment: no new MCP code change was justified by this audit; existing
  failure isolation is covered by realistic process-level tests.
- Remaining risk: the client uses synchronous worker-thread recovery and
  sleeps during reconnect, so callers must remain off the event loop. An
  async-facing MCP boundary should be checked during the broader tool/runtime
  audit.

## Verified fix: checkpoint resume is session-isolated

- Problem: V5 checkpoint filenames are keyed by caller-supplied turn IDs, but
  `_checkpoint_resume` restored a matching checkpoint without validating its
  persisted session. A turn-ID collision could hydrate another session's plan,
  memory, and outcome.
- Root cause: checkpoint lookup treated the filename as sufficient identity;
  the durable `session` field was recorded but not enforced.
- Fix: resume now rejects checkpoints whose persisted session differs from the
  current loop session, while preserving safe no-op behavior for missing or
  corrupt snapshots.
- Files: `orchestrators/v5/checkpoint.py`,
  `tests/v5/test_v5_checkpoint_resume_loop.py`.
- Verification: checkpoint/resume tests passed `9 passed`; the checkpoint
  module compiled successfully.
- Remaining risk: checkpoint writes are full-file snapshots and still need a
  cross-process transaction/ownership audit for concurrent writers.

## Verified fix: checkpoint replacement and pruning are serialized

- Problem: atomic per-file replacement did not prevent concurrent checkpoint
  writers from racing with directory pruning, causing nondeterministic state
  retention and possible read/list races during long-running sessions.
- Fix: checkpoint save-plus-prune now uses a thread lock and sidecar SQLite
  `BEGIN IMMEDIATE` mutex per checkpoint directory. Temporary files remain
  same-directory, fsynced, and atomically replaced.
- Files: `orchestrators/v5/checkpoint.py`,
  `tests/v5/test_v5_checkpoint_resume_loop.py`.
- Verification: checkpoint/resume suite passed `10 passed` with concurrent
  writer coverage; two existing datetime deprecation warnings remain.
- Remaining risk: durable task ownership must still be checked so a resumed
  checkpoint cannot cause duplicate external side effects.

## Verified fix: expired queue workers cannot renew leases

- Problem: `TaskQueue.ack_lease` validated only the lease token. A delayed
  worker could renew an already-expired lease before the reaper reclaimed it,
  extending authority after another worker was eligible to take over.
- Root cause: lease expiry was enforced by the reaper/claim path but not by the
  heartbeat mutation itself.
- Fix: heartbeat renewal now requires `state == leased`, matching token, a
  non-null `leased_until`, and `leased_until > now`. The existing queue worker
  heartbeat remains compatible with normal positive-duration leases.
- Files: `queue/store.py`, `tests/test_queue_store.py`.
- Verification: queue store, queue driver, and reliability suites passed `34
  passed`; queue modules compiled successfully.
- Remaining risk: administrative completion/failure calls without a token are
  intentionally retained for compatibility and must remain restricted to
  trusted callers.

## Verified fix: durable queue diagnostics redact secrets

- Problem: `TaskQueue.fail`, cancellation, and cron-run updates persisted raw
  exception text in SQLite. These records survive process restarts and are
  exposed through queue inspection/diagnostic paths.
- Fix: durable error fields now pass through the shared secret redactor and a
  1000-character bound before storage. Task status values remain unmodified;
  only diagnostic text is sanitized.
- Files: `queue/store.py`, `tests/test_queue_store.py`.
- Verification: queue store/driver, cron, alert, and status tests passed `30
  passed`; the queue store compiled successfully.
- Remaining risk: trusted administrative callers can still finalize tasks
  without a lease token by design; API exposure of those methods should remain
  restricted and audited.

## Verified fix: queue restart reconciles canonical completion

- Problem: a worker could complete the canonical control-plane run and then
  crash before acknowledging the legacy SQLite queue row. On restart, the
  queue re-leased the task, but the driver attempted to start a new canonical
  run against an already-completed step and could retry forever or rerun the
  external side effect.
- Root cause: queue/control completion was a two-store handoff with no
  recovery decision for the canonical-success/queue-unacknowledged window.
- Fix: `ControlStore.get_run` exposes the linked run status. On retry, the
  queue driver detects a previously succeeded canonical run, marks the lease
  reconciliation-only, acknowledges the queue row, and skips agent execution.
  Retry paths update the legacy link to the newest canonical run. Custom
  control-store doubles without `get_run` remain compatible.
- Files: `nexus/control_store.py`, `queue/driver.py`,
  `tests/test_queue_control_identity.py`.
- Verification: queue identity, driver, and store tests passed `21 passed`;
  the regression proves completed external work is not rerun after the crash
  window.
- Remaining risk: exactly-once external effects still depend on the tool or
  provider honoring an idempotency key; the queue can now avoid known
  canonical duplicates but cannot undo an already-issued remote request.

## Idempotency boundary audit

- Evidence: `QueueDriver.run_task` passes canonical `task_id`/`turn_id` into
  V5 `stream_run`, but the V5 entrypoint currently has no explicit
  `idempotency_key` contract propagated to tool/provider calls.
- Assessment: local queue/control recovery is now fenced and reconciled, but
  a crash during an in-flight remote side effect can still produce an
  at-least-once external request on retry. This is a known boundary, not a
  silently assumed exactly-once guarantee.
- Next design work: define an idempotency context for side-effecting tools and
  providers, then require adapters to either honor it or report that their
  operation is non-idempotent before automatic retry.

## Verification sweep: durable execution and recovery

- Command covered queue store/driver/control identity, cron, queue alerts and
  status, plus provider reliability tests.
- Result: `48 passed` in `8.74s`.
- This is scoped evidence for durable execution; it does not establish
  exactly-once semantics for arbitrary remote side effects.

## Verified improvement: idempotency context reaches V5 tool execution

- Problem: queue retries had stable local task/control identities, but the V5
  stream entrypoint did not expose a stable idempotency key to the turn or
  registry-backed tools. Side-effecting adapters had no standard context from
  which to derive a deduplication key.
- Fix: queue tasks now derive a stable key from their durable queue namespace
  and task ID (or preserve an explicit enqueue key). Compatible loop
  implementations receive it when their `stream_run` signature supports it;
  V5 stores it in turn metadata and passes it through `_runtime_context` to
  tools.
- Files: `queue/driver.py`, `orchestrators/v5/core.py`,
  `orchestrators/v5/tools.py`, `tests/v5/test_v5_idempotency_context.py`,
  `tests/test_queue_driver.py`.
- Verification: queue identity, queue driver, V5 idempotency, and direct-loop
  suites passed `54 passed`; modified modules compiled successfully.
- Remaining risk: propagation alone does not make a remote operation exactly
  once. Side-effecting tools/providers must explicitly consume the context and
  honor the key; non-idempotent adapters still require retry suppression.

## Verified improvement: tool retries distinguish read-only and side-effecting operations

- Problem: the registry retried every classified transient failure whenever a
  tool schema set `execution.max_retries`, including writes and external sends
  whose timeout could represent an already-applied side effect.
- Root cause: retryability was classified only from the exception, without an
  operation-safety boundary.
- Fix: configured retries remain active for tools classified as read-only.
  Side-effecting tools now suppress automatic retries unless their schema
  explicitly sets `execution.retry_side_effects=true`; that opt-in documents
  that the adapter has an idempotency guarantee. The same rule applies to
  atomic and streaming registry execution, and the model-facing inventory
  exposes the opt-in state.
- Files: `tools/nexus_tools/registry.py`,
  `tests/test_tool_registry/scripts/test_retry_safety.py`.
- Verification: retry-safety, registry, V5 idempotency, and queue-driver tests
  passed `43 passed`; `registry.py` compiled successfully.
- Remaining risk: the registry cannot prove an adapter's idempotency claim;
  provider/tool adapters must still consume the propagated idempotency context
  and set the opt-in only when duplicate requests are safe.

## Verified improvement: global API errors no longer reflect exception text

- Problem: FastAPI's global exception handler returned `str(exc)` in the HTTP
  response. Provider diagnostics, local paths, command arguments, or embedded
  credentials could therefore cross the API boundary.
- Fix: unexpected exceptions are logged with the shared secret redactor and a
  traceback, while clients receive the stable `Internal server error` detail.
  Explicit `HTTPException` contracts remain unchanged.
- Files: `server/__init__.py`, `tests/test_server_global_error_contract.py`.
- Verification: global, voice, memory, and tool-retry error-contract tests
  passed `10 passed`; the server module compiled successfully. One existing
  FastAPI/httpx deprecation warning remains.
- Remaining risk: several legacy route-specific handlers still return raw
  exception text and require incremental endpoint-by-endpoint migration.

## Verification sweep: server reliability/error contracts

- Command covered async boundaries, global error handling, Hive persistence,
  MCP configuration, memory/voice error contracts, provider status, and queue
  supervisor behavior.
- Result: `36 passed` in `4.17s`; one existing FastAPI/httpx deprecation warning.
- Scope note: the full server collection remains larger than this focused
  sweep; broad full-suite execution previously exceeded the available command
  window without a usable report.

## Verified improvement: legacy voice errors use the public contract

- Problem: compatibility voice helpers returned raw exception text in their
  `{status: error, message: ...}` payloads, even though the active voice
  routes had already been hardened.
- Fix: statistics, history, search, export, clear/reset, voice/language/device
  discovery, and settings-update helpers now use the shared redacted logger
  and stable operation-specific messages.
- Files: `server/__init__.py`,
  `tests/test_server_voice_error_contract.py`.
- Verification: voice/global error-contract tests passed `6 passed`; the
  regression exercises the legacy statistics helper directly.
- Remaining risk: other legacy server domains still need endpoint-level
  contract migration.

## Verified improvement: local-engine errors use stable API details

- Problem: engine status, configuration, compilation, and reload endpoints
  exposed raw exception strings through `HTTPException.detail`.
- Fix: each endpoint now logs a redacted diagnostic and returns a stable
  operation-specific public detail while preserving status codes and import
  fallback behavior.
- Files: `server/__init__.py`,
  `tests/test_server_engine_error_contract.py`.
- Verification: engine, voice, global, and memory error-contract tests passed
  `8 passed`; the server module compiled successfully.
- Remaining risk: route-specific raw detail paths remain in session/history,
  file, and other legacy endpoint families.

## Verified improvement: session/history/file failures use stable API details

- Problem: session creation/loading/initialization, history retrieval, and
  workspace-file reads reflected raw exception text through HTTP 500 details.
- Fix: these lifecycle and file-read boundaries now use operation-specific
  stable messages with redacted diagnostics, preserving existing status codes
  and validation errors.
- Files: `server/__init__.py`,
  `tests/test_server_session_error_contract.py`.
- Verification: session, engine, voice, global, and memory error-contract
  tests passed `10 passed`; the server module compiled successfully.
- Remaining risk: a static audit still finds additional legacy handlers with
  raw detail/message paths outside this migrated group.

## Verified improvement: additional legacy API boundaries redact failures

- Problem: OpenAI-compatible streaming/session setup, tool inventory fallback,
  workspace directory listing, and sandbox command failures still reflected
  raw exception text to clients.
- Fix: these paths now return stable operation-specific messages and retain
  redacted diagnostics in server logs. Existing command output and structured
  file-restore diagnostics were not altered.
- Files: `server/__init__.py`,
  `tests/test_server_legacy_error_contract.py`.
- Verification: legacy, session, engine, voice, and global error-contract
  tests passed `11 passed`; the server module compiled successfully.
- Remaining risk: the static inventory still contains raw strings used for
  internal event state, deliberate validation details, and a few legacy route
  families requiring separate contract review.

## Verification sweep: server contract regression after legacy hardening

- Command covered the existing server async/Hive/MCP/provider/queue suites plus
  global, voice, memory, engine, session, and legacy error-contract tests.
- Result: `42 passed` in `5.96s`; one existing FastAPI/httpx deprecation
  warning. `git diff --check` passed for the modified server and registry
  modules.

## Verified improvement: read-only retry classification rejects mutating names

- Problem: the retry safety gate relied on substring heuristics. A compound
  name such as `get_or_create` contained a read-like token and could be
  incorrectly granted automatic retries despite performing a mutation.
- Root cause: the classifier had no explicit metadata precedence and no
  mutating-verb guard.
- Fix: `execution.read_only`/`read_only` metadata now takes precedence;
  otherwise tokenized mutating verbs override read-like tokens. The registry
  inventory exposes the resolved read-only state for diagnostics and UI.
- Files: `tools/nexus_tools/registry.py`,
  `tests/test_tool_registry/scripts/test_tool_registry.py`,
  `tests/test_tool_registry/scripts/test_retry_safety.py`.
- Verification: registry, retry-safety, and MCP tool classification tests
  passed `51 passed`; the registry compiled successfully.
- Remaining risk: adapters without explicit metadata or a trustworthy
  `is_read_only` method still depend on the conservative name classifier;
  side-effecting adapters should declare metadata or opt into idempotent
  retries explicitly.

## Verification sweep: registry/server integration after classifier hardening

- Command covered the server reliability/error-contract group and the full
  `tests/test_tool_registry` package.
- Result: `75 passed` in `8.75s`; one existing FastAPI/httpx deprecation
  warning. `git diff --check` passed for the modified server and registry
  modules.

## Verified improvement: safety API storage failures no longer leak details

- Problem: unexpected failures from the safety store were returned as
  `Safety store is unavailable: <exception>`, exposing paths, database errors,
  or other internal diagnostics across permission and sandbox endpoints.
- Fix: all safety-store 503 branches now return the stable
  `Safety store is unavailable` detail. The existing 400 validation/error
  responses remain unchanged so callers still receive actionable invalid-input
  feedback.
- Files: `server/__init__.py`,
  `tests/test_server_safety_error_contract.py`.
- Verification: safety error-contract plus the complete safety-settings suite
  passed `31 passed` in `27.43s`; the server module compiled successfully.
- Remaining risk: safety-store logs still contain diagnostics by design, so
  log access and redaction policy remain part of the broader observability
  audit.

## Verification sweep: server/tool regression after safety hardening

- Command covered the server async/Hive/MCP/provider/queue/error-contract
  suites, the safety error contract, and the tool-registry package.
- Result: `76 passed` in `11.61s`; one existing FastAPI/httpx deprecation
  warning. A static search found no remaining `Safety store is unavailable:`
  response construction.

## Verified improvement: V5 failed-tool observations redact secrets

- Problem: exceptions raised by registry-backed tools were converted directly
  to `Error: ...` strings and inserted into the model transcript, action
  evidence, lifecycle events, and potentially durable replay data.
- Fix: direct-loop and streaming tool-executor failure boundaries now use the
  shared provider secret redactor and a 4000-character bound before exposing
  diagnostics to the model or persistence layers. The loop's existing
  iteration/repair bounds remain the termination authority.
- Files: `orchestrators/v5/direct_loop.py`, `orchestrators/v5/tools.py`,
  `tests/v5/test_v5_direct_model_tool_loop.py`.
- Verification: direct-loop, tool-health, and idempotency-context tests passed
  `47 passed` in `6.77s`; both modified modules compiled successfully. Eight
  existing datetime deprecation warnings remain.
- Remaining risk: successful tool output can legitimately contain user data
  and still needs the separate output-classification/redaction policy audit;
  this fix covers exception-derived diagnostics.

## Verification sweep: API, registry, and V5 failure-boundary integration

- Command covered the server reliability/error-contract group, safety API,
  tool registry, direct V5 loop, tool health, and idempotency-context tests.
- Result: `123 passed` in `36.26s`; one FastAPI/httpx and eight existing
  datetime deprecation warnings. Modified modules passed compilation and
  `git diff --check`.

## Verified improvement: successful V5 tool output is sanitized at the stream boundary

- Problem: successful tool output could contain credential-shaped material.
  Redacting only failed exceptions left live tool chunks, transcript content,
  oversized archives, and successful action evidence able to retain secrets.
- Fix: V5 command, registry-tool, and code-action chunks now pass through the
  shared secret redactor before live emission. The direct loop sanitizes the
  complete result before transcript insertion, and successful action evidence
  uses the same bounded/archived sanitized representation.
- Files: `orchestrators/v5/tools.py`, `orchestrators/v5/direct_loop.py`,
  `tests/v5/test_v5_direct_model_tool_loop.py`.
- Verification: direct-loop, tool-health, and idempotency tests passed `48
  passed` in `8.83s`; modified modules compiled successfully. Eight existing
  datetime deprecation warnings remain.
- Remaining risk: redaction is pattern-based and cannot identify every
  organization-specific secret format; configurable secret detectors remain a
  future observability/security improvement.

## Verification sweep: public API, registry, safety, and V5 output boundaries

- Command covered the server reliability/error-contract group, safety API,
  tool registry, direct V5 loop, tool health, and idempotency-context tests.
- Result: `124 passed` in `37.72s`; one FastAPI/httpx and eight existing
  datetime deprecation warnings. Modified modules passed `git diff --check`.

## Verified improvement: shared secret redaction covers common credential formats

- Problem: the shared provider redactor missed several high-confidence secret
  shapes used by current integrations, including GitHub tokens, Slack tokens,
  npm/PyPI tokens, live/test payment keys, AWS access-key IDs, inline
  `token=`/`password=` assignments, and PEM private-key blocks.
- Fix: added narrowly scoped patterns with minimum lengths and preserved short
  human-readable text. Existing environment-value replacement and provider
  classification behavior remain unchanged.
- Files: `providers/reliability.py`,
  `tests/test_provider_secret_redaction.py`.
- Verification: provider redaction, provider reliability, redesign reliability,
  checkpoint redaction, and environment-redaction tests passed `44 passed` in
  `7.06s`; the provider module compiled successfully.
- Remaining risk: organization-specific secret formats outside these patterns
  still require configurable detectors or explicit environment registration.

## Verification sweep: API, V5, provider reliability, and security redaction

- Command covered the server reliability/error-contract group, safety API,
  registry, V5 loop/output/recovery tests, provider reliability, checkpoint
  redaction, and environment security tests.
- Result: `169 passed` in `43.92s`; one FastAPI/httpx and nine existing
  datetime deprecation warnings. All modified modules passed `git diff --check`.

## Verified improvement: active V5 turn timestamps are timezone-aware UTC

- Problem: the live V5 core used deprecated `datetime.utcnow()` for turn start
  and terminal timestamps, producing warnings and leaving naive datetimes in
  runtime state.
- Fix: active `V5TurnContext` and terminal paths now use
  `datetime.now(timezone.utc)`. The clock remains UTC, but timestamp values are
  explicit and safe for cross-process comparisons/serialization.
- Files: `orchestrators/v5/core.py`,
  `tests/v5/test_v5_timezone_contract.py`.
- Verification: timezone, direct-loop, checkpoint-redaction, and checkpoint
  resume tests passed `54 passed` in `15.91s`; the core module compiled
  successfully and this scope emitted no datetime deprecation warnings.
- Remaining risk: older, non-active PAORR/consciousness helper paths still use
  naive timestamps and should be migrated only with their own compatibility
  audit.

## Verification sweep: current hardened paths after timezone migration

- Command covered the server/API contracts, safety, registry, V5 direct loop,
  checkpoint/recovery, provider reliability/redaction, and environment
  security tests.
- Result: `180 passed` in `59.20s`; one existing FastAPI/httpx deprecation
  warning. All modified modules passed `git diff --check`.

## Verified improvement: V5 legacy timestamp paths use UTC-aware values

- Problem: PAORR plan/action timing, consciousness introspection, and
  self-evolution dataclass defaults still used naive `datetime.utcnow()` values
  after the active core migration.
- Fix: PAORR, consciousness, and self-evolution timestamps now use explicit
  `datetime.now(timezone.utc)`, including dataclass default factories. No
  `datetime.utcnow()` calls remain under `orchestrators/v5`.
- Files: `orchestrators/v5/conscious.py`, `orchestrators/v5/paorr.py`,
  `orchestrators/v5/self_evolution.py`,
  `tests/v5/test_v5_legacy_timezone_contract.py`.
- Verification: legacy timezone, PAORR integrity/visibility, self-evolution,
  and direct-loop tests passed `60 passed` in `13.29s`; modified modules
  compiled successfully.
- Remaining risk: `datetime.now()` remains in a few non-deprecated evolution
  helpers; those paths should be standardized only if their naive timestamp
  compatibility contracts are confirmed.

## Verified improvement: provider intent routing no longer crashes on the live path

- Problem: `ModelRouter._get_required_tier()` imported a nonexistent
  `NexusIntent`, while `cognition.intent_engine.IntentEngine.classify()` was a
  stub returning an untyped default mapping. Heavy-brain routing could fail
  before provider selection instead of classifying the request.
- Root cause: the router and cognition layer had diverged contracts; no test
  exercised the tier decision with the actual legacy mapping result.
- Fix: added a dependency-free `NexusIntent` enum and conservative
  high-signal classifier that preserves the existing mapping return shape.
  The router now normalizes mapping, string, and enum results for compatibility
  with custom engines and partial restores.
- Files: `cognition/intent_engine.py`, `providers/router.py`,
  `tests/test_intent_engine.py`.
- Verification: intent and provider-router tests passed `9 passed` in `0.14s`.
- Remaining risk: this is intentionally lexical routing, not semantic model
  classification; ambiguous requests safely remain in the lighter tier.

## Verified improvement: self-improvement backlog writes are crash- and concurrency-safe

- Problem: active improvement actions were appended without serialization, and
  status rewrites used a shared `.tmp` filename. Concurrent sessions could
  interleave records or replace/delete each other’s temporary file.
- Fix: added a per-path process lock plus SQLite `BEGIN IMMEDIATE` interprocess
  mutex, fsynced append records, and unique temporary files with fsync and
  cleanup for status rewrites.
- Files: `evolution/backlog.py`, `tests/test_evolution_backlog.py`.
- Verification: concurrent backlog and evolution subsystem tests passed
  `16 passed` in `3.10s`.
- Remaining risk: the backlog remains JSONL rather than a fully transactional
  queue; malformed pre-existing lines are preserved and skipped on reads.

## Verified improvement: local engine lifecycle no longer reports fake success

- Problem: engine configuration writes were no-ops, `STATUS_PATH` was empty,
  `reload_engine()` accepted no model argument despite the API passing one,
  and compilation returned a misleading skipped result without lifecycle state.
- Root cause: the engine manager/compiler files were placeholders on an active
  server API path.
- Fix: implemented durable validated engine configuration, atomic JSON writes,
  persisted status, model-artifact validation, and honest `not_ready`/`ready`
  results. The compiler boundary now reports `unavailable` until a portable
  native build contract exists.
- Files: `utils/engine_manager.py`, `utils/engine_compiler.py`,
  `tests/test_engine_manager.py`.
- Verification: engine manager, engine API error contract, and authenticated
  endpoint tests passed `15 passed` in `56.16s`; one existing FastAPI/httpx
  deprecation warning remains.
- Remaining risk: this records readiness but does not itself load a native
  llama.cpp runtime; provider-specific loading remains the next integration
  boundary to audit.

## Verified improvement: `/api/multi_agent` now launches real Hive work

- Problem: the compatibility endpoint returned `started` while only echoing
  the prompt; the response explicitly admitted that no workflow integration
  existed. TUI callers therefore received false progress.
- Fix: validate the request, resolve the requested persona, launch a real
  one-agent Hive through the canonical engine, persist its Hive projection,
  and return the Hive/agent identity while preserving the existing `started`
  response status. Launch failures now return a stable 503 contract.
- Files: `server/__init__.py`, `tests/test_server_multi_agent_bridge.py`.
- Verification: multi-agent bridge, Hive persistence, and engine API tests
  passed `11 passed` in `1.36s`.
- Remaining risk: the compatibility route launches one worker; callers that
  need decomposition/quorum should use the full `/api/hives` contract.

## Verified improvement: local training API has explicit bounded lifecycle state

- Problem: `/api/engine/train` accepted arbitrary values, could launch with
  the caller's cwd, had no durable `training` record before spawning, and
  treated a post-restart missing process as ordinary idle state. Concurrent
  starts also relied only on an in-memory check.
- Fix: validate `steps` to `1..10000`, serialize start checks, launch with the
  project root as cwd, persist an atomic run record with run ID/PID/timestamp,
  and report `failed`, `completed`, or `orphaned` states explicitly.
- Files: `server/__init__.py`, `tests/test_server_training_lifecycle.py`.
- Verification: training lifecycle, engine manager/API, multi-agent bridge,
  and Hive persistence tests passed `18 passed` in `1.17s`; touched modules
  compiled and passed `git diff --check`.
- Remaining risk: training is still a separate process without durable
  cross-server ownership; multi-worker deployments need an interprocess lease
  before allowing concurrent training sessions.

## Verified improvement: training ownership is fenced across server workers

- Problem: the previous training guard prevented duplicates only within one
  Python process. Multiple API workers could each observe no local process and
  launch competing training jobs.
- Fix: training start now uses the existing SQLite interprocess mutex around
  ownership check and spawn, reads the persisted owner record, and honors a
  live owner PID across workers. A dead PID is treated as stale and can be
  reclaimed; status remains explicitly recoverable after restart.
- Files: `server/__init__.py`, `tests/test_server_training_lifecycle.py`.
- Verification: engine/training/API/Hive regression scope passed `19 passed`
  in `0.87s`; server compilation and diff checks passed.
- Remaining risk: PID liveness cannot completely eliminate operating-system
  PID reuse; a future durable worker lease should add renewable owner epochs
  or process-start identity where deployment scale requires it.

## Verified improvement: engine reload model paths are workspace-contained

- Problem: `/api/engine/reload` accepted arbitrary absolute paths and relative
  traversal, allowing a caller to persist an external filesystem path as the
  local model target.
- Fix: added resolved-path containment against `models/local`, including
  symlink-aware resolution, and preserved a client-visible 403 instead of
  converting the boundary failure into a generic 500.
- Files: `server/__init__.py`, `tests/test_engine_manager.py`.
- Verification: engine, training, server error-contract, path-traversal, and
  sandbox-scope tests passed `44 passed, 2 skipped` in `3.54s`; touched modules
  compiled and passed diff checks.
- Remaining risk: deployments that intentionally store models outside the
  project must copy or explicitly provision them under the local-model root;
  broad arbitrary-path loading is intentionally no longer accepted.

## Verified improvement: kernel reinforcement feedback is no longer silently discarded

- Problem: `kernel.reinforce()` reached a `NexusNerveCenter` stub that logged a
  debug message and dropped every reward; mutation logging was also a no-op.
- Fix: added a SQLite-backed, cross-process-safe feedback ledger with bounded
  task/tool labels, finite reward validation, aggregate counts/totals, and
  redacted bounded mutation records. The snapshot explicitly reports model
  training as `not_implemented` rather than implying online RL.
- Files: `neural/nerve_center.py`, `tests/test_neural_nerve_center.py`.
- Verification: nerve, kernel, evolution-subsystem, and secret-redaction
  tests passed `40 passed` in `10.47s`; the nerve module compiled and passed
  diff checks.
- Remaining risk: the ledger is currently an auditable input for future
  routing/training, not yet consumed by a model or routing policy; integrating
  it requires a separate quality/rollback design.

## Verified improvement: V5 tool outcomes now feed the durable feedback ledger

- Problem: the new reinforcement ledger had no production consumer; tool
  success/failure signals from the live V5 executor were still discarded.
- Fix: wrapped the V5 tool execution boundary so every real tool call records
  `+1` on success or `-1` on failure. Ledger construction and SQLite writes run
  via `asyncio.to_thread`, and feedback failures remain isolated from tool
  results and exception semantics.
- Files: `orchestrators/v5/tools.py`, `tests/v5/test_v5_tool_feedback.py`.
- Verification: V5 feedback, direct model/tool loop, tool gates, parallel
  control, active-loop, and nerve tests passed `105 passed` in `21.63s`; nine
  pre-existing asyncio deprecation warnings remain. Modified modules compiled
  and passed diff checks.
- Remaining risk: the aggregate feedback is not yet used to change routing or
  model weights; quality-gated promotion/rollback is still required before
  adaptive behavior is enabled.

## Verified improvement: kernel semantic indexing is connected to canonical RAG

- Problem: the kernel exposed `NexusSemanticIndexer` as an initialization-only
  stub while GUI/V5 repository context used `NexusAtlasRAG` directly. Kernel
  callers therefore received no indexing or retrieval capability and the
  project had two disconnected concepts of repository intelligence.
- Fix: replaced the stub with a small facade over durable RAG indexing,
  structured hybrid search, text retrieval, and status reporting. No second
  index format was introduced.
- Files: `indexer/__init__.py`, `tests/test_semantic_indexer.py`.
- Verification: semantic-indexer, RAG concurrency, kernel, context, and V5
  memory-context tests passed `39 passed` in `2.19s`; the facade compiled and
  passed diff checks.
- Remaining risk: `NexusAtlasRAG` remains a process singleton for the active
  workspace. Multi-workspace server deployments need a keyed registry or
  explicit lifecycle management before sharing one process across roots.

## Verified improvement: RAG state is isolated per persistent vault

- Problem: the canonical RAG class inherited a process-global singleton while
  callers supplied different workspace/vault paths. A workspace switch could
  reuse stale documents and return results from the previous project.
- Fix: changed ownership to a thread-safe keyed instance map using the resolved
  vault path, while retaining `_reset_instance()` compatibility for tests and
  maintenance. Each vault keeps its own durable index/cache/lock path.
- Files: `rag/engine.py`, `tests/test_semantic_indexer.py`.
- Verification: semantic-indexer, RAG concurrency, kernel, context, OAuth, and
  provider-router tests passed `47 passed` in `2.03s`; modified modules compiled
  and passed diff checks.
- Remaining risk: callers that intentionally rely on one global default vault
  remain compatible; explicit lifecycle cleanup is still needed for processes
  that create many short-lived workspace vaults.

## Verified improvement: V5 exception observations are redacted and bounded

- Problem: V5 core and parallel execution paths interpolated raw exception
  text into tool results. Provider credentials or filesystem secrets embedded
  in an exception could therefore reach model context despite redaction in the
  lower-level executor.
- Fix: route core and parallel exception/result errors through the shared
  secret redactor and cap them at 4,000 characters before they become model
  observations.
- Files: `orchestrators/v5/core.py`, `orchestrators/v5/parallel.py`,
  `tests/v5/test_v5_error_redaction.py`.
- Verification: V5 redaction, direct-loop, tool-gate, parallel-control,
  active-loop, run-control, environment-redaction, and provider-redaction tests
  passed `135 passed` in `15.14s`; nine pre-existing asyncio deprecation
  warnings remain. Modified modules compiled and passed diff checks.
- Remaining risk: pattern-based redaction cannot recognize every
  organization-specific credential format; configurable detectors remain a
  future security improvement.

## Verified improvement: background failure events are redacted and bounded

- Problem: long-running V5 background retry/failure events persisted raw
  exception text, allowing credentials or sensitive paths in worker failures
  to reach durable event streams and UI consumers.
- Fix: route retry and terminal failure diagnostics through the shared secret
  redactor and bound them to the existing event-size limits.
- Files: `orchestrators/v5/background_runner.py`,
  `tests/v5/test_v5_background_error_redaction.py`.
- Verification: background redaction, durable background runner, run-control,
  checkpoint resume, provider-redaction, and environment-redaction tests passed
  `56 passed` in `14.93s`; the runner compiled and passed diff checks.
- Remaining risk: other non-V5 background adapters need the same audit if they
  emit raw third-party exception payloads.

## Verified improvement: scheduled-task failure records are redacted and bounded

- Problem: V5 cron execution passed raw exceptions into `CronLifecycle` failure
  records, including one path where callers could bypass the scheduler’s
  normal sanitization.
- Fix: sanitize and cap errors at scheduler call sites and again inside
  `_cron_record_result`, covering explicit errors and future exceptions from
  bridged futures.
- Files: `orchestrators/v5/cron.py`,
  `tests/v5/test_v5_cron_error_redaction.py`.
- Verification: cron, background runner, queue store/driver/identity, and
  provider/environment redaction tests passed `55 passed` in `5.35s`; the cron
  module compiled and passed diff checks.
- Remaining risk: legacy scheduler implementations outside V5 need an
  equivalent boundary audit before their errors are considered safe.

## Verified improvement: lifecycle persistence failures are observable

- Problem: lifecycle JSON persistence described every read/write failure as a
  silent no-op. Supervisors continued in memory, but callers could not tell a
  clean missing state from corrupt or unwritable durable state.
- Fix: added normalized state-root-safe keys, atomic fsync-backed writes, and a
  `persistence_status()` diagnostic contract recording the last operation,
  availability, bounded error, and timestamp. Existing `load_state`/`save_state`
  behavior remains nonfatal; save/clear now also return a compatibility-safe
  boolean outcome.
- Files: `lifecycle/persistence.py`, `lifecycle/__init__.py`,
  `tests/test_lifecycle_persistence_contract.py`.
- Verification: lifecycle, kernel, run-context, control-store, checkpoint,
  cron, and background persistence tests passed `53 passed` in `21.91s`; modules
  compiled and passed diff checks.
- Remaining risk: supervisors do not yet surface this status in a dedicated API
  health endpoint; operators currently access it through the lifecycle module.

## Verified improvement: supervisor diagnostics expose durable-state health

- Problem: lifecycle persistence could now report failures internally, but
  `ComponentSupervisor.get_stats()` exposed only in-memory stage counts. A
  healthy-looking supervisor could therefore be losing every state transition
  on disk without an operator-visible signal.
- Fix: added a bounded `persistence` projection to supervisor stats, covering
  available, disabled, last operation, error, and timestamp while preserving
  nonfatal lifecycle behavior.
- Files: `lifecycle/supervisor.py`,
  `tests/test_lifecycle_supervisor_persistence_health.py`.
- Verification: lifecycle, persistence, kernel, run-context, control-store,
  and checkpoint tests passed `55 passed` in `18.05s`; modified modules
  compiled and passed diff checks.
- Remaining risk: the server/UI health surfaces do not yet expose this
  lifecycle-specific projection; API wiring is a follow-up observability task.

## Verified improvement: lifecycle persistence health is visible through `/api/health`

- Problem: the supervisor exposed durable-state health internally, but the
  public server health contract did not include it. Operators and UI clients
  could therefore see HTTP success while missing a persistence degradation.
- Fix: added a bounded `lifecycle_persistence` projection to `/api/health`,
  with explicit availability, operation, error, and timestamp fields. The
  existing HTTP 200 and `status: ok` compatibility contract remains unchanged.
  Unexpected health-projection failures are redacted and do not crash the
  endpoint.
- Files: `server/__init__.py`, `tests/test_server_health_lifecycle.py`.
- Verification: focused server/lifecycle health tests passed `4 passed` in
  `0.40s`; modified modules compiled and passed diff checks.
- Remaining risk: health remains HTTP-healthy for compatibility even when the
  durability field reports degraded state; clients must inspect the projection.

## Verified improvement: Hive blackboard version checks are process-safe

- Problem: `HiveStateStore.put_blackboard()` used an in-process lock and a
  deferred SQLite transaction. Separate workers could both read the same
  version before either write, weakening optimistic concurrency and producing
  lost updates or generic lock errors instead of a domain conflict.
- Fix: begin an SQLite `IMMEDIATE` transaction before reading the current
  version, so the read/check/write sequence is serialized across processes
  while preserving `HiveStateConflict` semantics.
- Files: `hive/state.py`, `tests/test_hive_state.py`.
- Verification: Hive state and V5 Hive lifecycle tests passed `17 passed` in
  `2.25s`; modified modules compiled and passed diff checks.
- Remaining risk: artifact manifest updates still use last-writer-wins
  semantics; they need a separate conflict contract if concurrent artifact
  ownership becomes user-visible.

## Verified improvement: Hive artifact registration rejects symlink escapes

- Problem: artifact containment used lexical absolute paths. A symlink under
  the Hive root could therefore resolve to an external file and bypass the
  intended artifact trust boundary.
- Fix: compare real paths for both the Hive root and candidate artifact before
  registration, while retaining the normalized project path in the manifest.
- Files: `hive/state.py`, `tests/test_hive_state.py`.
- Verification: Hive state and V5 Hive lifecycle tests passed `17 passed, 1
  skipped` in `0.77s`; the skip is only for platforms that disallow symlink
  creation. Modified modules compiled and passed diff checks.
- Remaining risk: artifact contents are fingerprinted at registration and
  reconciliation time; consumers must still avoid treating a later path
  replacement as trusted without reconciling it.

## Verified improvement: Hive failure observations and diagnostics are redacted

- Problem: core Hive sub-agent failures, tool exceptions, retry diagnostics,
  and consolidation warnings could carry provider credentials or sensitive
  paths into events, effect-ledger state, logs, or model observations.
- Fix: added a bounded `_safe_text()` boundary using Nexus's shared secret
  redactor and applied it to sub-agent failure events, tool-failure
  observations, effect failures, retry/dependency diagnostics, and
  consolidation warnings.
- Files: `hive/engine.py`, `tests/test_hive_error_redaction.py`.
- Verification: focused Hive error/state/retry/dependency/event tests passed
  `17 passed, 1 skipped` in `1.65s`; the engine and regression test compiled
  and passed diff checks.
- Remaining risk: successful tool output and tool parameters can still contain
  arbitrary sensitive content; a broader output/event redaction policy should
  be evaluated without corrupting legitimate research results.

## Verified improvement: successful Hive telemetry and checkpoints are redacted

- Problem: successful tool parameters/results were copied raw into progress
  events, transcripts, checkpoints, and LLM consolidation prompts. The earlier
  exception-only boundary did not protect credentials returned by a successful
  tool or supplied as a parameter.
- Fix: added recursive bounded redaction for JSON-like telemetry values and
  applied it to tool parameters, result events, tool observations, checkpoints,
  deterministic consolidation, and LLM consolidation input.
- Files: `hive/engine.py`, `tests/test_hive_error_redaction.py`.
- Verification: focused Hive error/state/retry/dependency/event tests passed
  `18 passed, 1 skipped` in `1.65s`; modified modules compiled and passed diff
  checks.
- Remaining risk: user task text and external files may contain intentional
  sensitive content; broad redaction can only cover recognized credential
  patterns and should not be treated as a complete data-classification system.

## Verified improvement: empty Hive results cannot become successful work

- Problem: `SubAgent.run()` marked an agent successful whenever the model call
  returned without raising, including an empty or whitespace-only response.
  This created a false terminal state and could make parent consolidation lose
  an agent's contribution without an explicit failure.
- Fix: enforce a terminal-result invariant after the model/tool loop; empty
  results raise a bounded lifecycle failure and are persisted/emitted as
  `failed`.
- Files: `hive/engine.py`, `tests/test_hive_error_redaction.py`.
- Verification: focused Hive state, retry, dependency, consensus, event, and
  redaction tests passed `22 passed, 1 skipped` in `1.82s`; modified modules
  compiled and passed diff checks.
- Remaining risk: a non-empty but malformed or prematurely truncated response
  still needs semantic validation at the caller/model-contract layer.

## Verified improvement: Hive tool-budget exhaustion has an explicit failure state

- Problem: when the final wrap-up call failed, or returned another tool call
  after the step budget was exhausted, `SubAgent` could still mark the run
  successful with no final answer. Parent consolidation then received an
  incomplete terminal result.
- Fix: wrap-up failures now become explicit sub-agent failures, and a wrap-up
  that still requests a tool is rejected as budget exhaustion without a final
  answer.
- Files: `hive/engine.py`, `tests/test_hive_error_redaction.py`.
- Verification: focused Hive redaction/state/retry/dependency/consensus/
  control/effect/event tests passed `31 passed, 1 skipped` in `2.40s`; modified
  modules compiled and passed diff checks.
- Remaining risk: syntactically valid but semantically incomplete final text
  still requires domain-level validation by the parent task.

## Verified improvement: Hive consolidation fails closed when every worker fails

- Problem: parent consolidation could invoke an LLM even when no worker had a
  successful result. A model-generated response could then look like completed
  work despite total worker failure.
- Fix: count non-empty successful worker results before consolidation; when the
  count is zero, return an explicit `HIVE FAILED` result with deterministic
  worker diagnostics and skip the LLM consolidation call.
- Files: `hive/engine.py`, `tests/test_hive_consensus.py`.
- Verification: focused Hive consensus/state/retry/dependency/control/effect/
  event/redaction tests passed `32 passed, 1 skipped` in `5.04s`; modified
  modules compiled and passed diff checks.
- Remaining risk: partial-success consolidation remains intentionally allowed;
  callers requiring complete coverage must use quorum or an equivalent policy.

- Additional regression verification: the complete Hive-named test inventory
  passed `58 passed, 1 skipped` in `4.71s` after the consolidation change.

## Verified improvement: V5 no longer reports failed Hive consolidation as success

- Problem: the engine now returns an explicit `HIVE FAILED` result when all
  workers fail, but V5 treated any non-empty consolidation text as success,
  emitted `hive.done`, and injected the failure report into the main context.
- Fix: V5 recognizes failed/quorum-rejected consolidation markers, marks the
  group and current turn failed, emits no success path, and refuses context
  injection.
- Files: `orchestrators/v5/hive.py`, `tests/test_redesign_hive.py`.
- Verification: V5 Hive, engine, consensus, state, retry, dependency, control,
  effect, and event tests passed `46 passed, 1 skipped` in `6.74s`; modified
  modules compiled and passed diff checks.
- Remaining risk: callers that use custom failure wording outside the explicit
  engine markers still need a structured consolidation result contract.

## Verified improvement: V5 preserves partial Hive worker state

- Problem: after any non-empty consolidation, V5 marked every persisted worker
  as `succeeded`, erasing failed/cancelled worker states and making recovery,
  progress, and audit views falsely optimistic.
- Fix: completion preserves terminal worker failures/cancellations, synchronizes
  live engine statuses before completion, and records `partial` plus failed
  worker IDs in persisted state and `hive.done` event payloads.
- Files: `orchestrators/v5/hive.py`, `tests/test_redesign_hive.py`.
- Verification: V5 Hive plus engine consensus/state/retry/dependency/control/
  effect/event tests passed `47 passed, 1 skipped` in `3.38s`; modified modules
  compiled and passed diff checks.
- Remaining risk: the public server manifest still models aggregate Hive state
  from live engine agents; V5’s persisted partial metadata should be surfaced
  consistently there in a later API/UI pass.

## Verified improvement: server Hive listings expose partial failure explicitly

- Problem: `/api/hives` derived only a coarse aggregate status from live agents
  and did not expose whether a terminal Hive contained both successful and
  failed workers. Consumers could not distinguish complete failure from useful
  but degraded partial work.
- Fix: added a bounded `partial` field to each Hive listing and persisted
  manifest projection; mixed success/failure is marked explicitly while the
  aggregate remains `failed` for conservative compatibility.
- Files: `server/__init__.py`, `tests/test_server_hive_status_projection.py`.
- Verification: server Hive status, persistence, and multi-agent bridge tests
  passed `11 passed` in `0.63s`; modified modules compiled and passed diff
  checks.
- Remaining risk: create/resume responses are launch acknowledgements; clients
  must refresh `/api/hives` to observe terminal partial state.

## Verified improvement: GUI Hive status matches backend lifecycle states

- Problem: the React Hive panel expected `completed`, while the backend emits
  `success`/`succeeded`; it also hid all terminal hives when no work was active.
  The settings dashboard therefore undercounted completed work and could show
  no evidence of failed or partial execution.
- Fix: added shared status normalization for success/failure/cancelled/partial
  states, retained terminal Hive rows, normalized agent counters, and exposed
  partial counts in the Hive manager statistics.
- Files: `gui/src/lib/api.ts`, `gui/src/components/HivePanel.tsx`,
  `gui/src/components/settings/HiveManager.tsx`.
- Verification: `npm.cmd run build` passed (`tsc` plus Vite production build;
  1,576 modules transformed). Vite reported only the existing >500 kB chunk
  advisory.
- Remaining risk: GUI production bundle still has a large main chunk; this is a
  performance optimization backlog item, not a correctness failure.

## Verified improvement: GUI plugin ZIP installation is traversal-safe

- Problem: GitHub fallback plugin installation used `ZipFile.extractall()` on
  downloaded content without validating member paths. A malicious or
  compromised archive could write outside the temporary extraction directory,
  and archive symlinks could create a second escape path.
- Fix: added `_safe_extract_zip()` with absolute-path, normalized containment,
  and symlink rejection checks; extraction now copies only validated members.
- Files: `gui/api.py`, `tests/test_gui_archive_security.py`.
- Verification: archive security tests passed `4 passed` in `0.54s`; modified
  modules compiled and passed diff checks.
- Remaining risk: unverified plugin source remains executable code by design;
  the existing plugin trust/opt-in gate must remain enabled for installation.

## Verified improvement: plugin reinstall is staged and failure-safe

- Problem: forced remote plugin installation deleted the existing plugin before
  cloning or archive fallback succeeded. Network, Git, or archive failures
  could therefore destroy a working plugin and leave partial temporary files.
- Fix: clone/extract into a unique staging directory, generate/validate the
  manifest there, then promote it into place. Existing plugins are moved to a
  temporary backup only during promotion and are restored on failure; stale
  staging/backup artifacts are cleaned up.
- Files: `gui/api.py`, `tests/test_gui_archive_security.py`.
- Verification: archive and plugin lifecycle security tests passed `6 passed`
  in `0.53s`; modified modules compiled and passed diff checks.
- Remaining risk: promotion cannot make external plugin code trusted; the
  explicit unverified-install opt-in remains mandatory.

## Verified improvement: session artifact archives reject symlink escapes

- Problem: `/api/session-files.zip` checked artifact paths lexically and used
  `os.path.isfile`, so a symlink inside a session artifact directory could
  cause an external file to be included in a downloadable archive.
- Fix: artifact candidates now require a non-symlink, real in-root file before
  inclusion; root and candidate containment use resolved paths.
- Files: `gui/api.py`, `tests/test_gui_archive_security.py`.
- Verification: archive/plugin security tests passed `6 passed, 1 skipped` in
  `0.51s`; modified modules compiled and passed diff checks.
- Remaining risk: archive creation still depends on upstream source-library
  paths being validated by `safe_workspace_read_path`, which is now enforced.

## Verified improvement: context compaction preserves critical older facts

- Problem: shared compaction summarized older messages using only their first
  200 characters. Errors, decisions, changed-file notes, constraints, and
  unresolved work near the end of a long message could silently disappear
  while the current turn continued.
- Fix: compaction now adds bounded, de-duplicated critical-line excerpts to the
  summary and centers truncation around the matching critical term. Existing
  token budgeting and tool-call/result atomicity remain unchanged.
- Files: `context/__init__.py`, `tests/test_redesign_context.py`.
- Verification: complete context-named test inventory passed `58 passed` in
  `0.77s`; modified modules compiled and passed diff checks.
- Remaining risk: keyword-based preservation cannot replace semantic memory
  selection; future model-aware summaries must retain this deterministic
  fallback and test its token cost.

## Verified improvement: V5 code-action file writes are async-safe and contained

- Problem: `_execute_code_action()` performed directory creation and file writes
  directly inside an async tool path, blocking the event loop during slow
  filesystem operations. It also interpolated the current turn ID into a
  filename without sanitization, allowing path separators to escape the temp
  directory.
- Fix: moved code-action file creation into `asyncio.to_thread`, sanitized the
  turn-derived filename, enforced resolved containment, and redacted bounded
  write/execution errors.
- Files: `orchestrators/v5/tools.py`, `tests/v5/test_v5_tool_gates.py`.
- Verification: V5 tool-gate, direct-loop, and redaction tests passed `63
  passed` in `7.70s`; modified modules compiled and passed diff checks.
- Remaining risk: the sandbox execution itself remains provider/platform
  dependent; command lifecycle and cancellation are covered separately by the
  sandbox/control tests.

## Verified improvement: workspace storage cleanup no longer blocks the server loop

- Problem: async `/api/workspace/storage/clear` directly enumerated and deleted
  session, cache, temp, and index files. Large cleanup directories could stall
  all concurrent API requests on the event loop.
- Fix: moved the bounded, server-owned cleanup operation into
  `_clear_workspace_storage_sync()` and invoked it via `asyncio.to_thread`,
  preserving the protected session index and existing response semantics.
- Files: `server/__init__.py`, `tests/test_server_storage_async_boundary.py`.
- Verification: storage, file async-boundary, and health tests passed `4 passed`
  in `1.35s`; modified modules compiled and passed diff checks.
- Remaining risk: other explicitly user-triggered local OS operations (such as
  opening a path) remain candidates for the next async-boundary pass.

## Verified improvement: saved-model discovery is offloaded from the API loop

- Problem: async saved-model endpoints synchronously read provider YAML and
  profile storage on every GUI model-picker request, allowing slow disk or
  profile operations to delay unrelated requests.
- Fix: isolated the existing read-only response builder in
  `_list_saved_models_sync()` and routed the async endpoint through
  `asyncio.to_thread` without changing its response contract.
- Files: `server/__init__.py`, `tests/test_server_saved_models_async_boundary.py`.
- Verification: saved-model, storage-boundary, and public health tests passed
  `3 passed, 1 warning` in `1.07s`; the warning is the existing Starlette/httpx
  deprecation notice. Modified modules compiled and passed diff checks.
- Remaining risk: provider profile loading itself may still perform multiple
  disk reads; it is now isolated from the event loop but remains a candidate
  for caching/latency measurement.

## Verified improvement: local file-manager launch is off the API loop

- Problem: async `/api/open` launched the platform file manager directly from
  the request handler, so OS process/file-manager startup could block other
  requests.
- Fix: isolated platform-specific launching in `_open_path_sync()` and routed
  it through `asyncio.to_thread`, preserving the existing workspace
  containment and response behavior.
- Files: `server/__init__.py`, `tests/test_server_open_async_boundary.py`.
- Verification: open-path boundary test passed `1 passed` in `0.36s`; saved
  model and storage boundary regressions passed `2 passed` in `0.39s`; the
  modified server and tests compiled and passed diff checks.
- Remaining risk: platform launchers are intentionally fire-and-forget; a
  later observability pass can report launcher failures without blocking the
  API request.

## Verified improvement: voice startup and Hive feedback writes are async-safe

- Problem: async voice startup performed log reset, stray-process cleanup,
  log-handle creation, and `Popen` directly in the API handler. V5 Hive
  feedback also wrote its session JSON directly from an async path.
- Fix: grouped voice preparation/launch in `_start_voice_process_sync()` and
  invoked it with `asyncio.to_thread`; Hive feedback serialization now runs in
  a worker thread while retaining its defensive failure handling.
- Files: `server/__init__.py`, `orchestrators/v5/hive.py`,
  `tests/test_server_voice_async_boundary.py`.
- Verification: voice, training lifecycle, and open-path tests passed `6
  passed` in `0.52s`; the broader Hive-related inventory passed `93 passed,
  2 skipped` in `7.43s`; modified modules compiled and passed diff checks.
- Remaining risk: the training endpoint still uses a synchronous process-state
  lock around launch coordination and should be revisited with an async-safe
  lock design after its cross-process semantics are mapped.

## Verified improvement: GUI chat metadata reads are off the event loop

- Problem: the GUI `/api/chat` handler synchronously opened and parsed the
  session metadata file while preparing a turn, creating avoidable latency for
  concurrent streaming requests.
- Fix: added `_session_title_needs_write_sync()` and routed the metadata read
  through `asyncio.to_thread`; title persistence was already offloaded.
- Files: `gui/api.py`, `tests/test_gui_chat_async_boundary.py`.
- Verification: GUI chat, server async-boundary, and voice-boundary tests
  passed `11 passed` in `1.42s`; the modified GUI module compiled and all
  touched files passed diff checks.
- Remaining risk: the surrounding GUI chat path intentionally owns a worker
  thread for synchronous loop streaming; a separate throughput audit should
  measure queue backpressure and cancellation under concurrent sessions.

## Verified improvement: training launch coordination is off the API loop

- Problem: `/api/engine/train` acquired a blocking thread lock, read durable
  status, launched `Popen`, and wrote the start record directly in an async
  handler. A concurrent request could therefore stall the event loop while
  waiting for launch coordination or filesystem locks.
- Fix: moved the complete check-lock-launch-status transaction into
  `_start_training_sync()` and invoke it through `asyncio.to_thread`, keeping
  the in-process and cross-process lock ordering intact.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: training lifecycle and server async-boundary tests passed
  `14 passed` in `1.55s`; modified modules compiled and passed diff checks.
- Remaining risk: training status polling remains synchronous by design on its
  normal lightweight path; if status files become large, it should be moved
  behind the same bounded worker pattern.

## Verified improvement: voice startup failure-tail reads are async-safe

- Problem: after a child exited immediately, `/api/voice/start` synchronously
  opened and read the voice log while constructing the error response.
- Fix: reused the bounded `_tail_voice_log()` helper through
  `asyncio.to_thread`, so both successful startup and failure diagnostics avoid
  direct filesystem I/O in the async route.
- Files: `server/__init__.py`.
- Verification: combined voice, training, server-boundary, and GUI-boundary
  tests passed `16 passed` in `1.78s`; modified modules compiled and passed
  diff checks.
- Remaining risk: voice status endpoints still expose the latest bounded log
  snapshot synchronously; they are read-only and bounded but should be included
  in a future latency measurement pass.

## Async-boundary audit checkpoint: audited routes have no unwrapped local I/O

- Scope: `server/__init__.py`, `gui/api.py`, and `orchestrators/v5/hive.py`.
- Evidence: an AST scan for direct `open`, directory mutation, file mutation,
  `Popen`, and `startfile` calls inside async functions found no unwrapped
  route operations. The sole remaining match is the synchronous nested Hive
  feedback writer, which is explicitly submitted via `asyncio.to_thread`.
- Next work: measure bounded status/log read latency and then prioritize the
  next reliability backlog item, with training status polling and GUI chat
  stream backpressure as the current candidates.
## Verified improvement: GUI chat streams are bounded and cancel producers

- Problem: GUI chat used an unbounded `queue.Queue` for model chunks and live
  work events. If a client disconnected or consumed slowly, producer threads
  could retain unbounded output and continue running without a cancellation
  signal.
- Fix: added `_CancellableStreamQueue` with a bounded capacity and stop-event
  aware puts; stream cleanup now signals `request_abort(...,
  "client_disconnect")` for incomplete runs and joins the producer briefly.
- Files: `gui/api.py`, `tests/test_gui_stream_backpressure.py`.
- Verification: bounded-queue regression passed `1 passed` in `0.67s`; GUI
  work-event tests passed `36 passed` in `2.44s`; GUI chat boundary test passed
  `1 passed` in `0.12s`; modified modules compiled and passed diff checks.
- Remaining risk: the legacy server chat route has a separate async producer
  architecture and should receive an equivalent disconnect/cancellation audit.
  Its existing parity test was separately observed to exceed 20 seconds and
  was stopped for isolation; this is recorded as a test-environment follow-up,
  not treated as a passing result.
## Verified improvement: server chat disconnects abort the active run

- Problem: the server chat route bounded its queues and cancelled the async
  producer task, but a client disconnect did not explicitly signal the
  underlying Nexus loop. A provider/tool operation could therefore continue
  after the stream had gone away.
- Fix: incomplete stream cleanup now requests `client_disconnect` cancellation
  before cancelling and gathering the producer task; the existing terminal
  persistence and sink restoration remain in the same cleanup path.
- Files: `server/__init__.py`, `tests/test_server_async_boundaries.py`.
- Verification: server async-boundary, GUI backpressure, and work-event tests
  passed `48 passed` in `5.69s`; modified modules compiled and passed diff
  checks.
- Remaining risk: a provider that ignores Nexus cancellation may still outlive
  the request; provider subprocess/network cancellation needs a separate
  integration test with a deliberately stuck stream.
## Verified improvement: server stream disconnect reaches the underlying run

- Problem: the server chat route cancelled its pump task when the response
  closed, but there was no direct proof that a still-running provider/tool run
  received cancellation on client disconnect.
- Fix: incomplete server stream cleanup now calls the loop's
  `request_abort(turn_id, "client_disconnect")` before cancelling the pump.
- Files: `server/__init__.py`, `tests/test_server_stream_disconnect.py`.
- Verification: an integration-style async-generator test used a deliberately
  stalled stream and observed the abort reason; the combined server/GUI stream
  regression set passed `49 passed` in `5.33s`, with compilation and diff
  checks clean.
- Remaining risk: cancellation remains cooperative; providers or subprocesses
  that ignore the loop control signal need provider-specific termination tests.
## Verified improvement: primary HTTP stream adapters close response bodies

- Problem: `CommandCodeProvider` and `OpenAIProvider` used `requests` with
  `stream=True` but did not close the response on normal completion, early
  `[DONE]`, deadline return, parse failure, or generator cancellation.
- Fix: both adapters now retain the response and close it in a defensive
  `finally` block, without changing emitted content or tool-call envelopes.
- Files: `providers/commandcode.py`, `providers/openai.py`,
  `tests/test_commandcode_stream_cleanup.py`,
  `tests/test_openai_stream_cleanup.py`.
- Verification: provider stream cleanup and router-stream regressions passed
  `12 passed` in `0.26s`; modified providers compiled and passed diff checks.
- Remaining risk: the same duplicated pattern exists in additional provider
  adapters (`deepseek`, `anthropic`, `groq`, and others); inventory is retained
  for the next provider reliability wave rather than assuming these two fixes
  cover every route.
## Verified improvement: DeepSeek and Anthropic stream responses are closed

- Problem: the primary cloud adapters (`OpenAI`, `CommandCode`, `DeepSeek`,
  and `Anthropic`) all used streamed `requests` responses without guaranteed
  closure on generator exit, creating connection-pool/file-descriptor leak
  risk during long-running sessions.
- Fix: added defensive response `finally` cleanup to all four adapters,
  including early status/deadline returns and consumer cancellation.
- Files: `providers/openai.py`, `providers/commandcode.py`,
  `providers/deepseek.py`, `providers/anthropic.py`,
  `tests/test_openai_stream_cleanup.py`,
  `tests/test_commandcode_stream_cleanup.py`.
- Verification: adapter cleanup and router-stream tests passed `14 passed` in
  `0.27s`; all modified providers compiled and passed diff checks.
- Remaining risk: additional streamed adapters remain in the inventory and
  need the same treatment; this wave intentionally started with the highest
  use cloud routes to keep changes reviewable.
## Verified improvement: five OpenAI-compatible adapters close streams

- Problem: `Groq`, `xAI`, `Together`, `Fireworks`, and `Mistral` repeated the
  same streamed-response lifecycle without closing the `requests` response.
  The initial patch also exposed the risk of editing duplicated adapters
  mechanically, so each stream path was compiled and exercised individually.
- Fix: initialized a stream-local response, added defensive `finally` close
  handling, and added module loggers for cleanup diagnostics in all five.
- Files: `providers/groq.py`, `providers/xai.py`, `providers/together.py`,
  `providers/fireworks.py`, `providers/mistral.py`,
  `tests/test_openai_stream_cleanup.py`.
- Verification: provider cleanup and router-stream tests passed `19 passed` in
  `0.28s`; all nine touched provider modules compiled and passed diff checks.
- Remaining risk: further streamed adapters (`google_gemini`, `ollama`, local
  servers, and others) remain in the inventory and may have provider-specific
  response/client lifecycle behavior.
## Verified improvement: Gemini and Ollama close local/cloud streams

- Problem: both adapters used `stream=True` response objects without closing
  them when the stream ended or the consumer stopped early.
- Fix: added stream-local response ownership and defensive `finally` cleanup,
  with module loggers for cleanup diagnostics.
- Files: `providers/google_gemini.py`, `providers/ollama.py`,
  `tests/test_openai_stream_cleanup.py`.
- Verification: the expanded provider cleanup tests passed `11 passed` in
  `0.22s`; both modules compiled and passed diff checks.
- Remaining risk: LM Studio, Universal, Qwen, Perplexity, SambaNova, Azure,
  and OpenRouter still need provider-specific review before the full streamed
  adapter inventory is closed.
## Verified improvement: OpenRouter closes each fallback attempt

- Problem: OpenRouter can try several models in one streamed request, but a
  failed, timed-out, or early-success response was not explicitly closed
  before retry/return. This could accumulate pooled connections during health
  degradation.
- Fix: each fallback iteration now owns a response and closes it in `finally`,
  including all retry and terminal-return paths.
- Files: `providers/openrouter.py`.
- Verification: OpenRouter/router-stream and provider cleanup tests passed
  `20 passed` in `0.26s`; the adapter compiled and passed diff checks.
- Remaining risk: the remaining adapters with duplicated response loops still
  need targeted cleanup and tests; no blanket completion claim is made.
## Verified improvement: remaining OpenAI-compatible HTTP streams close bodies

- Problem: LM Studio, Universal, Qwen, Perplexity, SambaNova, and Azure
  OpenAI had the same unclosed `stream=True` response lifecycle. Azure also
  uses a deployment-specific URL and chunk-size argument, so it was tested
  separately through the shared adapter regression.
- Fix: each stream function now initializes a response local and closes it in
  a defensive `finally`; missing module loggers were added where needed.
- Files: `providers/lm_studio.py`, `providers/universal.py`,
  `providers/qwen.py`, `providers/perplexity.py`, `providers/sambanova.py`,
  `providers/azure_openai.py`, `tests/test_openai_stream_cleanup.py`.
- Verification: the expanded adapter cleanup tests passed `17 passed` in
  `0.22s`; all six providers compiled and passed diff checks.
- Remaining risk: local `llama_cpp` uses a native iterator rather than an HTTP
  response, and should receive a separate iterator-close/cancellation audit.
## Verified improvement: final provider stream lifecycles are closed

- Problem: Cohere and NVIDIA NIM still left streamed HTTP response bodies
  open, while llama.cpp's native iterator was not explicitly closed when a
  consumer stopped early.
- Fix: added defensive response cleanup to Cohere/NVIDIA and iterator `.close()`
  cleanup to llama.cpp when supported.
- Files: `providers/cohere.py`, `providers/nvidia.py`,
  `providers/llama_cpp.py`, `tests/test_openai_stream_cleanup.py`,
  `tests/test_llama_cpp_stream_cleanup.py`.
- Verification: the complete provider cleanup subset passed `20 passed` in
  `0.25s`; modified providers compiled and passed diff checks. A static scan
  now reports no remaining HTTP `stream=True` adapter without response-close
  handling; llama.cpp is the intentional native-iterator exception.
- Remaining risk: iterator close support depends on the installed llama.cpp
  binding; the cleanup is capability-checked and remains safe when absent.
## Verified improvement: Hive cancellation is published before local waits

- Problem: `cancel_hive()` cancelled and awaited local worker tasks before
  writing the durable cancelled control file. If a worker in another server
  process was inside a long model/tool call, remote cancellation could be
  delayed until local cleanup completed.
- Fix: persist the cancelled control decision and release pause waiters before
  cancelling/awaiting local tasks. Local task cleanup remains awaited and
  bounded by the worker's cooperative cancellation behavior.
- Files: `hive/engine.py`, `tests/test_hive_control.py`.
- Verification: Hive control/state/retry tests passed `11 passed, 1 skipped` in
  `1.54s`; modified modules compiled and passed diff checks. The new test
  observes the control file as cancelled before `cancel_hive()` returns.
- Remaining risk: workers only observe the durable control at safe boundaries;
  providers/tools that ignore cooperative cancellation still need their own
  termination guarantees.
## Verified improvement: synchronous Hive tools no longer block cancellation

- Problem: `SubAgent._execute_tool()` invoked synchronous registry/callable
  tools directly inside the asyncio event loop. A slow filesystem/process tool
  could stall all Hive workers and prevent pause/cancel control from being
  observed.
- Fix: tool invocation now runs through `asyncio.to_thread`; returned
  awaitables are still awaited on the owning loop, preserving async tool
  behavior while isolating synchronous work.
- Files: `hive/engine.py`, `tests/test_hive_tool_async_boundary.py`.
- Verification: Hive tool-boundary, control, budget, and retry tests passed
  `10 passed` in `1.75s`; modified modules compiled and passed diff checks.
- Remaining risk: a synchronous tool can continue in its worker thread after
  task cancellation because Python cannot forcibly stop arbitrary threads;
  effect-ledger uncertainty handling remains the safety boundary for side
  effects.
## Verified improvement: cancelled Hive side effects fail closed

- Problem: moving synchronous Hive tools to worker threads prevents event-loop
  starvation, but cancellation can detach the awaiting coroutine while the
  side effect is still in flight. Retrying immediately must not execute the
  same effect twice.
- Fix: validated the existing effect-ledger behavior at this boundary: a
  cancelled in-flight effect remains leased as `running`/uncertain, so a later
  claim is refused until reconciliation or lease expiry.
- Files: `tests/test_hive_effects.py` (regression coverage; ledger behavior is
  in `hive/effects.py`).
- Verification: Hive effects, tool-boundary, and control tests passed `11
  passed` in `1.01s`; modified modules compiled and passed diff checks.
- Remaining risk: reconciliation callbacks must be supplied for durable tools
  whose outcome can be queried; otherwise the fail-closed state requires
  operator/provider reconciliation.
## Hive model-call cancellation boundary: cooperative limitation recorded

- Evidence: `SubAgent._llm()` and `_default_llm_call()` already route
  synchronous provider/router calls through `asyncio.to_thread`, while native
  async callables remain directly awaitable. This keeps the event loop
  responsive and allows the agent task to transition to `cancelled`.
- Limitation: Python cannot forcibly stop an arbitrary worker thread after its
  awaiter is cancelled. The underlying provider call may finish later, but its
  detached result is no longer consumed by the cancelled agent task.
- Safety posture: tool side effects are protected by the effect ledger's
  uncertain lease; model calls are read-only from the Hive state perspective.
  Provider-specific request timeouts remain the termination boundary.
- Next work: add provider/router cancellation tests where adapters expose an
  explicit close/cancel handle, without changing the backward-compatible
  `llm_call(messages)` contract.
## Verified improvement: cancelled synchronous model calls cannot complete the agent

- Problem: a synchronous Hive model provider can continue in its worker thread
  after the awaiting asyncio task is cancelled; without an explicit state
  invariant, a late result could be mistaken for successful agent completion.
- Fix/contract: retain the existing `to_thread` bridge and verify that
  cancellation transitions the agent to `cancelled` with no result; late
  provider output is detached and never consumed by that task.
- Files: `tests/test_hive_tool_async_boundary.py` (regression coverage),
  `hive/engine.py` (existing bridge).
- Verification: Hive tool-boundary, effects, and control tests passed `12
  passed` in `1.01s`; modified modules compiled and passed diff checks.
- Remaining risk: forcibly terminating arbitrary provider threads is not safe;
  adapters must expose bounded request timeouts or explicit cancellation
  handles for stronger termination guarantees.

## Verified improvement: Hive restart resume hydrates task checkpoints

- Problem: `SubAgent.restore_checkpoint()` existed but the server restart-resume
  path discarded the saved agent IDs and spawned fresh agents. Persisted
  transcripts, tool-call history, and step counters therefore could not affect
  resumed work.
- Root cause: the API passed only `(task, persona)` pairs to the engine, leaving
  checkpoint identity disconnected from task reconstruction.
- Fix: `resume_hive()` now passes validated saved agent IDs when the active engine
  supports `agent_ids`; `spawn_hive()` restores matching checkpoints, validates
  the task identity, and rebinds the restored agent to the new Hive ID. Older
  engine doubles without that optional parameter remain compatible through
  signature-based capability detection.
- Files: `hive/engine.py`, `server/__init__.py`,
  `tests/test_hive_checkpoint_hydration.py`.
- Verification: Hive persistence, status projection, multi-agent bridge, control,
  dependency, and checkpoint tests passed `20 passed` in `1.45s`.
- Remaining risk: provider execution state and in-flight external side effects
  are intentionally not restored; those require effect-ledger reconciliation and
  provider-specific cancellation/lookup contracts.

## Verified improvement: Hive agent-ID collisions fail closed

- Problem: stable IDs are required for checkpoint hydration, but duplicate IDs
  in a resume manifest or an already-live engine registry could overwrite
  `NexusHiveEngine._agents`, orphaning the first worker and corrupting status
  ownership.
- Fix: `spawn_hive()` now tracks IDs allocated in the current Hive and the live
  registry; collisions receive a fresh generated ID, while the first valid ID
  retains the opportunity to hydrate its matching checkpoint.
- Files: `hive/engine.py`, `tests/test_hive_checkpoint_hydration.py`.
- Verification: checkpoint, budget, control, server Hive persistence, and
  multi-agent bridge tests passed `19 passed` in `1.52s`.
- Remaining risk: a generated replacement cannot hydrate the colliding
  checkpoint by design; this is safer than assigning two workers the same
  durable identity.

## Verified improvement: durable background recovery is Windows-aware

- Problem: restart recovery used `os.kill(pid, 0)` as its only owner-process
  probe. That is a POSIX convention and can be rejected or behave differently
  on Windows, risking reclamation of a healthy background job.
- Fix: `DurableBackgroundStore` now uses `GetExitCodeProcess` with a limited
  query handle on Windows, treats access denial conservatively as alive, and
  retains the signal-zero probe on POSIX. Native-probe failures also fail closed
  rather than reclaiming work immediately.
- Files: `orchestrators/v5/durable_background.py`,
  `tests/v5/test_v5_background_runner.py`.
- Verification: V5 background runner and redaction tests passed `14 passed` in
  `1.77s`; the recovery regression confirms live owners remain running while
  dead owners become interrupted.
- Remaining risk: a reused PID cannot be distinguished without persisting a
  process-start identity; heartbeat and owner-token fencing remain the safety
  boundary for that case.

## Verified improvement: durable background results are persisted safely

- Problem: successful durable jobs were marked `completed` but their return
  value was discarded, while failure text was written to SQLite without the
  runtime secret-redaction contract. This weakened restart inspection and could
  leak credentials into the durable ledger.
- Fix: the runner now captures the factory result across the callback boundary,
  persists a bounded redacted `result_summary`, and redacts bounded failure
  diagnostics before `complete()`/`fail()` writes.
- Files: `orchestrators/v5/background_runner.py`,
  `tests/v5/test_v5_background_runner.py`.
- Verification: V5 background runner and error-redaction tests passed `15
  passed` in `1.78s`, including successful result persistence and secret
  suppression for both success and failure paths.
- Remaining risk: result summaries are intentionally stringified and bounded;
  structured result retrieval is not yet part of the public background-task
  contract.

## Verified improvement: durable queue results are redacted recursively

- Problem: queue failures were redacted, but successful task results were
  serialized directly. Nested provider/tool output could therefore persist
  bearer tokens or API keys in `.nexus_queue.db`.
- Fix: `TaskQueue.complete()` now recursively redacts strings in dictionaries,
  lists, and tuples before JSON serialization, preserving the result shape and
  retaining safe scalar values.
- Files: `queue/store.py`, `tests/test_queue_store.py`.
- Verification: queue store, lease fencing, driver, control-identity, and cron
  tests passed `25 passed` in `2.88s`, including nested result redaction.
- Remaining risk: user prompts and arbitrary task metadata are intentionally
  retained as submitted; only terminal result payloads are changed by this
  fix, and administrative raw database access remains outside the API contract.

## Verified improvement: Hive aggregate work budget

- Problem: Hive concurrency and per-agent step limits bounded parallelism and
  individual loops, but a large Hive could still multiply model/tool calls
  without a mission-wide ceiling.
- Fix: `NexusHiveEngine` now accepts an optional shared aggregate inference-step
  budget. All agents in a Hive consume from the same event-loop-owned counter;
  exhaustion fails the next agent closed instead of allowing more provider or
  tool calls. API-created Hives can configure it with
  `NEXUS_HIVE_MAX_TOTAL_STEPS` (zero preserves unlimited legacy behavior).
- Files: `hive/engine.py`, `server/__init__.py`, `tests/test_hive_budget.py`.
- Verification: Hive budget, retry, checkpoint hydration, and control tests
  passed `13 passed` in `1.97s`; the aggregate-budget test observed exactly two
  model calls for a three-agent Hive with a two-step ceiling.
- Remaining risk: the budget counts inference steps rather than provider token
  cost or tool wall-clock time; those require provider usage telemetry and
  separate execution deadlines.

## Verified improvement: Hive budget configuration fails safely

- Problem: the new API environment setting could raise `ValueError` during
  process-wide Hive-engine initialization when operators supplied malformed
  input, turning a recoverable configuration mistake into an endpoint/startup
  failure.
- Fix: server initialization now parses `NEXUS_HIVE_MAX_TOTAL_STEPS` through a
  bounded helper, logs invalid values, and falls back to zero (unlimited legacy
  behavior) rather than crashing.
- Files: `server/__init__.py`, `tests/test_server_hive_persistence.py`.
- Verification: server Hive persistence/status and Hive budget tests passed
  `13 passed` in `1.17s`, including malformed, negative, and valid values.
- Remaining risk: zero remains an intentional unlimited setting for backward
  compatibility; production deployments should set an explicit positive cap.

## Verified improvement: session memory writes are atomic and merge-safe

- Problem: `MemoryManager._sync_session()` read and rewrote the session JSON
  directly. Concurrent MemoryManager instances could both read the same
  snapshot and lose one turn, while a process crash during truncating write
  could leave a corrupt transcript.
- Fix: session read/merge/append/replace is now protected by a shared writer
  lock and written through an fsynced temporary file followed by `os.replace`.
  Merge failures are observable at debug level without breaking the turn.
- Files: `memory/__init__.py`,
  `tests/test_memory_manager/scripts/test_memory_manager.py`.
- Verification: memory manager, context merge, and session-path security tests
  passed `33 passed` in `0.92s`, including concurrent two-writer merge coverage.
- Remaining risk: the main loop's separate `_write_session_bus` writer should
  eventually share this same persistence primitive for full cross-component
  serialization.

## Verified improvement: all primary session writers share one durability boundary

- Problem: MemoryManager and the V5 loop each implemented their own session
  lock/replacement protocol. Their locks could not coordinate with each other,
  so cross-component concurrent writes still had a last-writer-wins window.
- Fix: added `nexus/session_store.py` with the shared process/interprocess
  mutex and atomic JSON writer. MemoryManager and V5 `_write_session_bus()`
  now use the same read/merge/write boundary; the legacy V5 lock helper remains
  as a compatibility adapter.
- Files: `nexus/session_store.py`, `memory/__init__.py`,
  `orchestrators/v5/core.py`, and the existing session regressions.
- Verification: memory manager, V5 session-bus, direct model/tool-loop, and
  session-path security tests passed `86 passed` in `12.82s`.
- Remaining risk: other legacy writers outside these two primary paths should
  be migrated to `nexus.session_store` as they are encountered.

## Parallel specialist findings: gateway, provider, and context hardening

### Gateway polling error redaction

- Problem: `BasePlatformAdapter._guard_poll()` sanitized `last_error` but
  logged the raw third-party exception, allowing credentials in polling logs.
- Fix: the shared polling path now logs the redacted error; `SendResult` also
  normalizes adapter error text at the public boundary.
- Files: `gateway/base.py`, `tests/test_gateway_runtime.py`.
- Verification: specialist gateway suite passed `19 passed` in `6.28s`; syntax
  and diff checks passed.
- Remaining risk: platform-specific logging outside the shared polling path
  still needs a complete gateway-wide audit.

### Provider unsupported-kwargs recovery

- Problem: router recovery for unsupported provider kwargs was unreachable:
  `call_with_reliability()` converted the inner `TypeError` into
  `ProviderCallError` before the outer handler could retry safely.
- Fix: provider signatures are inspected before reliability wrapping; only
  unsupported kwargs are filtered, while `**kwargs` adapters remain unchanged.
- Files: `providers/router.py`, `tests/test_provider_router_attempts.py`.
- Verification: focused provider tests passed `26 passed`; regression subset
  passed `14 passed`; broader provider coverage reported `82 passed`, with 21
  setup failures caused by the environment temporary-directory ACL.
- Remaining risk: uninspectable third-party callables retain the normal
  classified failure path.

### Context hard-budget admission

- Problem: the compaction fast path used floored `total_chars // 4`, allowing
  short recent-only transcripts to exceed the hard character envelope.
- Fix: fast-path admission now compares exact `total_chars` against
  `budget_tokens * 4`, and the final compaction result is fitted to the same
  envelope without mutating the caller transcript.
- Files: `context/__init__.py`, `tests/test_context_budget_boundary.py`.
- Verification: boundary regression passed; context redesign coverage passed
  `14 passed, 4 deselected`; the available context/scrubber partition passed
  `40 passed`.
- Remaining risk: four-characters-per-token remains an approximation until
  model-specific tokenizers are integrated into this boundary.

## Verified improvement: server and GUI session-management writers use the shared store

- Audit scope: only `server/`, `gui/`, and `nexus/` session-related Python files
  plus their relevant tests. The already-migrated `memory/` and
  `orchestrators/v5/core.py` writers were treated as the reference boundary.
- Problem: the server and GUI clear-session and rename-session paths wrote the
  shared `logs/sessions/<id>.json` / `.meta` files directly. Those writes could
  race a V5 or MemoryManager save and used a separate replacement protocol.
- Fix: both API surfaces now use `nexus.session_store.session_write_lock()`
  keyed to the transcript and `atomic_write_json()`. Clear persists both files
  under one lock and updates a cached loop without a nested save; rename locks
  the transcript even though it updates only metadata.
- Files changed: `server/__init__.py`, `gui/api.py`,
  `tests/test_session_api_store_migration.py`.
- Verification: the focused session/API suite passed `16 passed` in `16.67s`;
  `git diff --check` passed.
- Remaining scoped writers: none in `server/`, `gui/`, or `nexus/` write the
  conversational session JSON after this migration. `server` and `gui` still
  delete session files directly on non-default session deletion; that is a
  destructive mutator rather than a JSON writer and remains an uncoordinated
  follow-up risk. `nexus/run_context.py` writes durable run-context JSON, not
  conversational session transcripts, and was intentionally not migrated.

## Verified improvement: mission reconciliation and episodic retrieval

### Terminal mission results are idempotent

- Problem: a late failure for an already completed milestone could reopen it
  after identity/revision checks, causing duplicate replanning and work.
- Fix: terminal `done` and `blocked` milestones now ignore late results;
  queueing also uses a stable mission/milestone/revision idempotency key, and
  optional completion verification fails closed.
- Files: `queue/mission.py`, `tests/test_mission_layer.py`.
- Verification: mission tests `13 passed`.
- Remaining risk: legacy result payloads without IDs or revisions cannot get
  strong stale-result protection.

### Episodic retrieval uses the active query

- Problem: episodic prefetch ranked by recency/status/metadata while ignoring
  the current user message, so an unrelated recent failure could displace an
  older directly relevant episode.
- Fix: deterministic lexical query relevance is ranked first, with
  `user_message` passed through `prefetch_all()` into episodic retrieval.
- Files: `memory/__init__.py`,
  `tests/memory/test_memory_episodic_retrieval.py`.
- Verification: focused memory/RAG suite `22 passed`; adjacent memory/API
  suite `26 passed`.
- Remaining risk: lexical matching does not capture synonyms or semantic
  similarity.

### Combined regression verification

- Command: `python -m pytest -q tests/test_mission_layer.py tests/memory/test_memory_episodic_retrieval.py tests/test_memory_manager/scripts/test_memory_manager.py tests/test_session_api_store_migration.py`
- Result: `45 passed in 15.78s`.

## Verified improvement: destructive session cleanup is serialized

- Problem: non-default session deletion in the server and GUI checked for
  existence and removed transcript/metadata files outside the shared session
  lock. Concurrent saves could produce false not-found results or leave
  orphaned metadata.
- Fix: deletion now acquires the transcript-keyed interprocess lock before
  checking existence and removes transcript, metadata, and cached loop state
  as one protected operation. The default session remains a cleared session,
  never a deleted file.
- Files: `server/__init__.py`, `gui/api.py`,
  `tests/test_session_api_store_migration.py`.
- Verification: session persistence suite `14 passed`; adjacent endpoint and
  path-security tests `6 passed`.
- Remaining risk: a genuinely new write after deletion may recreate the
  session; that is intentionally treated as new activity.

## Verified improvement: V5 memory recall no longer drops context channels

- Problem: perception injected only the first three memory channels, while
  direct-loop integration could replace existing planning/Hive context. Large
  session/RAG channels could also starve procedural guidance.
- Fix: both paths now use a shared 8,000-character bounded merge that fairly
  allocates all eight channels, preserves existing execution context, redacts
  secrets, and deduplicates reused snapshots.
- Files: `orchestrators/v5/core.py`,
  `tests/v5/test_v5_memory_context_merge.py`,
  `tests/v5/test_v5_learning_signal_loop.py`.
- Verification: combined session/V5/mission/memory regression `70 passed`;
  one unrelated deprecation warning remains.
- Remaining risk: one adjacent pre-existing V5 stream API mismatch remains:
  `stream_run()` does not accept `idempotency_key`.

## Reference research update (2026-08-11)

- OpenCode analyzed at `dev@0d927ba`; Hermes Agent at
  `main@c0106e5`; OpenClaw at `main@71ea11b`. Current releases observed were
  OpenCode `v1.18.16`, Hermes `v2026.8.3`, and OpenClaw `v2026.7.1-2`.
- Durable-task lesson: separate logical tasks from immutable attempt records,
  use heartbeats/claim TTLs, and do not blindly replay an ambiguous
  non-idempotent provider dispatch after a crash. OpenCode's session spec and
  Hermes Kanban model are useful references; OpenClaw issue history shows the
  zombie-task failure mode.
- Loop lesson: combine exact-call hashes with no-progress/result hashes,
  ping-pong detection, cross-session spawn budgets, and one bounded recovery
  attempt. Exact-call detection alone misses truncation and recursive
  subagent loops.
- Context lesson: preflight the *next* request after large tool output, keep
  tool-call/result pairs intact, persist compaction, and fall back when a
  custom compactor returns empty output.
- Next architectural priority: durable execution leases and effect receipts;
  then unified provider classification/retry budgets, hierarchical loop
  detection, and next-request context preflight.
- Evidence links: OpenCode session spec
  `https://github.com/anomalyco/opencode/blob/dev/specs/v2/session.md`,
  Hermes Kanban
  `https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban.md`,
  OpenClaw compaction
  `https://github.com/openclaw/openclaw/blob/main/docs/reference/session-management-compaction.md`.

## Durable execution audit checkpoint

- Existing queue/control-plane integration already links legacy queue tasks to
  canonical task/plan/step/run records, renews both queue and canonical leases,
  refuses to replay a canonically succeeded side effect after a crash, and
  records cancellation explicitly.
- Verification: queue control identity, queue driver, and Hive effect-ledger
  regressions passed `20 passed in 3.92s`.
- Remaining gap: the canonical run/effect model is not yet a single public
  immutable attempt-receipt contract for every tool/provider execution. The
  next change should extend that boundary only after mapping all dispatch
  callers and defining recovery-required semantics for ambiguous outcomes.
