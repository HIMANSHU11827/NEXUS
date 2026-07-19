# Full-System Acceptance Audit

Date: 2026-07-03  
Scope: attached A-to-Z NEXUS mission, checked against the current worktree.  
Method: source and focused regression evidence. A declared schema, route, or component is not counted as end-to-end working without a production path and proportionate evidence.

## Verdict

**Not fully accepted.** Source proves a substantial canonical event/runtime foundation, real GUI/TUI adapters, ordered persistence/replay, focused security boundaries, and regression coverage. It does not prove the mission's complete real-user flow across GUI and TUI, complete client-to-runtime cancellation, every required event family in production, bounded high-volume streaming, true child-agent orchestration, or an all-repository green test run.

**Proven** means direct implementation plus focused regression evidence. **Partial** means meaningful implementation exists but the full mission scope is not demonstrated. **Open** means required implementation or evidence is absent.

## Requirement-to-evidence matrix

| Mission requirement | Status | Current evidence | Remaining gap |
|---|---|---|---|
| Research Agent: 100+ sources and matrix | Proven artifact | `docs/research/agent_framework_research_matrix.md`; prior verified pass records 110 sources. | This pass did not independently re-fetch every external source. |
| Full architecture map and migration design | Partial | `docs/ARCHITECTURE.md`, `docs/NEXUS_UNIFIED_AGENT_ARCHITECTURE.md`, package tree. | No single dependency map proves every module/caller; some broader docs remain aspirational. |
| One canonical validated event model with all named types/fields | Proven schema; partial use | `nexus/events.py`; canonical registry/envelope tests in `tests/gui/test_work_event_updates.py`. | Several registered types, including phase/web/handoff/skill lifecycle, lack demonstrated production emitters. Legacy adapter fields remain. |
| Ordered delivery, persistence, latest-state dedupe | Proven focused semantics | `gui/api.py::{append_work_event,list_work_events,replay_work_events_after}`; ordering, persistence, live-sink, replay tests; GUI/Ink sequence guards. | No crash/soak proof; sequence lock is process-local rather than a multi-process transaction. |
| SSE/RPC and schema validation | Partial | `/api/chat` frames `message`, `work_event`, `heartbeat`, `error`, `done`; command stream uses SSE; persisted records use `CanonicalEvent`. | API requests/responses remain mostly dictionary-shaped instead of fully typed FastAPI models; replay itself is JSON. |
| Reconnect/resume and history replay | Partial | `after_sequence`/`Last-Event-ID`, `next_sequence`, persistent JSONL, cursor regression tests. | No automatic dropped-SSE reconnect/resume flow is demonstrated in clients. |
| Cancellation propagation | Partial | `POST /api/chat/{session_id}/cancel` calls `abort()` and persists `run.cancelled`; endpoint test. | GUI and Ink stop actions only abort local readers and do not call the endpoint, so backend work may continue. |
| Backpressure/batching | Partial | Tool output is chunked by `NEXUS_TOOL_STREAM_CHARS`; UI appends stdout/stderr incrementally. | Chat uses an unbounded queue; no load/latency test or bounded backpressure contract. |
| Main loop lifecycle, immediate acknowledgement, truthful terminal state | Partial/strong core | `orchestrators/loop.py` emits conversation/run/message/plan/step/tool states; actionable requests require a real tool; core loop failure/lifecycle tests. | One real-provider run has not demonstrated every acceptance observation; complete phase/subgoal flow is absent. |
| Simple and advanced planning tied to work | Partial | Planning events and real plan-step events wrap tool calls; completed plan contains numbered tool steps; checklist/phased structures exist. | Prescribed four advanced phases and all phase/subgoal transitions are not consistently emitted as canonical phase events. |
| Tool registry, schemas, lifecycle, errors, streaming | Partial | `ToolRegistry.stream_execute()`, loop lifecycle/chunk emission, typed parameter/security tests, direct sandbox command path. | Atomic upstream tools have no intermediate stream; exhaustive retry semantics and every installed tool are not tested. |
| Command stdout/stderr, exit code, direct ownership | Proven focused path | `NexusLoop._run_tool()` routes shell aliases through `SovereignSandbox`; command API and TUI/Rich tests cover output/exit code. | No high-volume stress test; environment/profile display is not uniformly proven. |
| File/search/web/test bubbles and payloads | Partial | Canonical registry/inference, loop work payloads, GUI Canvas/timeline consumers, adapter-kind tests. | No single smoke run proves read, edit/diff, search, web, and test metadata together. Specialized web/test emitters are incomplete. |
| GUI chat/timeline/workspace from backend events | Partial, strong | `gui/src/App.tsx`, `WorkActivityTimeline.tsx`, `CanvasPanel.tsx`; stable-ID merge, scoping, replay, failure visibility, no-fabricated-card tests. | No current browser acceptance capture proves every click/expand, repeated-run, error and long-history criterion. |
| GUI/TUI parity on shared events | Partial, strong | Ink, headless and Rich adapters; `tests/test_shell_tui.py` covers canonical/public/internal events, extended kinds, failures and real command output. | Expandable-detail parity/full interactive acceptance is unproven; stop does not cancel backend work. |
| Workspace selected-activity details | Partial | Canvas selection/detail paths for files, command/tool/search/test and extended kinds; regressions prevent assistant-chat fallback. | Changed lines/diffs depend on producer payload and are not proven for every edit; no browser interaction test here. |
| Skill discovery, precedence, usage identity | Proven registry; partial runtime | `skills/registry.py`; tests prove canonical precedence, legacy reads and identity; curator/forge tests exist. | Automatic selection/use and full mission skill-category examples are not demonstrated. |
| MCP integration and trust boundary | Proven focused boundary; partial system | `mcp/security.py`; tests cover workspace escape, bounds, no-shell process launch, argument validation, redaction and oversized lines. | Server authenticity, capability authorization, prompt-injection defense and OS isolation remain incomplete. |
| Plugin integration and safe installation | Partial | `plugins/manager.py`, `plugins/trust.py`; manager and fail-closed install tests. | Opted-in plugins remain unsigned executable code; no signature/checksum trust chain or isolation. |
| Shell/file permissions, traversal, secrets | Partial | Risk scorer + sandbox, MCP root boundary, API path helpers, redaction tests. | No repository-wide adversarial audit proves every API/file/plugin path; not a hosted multi-tenant boundary. |
| Provider routing/errors/configuration | Partial | Provider router/factory/health; loop test prevents provider error strings becoming assistant content. | External providers/fallback combinations require credentials/services and are not all exercised. |
| Real multi-agent child runs and merged coordinator | Open/partial schema | Parent/subagent fields/types exist; GUI/TUI recognize agent/hive events. | No general independent child-run orchestration with linked logs, cancellation, streamed status and final merge is proven. Audit agents are not product evidence. |
| Memory/session/history correctness | Partial | Loop memory, `/api/history`, session bus, JSONL events. | Long-run growth, compaction and mission-wide memory correctness are not acceptance-tested. |
| Clean shutdown/no stuck state | Proven finalizers; partial system | `NexusLoop.aclose()`, `server._app_lifespan()`, shutdown/finalizer tests, UI failure regressions. | `gui.api` is a separate app without that lifespan owner; all child resources are not covered by one shutdown test. |
| Performance and long-run stability | Partial/open | Incremental chunks, capped previews/results and fetch limits, merge-in-place client behavior. | No benchmark for first response, throughput, memory/render cost or TUI flicker; JSONL growth is unbounded. |
| Remove fake/demo/dead and duplicate production paths | Partial | Tests reject fabricated thinking/next-action cards and private bootstrap leakage; canonical persistence exists. | Compatibility aliases and broader legacy/aspirational modules remain; repository-wide absence of dead/mock controls is unproven. |
| Backend, GUI, TUI start and complete real smoke task | Partial evidence | Prior work log records API/GUI HTTP 200 and runtime smoke; focused suites cover component contracts. | No fresh recorded TODO-summary task simultaneously proves every GUI workspace and TUI acceptance step. |
| Tests, lint, typecheck, build, repeat/failure flows | Partial | Prior focused pass records 126 passed, 1 skipped, GUI build/lint, CLI typecheck and runtime smoke. | Unscoped `python -m pytest` is unproven; optional dependency/provider failures remain outside the focused result. |
| Documentation and honest run/test instructions | Proven this pass | `docs/ARCHITECTURE.md`, `docs/NEXUS.md`, this audit. | README and other docs were outside this agent's write scope and may require reconciliation. |

## Direct regression evidence

- `tests/gui/test_work_event_updates.py`: canonical persistence, ordering/latest-state, live multiplex, SSE frames, cursor replay, cancellation, privacy, plan evidence, and GUI invariants.
- `tests/test_shell_tui.py`: real command output/exit code, public/internal rendering, pure canonical envelopes, stable merge, stop/retry source behavior, and extended Ink/headless kinds.
- `tests/test_tool_security_boundaries.py`: registry validation, MCP boundaries/redaction/bounds, skill precedence, plugin opt-in.
- `tests/core/test_loop/scripts/test_loop.py`: terminal failure events, canonical lifecycle, finalizer drain, actionable-tool truth.
- `tests/test_mcp`, `tests/test_plugin_manager`, `tests/test_skill_curator`, `tests/gui/test_command_execution.py`, and `tests/test_server/scripts/test_auth_endpoints.py` cover focused subsystem contracts.

The latest recorded focused pass is **126 passed, 1 skipped**, with GUI build/lint, TUI typecheck, and runtime smoke passing. It is evidence only for that selected scope, not an all-repository pass.

## Gates remaining for full acceptance

1. Wire GUI and Ink stop controls to the cancellation endpoint; verify provider/tool termination and replayable `run.cancelled`.
2. Record the exact real-user smoke task through GUI and TUI: acknowledgement, plan, search/read/edit/diff, command/test output, selected workspace details, final summary, replay, repeat, and failed command.
3. Emit/test real canonical phase/subgoal, web, handoff, skill, and subagent lifecycles rather than only registering their names.
4. Add bounded transport queues/batching, long-output/history performance tests, and JSONL retention/compaction.
5. Prove linked parent/child agent runs with cancellation and coordinator merge, or label the product capability unavailable.
6. Run the unscoped repository suite and resolve or explicitly quarantine every optional dependency/provider failure before claiming global green status.
7. Reconcile remaining README/roadmap/legacy claims and remove compatibility paths only after all consumers migrate.

Until these gates pass with current runtime evidence, NEXUS is a capable local development agent with a strong event foundation, not fully accepted against the attached mission.
