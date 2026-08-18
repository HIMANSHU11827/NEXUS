# Multi-Agent Task Plan

## Objective

Launch and exercise the NEXUS TUI, identify reproducible failures in normal chat/task workflows, fix root causes, and verify the result with focused tests.

## Workstreams

- [x] Coordinator: reproduce TUI startup and basic task flows; record evidence.
- [x] Repository Analyst: inspect TUI entrypoint, lifecycle, input handling, and recent risk areas.
- [x] Testing: identify or add focused regression coverage for any reproduced issue.
- [x] Critical Reviewer: inspect the final patch and test evidence for regressions and unsafe behavior.

## Completion Criteria

- TUI starts from the repository's supported command.
- At least three representative task/input flows are exercised.
- Any reproducible root-cause defect is fixed with a focused regression test.
- Relevant tests/build checks pass, or failures are clearly documented with evidence.

## Evidence

- `nexus` and standalone `cd tui && npm start` both reached `online` in elevated live checks.
- Live slash-command checks: `/status`, `/tools`, `/files`, `/run`, and `/git`.
- Natural-language chat check entered the real provider/tool loop; Esc cancellation returned the TUI to idle cleanly.
- `npm.cmd run build`: passed.
- `npm.cmd test`: passed (30 modularization/startup assertions and 19 component smoke assertions).
- Model chat remains environment-blocked by missing `DEEPSEEK_API_KEY`; the TUI reports `health: degraded` and cancellation works.
- Critical review passed token flow and virtualenv selection; it noted that the working tree contains substantial pre-existing unrelated edits, which were preserved.

## Follow-up Agentic Coding Mission

- [x] Ask the live NEXUS agent to inspect startup-auth coverage, plan a focused improvement, implement it without touching unrelated files, and run the focused test.
- [x] Verify the agent's plan, edits, test result, and root-cause handling from the TUI transcript and repository diff.

Follow-up result: the live agent never reached planning or repository work because the configured DeepSeek provider remained unavailable; it was cancelled after 38 seconds with no file changes. The deterministic launcher test was then added directly and passed.

- New regression: `tests/test_boot_setup_marker.py::test_ink_tui_propagates_dashboard_token_to_children`
- Focused result: `1 passed`; complete boot/setup file: `31 passed`.

## Tool-Argument Failure Investigation

- [x] Coordinator: reproduce and trace the `creating` tool missing `path` failure shown in the supplied TUI screenshots.
- [x] Tool Schema Analyst: inspect `creating` metadata, registry normalization, and executor validation.
- [x] Loop/Transport Analyst: inspect model tool-call parsing, repair retries, and argument preservation.
- [x] Implementation: preserve malformed arguments across provider adapters and the V5 parser; add focused regression coverage.
- [x] Testing/Critical Review: provider matrix and focused transport tests pass; pytest temp-directory cleanup remains blocked by an existing Windows ACL issue.

Root-cause evidence: the saved session contains three identical native calls, `creating` with `arguments: "{}"`. The `creating` metadata and V5 model schema both correctly require `path` and `content`; registry validation rejects the empty call before the file handler runs. Provider adapters and the V5 parser previously converted malformed/truncated argument payloads to `{}`, losing the diagnostic and causing generic repair retries. The fix centralizes argument normalization in `NexusBaseProvider`, rejects lossy truncated-to-empty repairs, preserves a bounded diagnostic marker, and stops execution before side effects when the parser reports an argument error.

Focused evidence: `tests/test_tool_argument_transport.py` — 4 passed; provider tool-call matrix — 73 passed; existing tool-result/deepseek tests included — 16 passed; V5 direct-loop/provider/queue regression set — 66 passed; AST parse of all 45 provider modules passed.

## 24/7 Resilience and Maturity Pass

- [x] Coordinator: inventory the dirty worktree, current architecture, and operational constraints without overwriting user changes.
- [x] Loop/Recovery specialist: audit V5 retries, checkpoints, cancellation, and continuation after failures.
- [x] Tool/Skill specialist: audit registry metadata, discovery truthfulness, argument validation, and execution isolation.
- [x] Hive/Lifecycle specialist: audit sub-agent recovery, gateway supervision, server health, and 24/7 restart behavior.
- [x] Testing: run broad Python/TUI baselines, classify failures, and reproduce actionable defects.
- [x] Implementation: fix the highest-impact shared root causes with focused regression tests.
- [x] Critical review: verify safety, bounded retries, no fake success, no regression, and document external blockers.

Constraint: the worktree already contains substantial user-owned modifications and untracked files across core, providers, tools, gateway, Hive, server, tests, GUI, and TUI. All maturity work must preserve unrelated changes and use narrow patches.

### Boundary Safety Follow-up

- [x] Critical reviewer: identify plugin-result, recursive-schema, and progress-projection trust gaps.
- [x] Implementation: canonicalize plugin-declared mapping failures in atomic and streaming paths.
- [x] Implementation: recursively validate nested object/array constraints before tool side effects.
- [x] Implementation: require the backend `deterministic-v1` marker and explicit safe progress keys.
- [x] Testing: focused Python boundary suite, wider direct-loop/tool/plugin suite, full TUI tests, and TypeScript build pass.

### Final resilience evidence

- Real `python -m nexus` Ink TUI startup reached the configured DeepSeek provider and `online`; authenticated headless status also passed. A live external-model coding request was intentionally not transmitted because it would disclose workspace-derived content without destination-specific approval.
- Root causes fixed across provider argument preservation, per-signature repair budgets, queue heartbeat/worker fencing, durable run recovery, Hive cancellation/replacement, gateway supervision, truthful plugin/MCP results, recursive schemas, plan restoration, and checkpoint identity.
- Lease ownership is now propagated as an execution fence into V5 and enforced by the registry, direct terminal path, and built-in file/plan/memory/task commit boundaries. Uncertain external outcomes are durably quarantined before bounded cancellation, preventing replacement replay during cleanup.
- Focused final gates: 93 lifecycle/direct-loop tests passed; 33 queue/tool fence tests passed; final early-quarantine regressions passed 3/3; provider matrix passed 112 with 1 skipped; checkpoint tests passed 13; integrated boundary suite passed 157.
- TUI: complete npm test suite and TypeScript build passed. The test renderer still emits an existing non-fatal `MaxListenersExceededWarning`.
- Broad Python suite reached 73% with no reported failures after an earlier 2314-pass run exposed three regressions that were fixed and individually rechecked. The last rerun was invalidated by the final quarantine-order patch; a fresh elevated rerun could not start because the execution-approval usage quota was exhausted, while sandboxed pytest temp directories hit the known Windows ACL denial.
- Critical review's final P1 was the quarantine-order race. The implementation now performs the exact requested transition before waiting on cancellation; post-fix reviewer execution could not return a final message because the agent quota was exhausted.

---

## Reliability Mission (2026-08-17)

### Objective
Transform Nexus into a persistent, self-healing runtime: unified failure envelopes, validated+persisted state machine, durable goals, recovery ladder with strategy freezing, stall detection, queue worker isolation, capability hardening � proven by unit/integration/chaos tests.

### Workstreams
- [x] Reliability core (failure/states/goal/recovery/progress/observability) � built by main agent (general sub-agents returned empty in this environment).
- [x] V5 loop integration (V5Reliability mixin, V5LoopState extension, hardened _transition_to, direct_loop hooks, retry backoff, run_context intermediate statuses, new EVENT_TYPES).
- [x] Queue worker isolation (A2 agent, completed): driver worker isolation + replacement budget + quarantine; 5 new tests.
- [x] Capability hardening (A4 agent, completed): web_search retry, registry env defaults, MCP timeout, memory forge, plugin rollback; 25 tests.
- [x] Chaos/failure-injection tests (provider outage, network partition, MCP disconnect, worker crash, strategy escalation, restart/resumption).
- [x] Audits (2 explore agents): reliability adoption/coverage audit; persistence & resume surface audit.
- [x] Docs: research architecture + comparison matrix, mission report, 2 audits.

### Evidence
- 599 passed / 0 failed: reliability 89 + integration 28 (incl. chaos) + capabilities 25 + v5 411 (no regression) + queue/run_context/supervisor/hive/planning 46.
- Bugs found+fixed: recovery attempt double-count, state-machine no auto-resume, GoalState.from_dict non-dict crash, progress-counter leak across runs (caught by v5 regression), pre-existing mcp_adapter import + memory forge self-param bugs.
- Known follow-ups (documented in audits): per-round tool-result flush, wire _checkpoint_resume + set_intermediate_status into live paths, persist worker quarantine, unify dual FailureClass taxonomies, 104 silent-swallow sites across 7 unwired subsystems.

---

## Agent Systems Deep Research (2026-08-17)

### Objective
Research how Manus, Hermes, DeepSeek, Claude Code, OpenAI Codex, and OpenCode handle tool use, prompts, failure handling, testing, memory, security, permissions, skills/plugins/MCP, multi-agent, and configuration - 50+ Q&A per system - then compare every topic against Nexus.

### Workstreams
- [x] Manus (context-engineering blog: KV-cache hit rate, stable prefix, append-only context, cache breakpoints, no mid-loop tool changes) - 53 Q&A.
- [x] Hermes (NousResearch function calling: ChatML + `<tools>` XML + prompter/schema/jsonmode; Hermes Agent framework from vendored source: HERMES_HOME profiles, plugins, restart counts, cron leases, 1,688 hermetic tests) - 50 Q&A.
- [x] DeepSeek (error codes 429/500/503, tool-call loop, strict mode beta, thinking-mode tool use, context-cache pricing) - 51 Q&A.
- [x] Claude Code (permissions/deny-removes-tool, hooks, CLAUDE.md hierarchy + auto memory, 18-section prompt + dynamic boundary, 10x retries + incomplete-response idempotency) - 61 Q&A.
- [x] Codex (AGENTS.md chain, config.toml precedence, hook hash-trust, sandbox modes + network proxy, granular approvals, subagents, OTel metrics) - 65 Q&A.
- [x] OpenCode (permissions/doom_loop/external_directory, agents, plugins event bus, MCP OAuth, skills, rules, troubleshooting) - 65 Q&A.
- [x] Nexus comparison chapter per topic + 10 transferable lessons.
- [x] Deliverable: docs/research/agent_systems_deep_research.md (861 lines, sources appendix, gaps marked "undocumented").

### Evidence
- All answers grounded in primary sources (official docs, vendored hermes-agent source, third-party corroborating source analyses); where a system publishes nothing, the gap is stated explicitly.
- Deepest cross-cutting finding: Manus/Claude Code/DeepSeek independently converge on stable-prefix prompt caching (cache-hit metrics, dynamic boundary) - Nexus's biggest adoption gap; failure-handling (Nexus state machine + escalation ladder + chaos tests) and orchestration (Hive) are Nexus's strongest positions vs the six.
