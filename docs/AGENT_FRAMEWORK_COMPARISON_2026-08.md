# Agent framework capability comparison and Nexus upgrade map

Date: 2026-08-10
Scope: production agent runtimes, coding-agent harnesses, durable workflows,
multi-agent orchestration, memory, tools, safety, and long-horizon execution.

This is an architecture comparison, not a leaderboard. Model quality, provider
access, prompt quality, tool permissions, and task sets can dominate results.
Only capabilities supported by primary documentation are treated as facts.
Unverified claims about closed or newly announced products are marked unknown.

## Executive conclusion

Nexus is unusually broad: it combines a local-first V5 loop, a durable queue,
Hive subagents, MCP, skills, plugins, sandboxing, memory/RAG, gateways, a GUI,
and an outer supervisor. Its weakness is not lack of modules; it is the
contract between modules. The next-generation runtime needs one durable run
record that owns the goal, plan revision, current step, checkpoint, approval,
artifact evidence, verifier verdict, retry budget, and resume cursor.

The most important upgrades are therefore:

1. independent milestone acceptance verification;
2. durable mission heartbeats and stuck-work recovery;
3. one unified run/step state machine across V5, queue, and Hive;
4. explicit background-task observation and operator controls;
5. replayable trajectories and task-level evaluations;
6. provider/model/tool routing measured against the same benchmark;
7. a clear distinction between safe autonomous continuation and actions that
   require approval.

## What current systems expose

| System | Loop and state model | Delegation/background work | Tools, safety, and environment | Observability/evaluation | Nexus comparison |
|---|---|---|---|---|---|
| OpenAI Responses API | Application owns the loop, output items, tools, state, and branching | Multi-agent coordination and PTC are available for suitable workflows | Functions, hosted tools, MCP/connectors, shell, sandbox and computer-use surfaces | Tracing/evals are first-class documentation paths | Nexus has local loop/control but needs stronger unified run state and benchmarked routing |
| OpenAI Agents SDK | SDK owns the agent loop; supports agents, handoffs, guardrails, results/state, sandbox agents, observability | Specialist ownership and handoffs are explicit | Typed tools/MCP and server-managed approvals | Traces and workflow evaluations are documented as a normal next step | Nexus has analogous pieces but they are spread across V5, Hive, queue, and server |
| Codex CLI | Local coding-agent harness with project instructions, permissions, sandbox/environment choices, skills, MCP, worktrees, non-interactive operation, and resume-oriented workflows | Background/long-running workflows and subagent operation are product-level concepts | Explicit permission/sandbox modes and isolated worktrees | Record/replay, hooks, review, and task progress surfaces | Nexus has most primitives but lacks one canonical transcript/trajectory contract across surfaces |
| Claude Code | Session harness with project memory/instructions and resumable sessions | Foreground/background subagents, task status, parallel research, chaining, nesting limits, and concurrency limits | Permission modes, MCP, hooks, tool restrictions, and project-scoped agents | Verbose output, task lists, partial-failure reporting, and session resume | Nexus should adopt explicit subagent status, partial-result semantics, and bounded nesting/concurrency |
| LangGraph | Checkpointed graph state keyed by thread; replay, time travel, pending writes, and restart from last successful node | Graph nodes/subgraphs provide explicit composition | Interrupts pause indefinitely; persisted state enables approval/edit/reject and safe resume | State history, replay, traces, and fault-tolerance are central | Nexus has checkpoints and replay pieces but needs a single checkpoint cursor for mission milestones |
| AutoGen | Agent runtime separates agent identity/lifecycle from messages and supports standalone or distributed runtimes | Teams, handoffs, selector/round-robin/swarm patterns, external termination, and agent-as-tool | Tools, code executors, MCP workbench, Docker executor, cancellation token | Team observation, task results, turn/token metrics, and state save/load | Nexus Hive has collaboration primitives; it needs clearer runtime ownership and distributed contracts |
| Gemini managed agents | Saved or inline agent configuration with instructions, skills/data, files, and tools | Managed interaction model with reusable agent configuration | Search, code execution, URL context, MCP, and custom functions | Provider-specific interaction state and tool results | Nexus is more local/provider-agnostic; it needs equivalent declarative agent profiles |
| CrewAI | Role/task/crew/flow abstraction with process and guardrail patterns | Sequential/hierarchical crews and flows | Tool/LLM integrations and task guardrails | Flow/crew execution visibility varies by deployment | Nexus has richer durability but should expose simpler declarative role/task definitions |
| Muse Code | Public primary technical documentation was not found during this audit | Do not treat third-party claims as verified capability evidence | Unknown until official docs or source are available | Unknown | Add an evidence row only after a primary source is available; do not copy rumors |
| Hermes Agent / Agent Zero | Earlier local reference inspection found delegation, checkpoints, context compression, tool-output limits, skill provenance, project memory, Docker/browser surfaces, and scheduling patterns | Explicit subordinate roles and background delegation | Project isolation, sandboxing, browser/desktop tooling, and scheduled skills | Trajectory compression and tool statistics are useful patterns | Nexus has several equivalents; provenance, trajectory normalization, and long-running task UX remain weaker |

## Capability inventory

The following checklist is the comparison target for Nexus. “Present” means an
implementation and relevant regression evidence exist; “partial” means the
concept exists but its contract is incomplete; “gap” means it is not yet a
release-grade capability.

### A. Goal, task, and run identity

1. Stable user goal ID across conversations.
2. Stable task ID independent of provider response IDs.
3. Stable plan revision ID.
4. Stable step ID and attempt ID.
5. Explicit run state machine.
6. Idempotent start/resume requests.
7. Durable owner/lease token.
8. Process and worker identity.
9. Parent/child run relationship.
10. Correlation IDs across model, tool, queue, Hive, and UI events.
11. Cancellation intent persisted before cancellation is acted on.
12. Pause/approval state that survives process death.

Nexus status: most primitives are present in separate stores. The gap is a
canonical cross-layer projection and an invariant that every surface uses it.

### B. Planning and long-horizon execution

13. Structured plan with dependencies and parallelism.
14. Plan revision with reason and changed steps.
15. Milestone acceptance criteria.
16. Independent completion verifier.
17. Evidence required per step.
18. Artifact manifest and fingerprints.
19. Progress heartbeat.
20. Stuck-step detection.
21. Bounded retry and backoff.
22. Replanning after failure.
23. Human escalation after bounded recovery.
24. Resume from the last successful checkpoint, not from the beginning.
25. No false completion when a plan has unfinished steps.
26. Explicit terminal states: completed, blocked, cancelled, failed, paused.
27. “Continue until done” policy with a safe stopping boundary.
28. Resource/time/cost budget.

Nexus status: queue leases, mission replan, V5 evidence verification, Hive
checkpoints, and supervisors exist. Mission acceptance verification and
mission-level stuck detection are the next implementation targets.

### C. Context and memory

29. Bounded working context.
30. Deterministic compaction trigger.
31. Durable transcript/checkpoint.
32. Resume prompt or state reconstruction.
33. Project instruction discovery and precedence.
34. Long-term memory with provenance.
35. Retrieval with source/evidence references.
36. Memory write policy and deduplication.
37. Time-travel/replay history.
38. Context isolation between parent and subagent.
39. Privacy/retention controls.

Nexus status: context compression, continuity memory, RAG, replay, skills, and
project instructions exist; unified provenance and cross-surface state replay
remain partial.

### D. Tools, skills, and extension surface

40. Typed tool schemas.
41. Tool discovery/search.
42. Tool output limits.
43. Tool timeout.
44. Retry classification.
45. Idempotency key for side effects.
46. Side-effect reconciliation.
47. MCP client/server support.
48. Skill/agent instruction loading.
49. Plugin lifecycle and trust policy.
50. Tool provenance and versioning.
51. Programmatic/batched tool calling for bounded data processing.
52. Direct-call fallback when semantic judgment is needed.
53. Tool approval/edit/reject workflow.
54. Tool result evidence attached to the step.

Nexus status: typed tools, MCP, skills, plugins, sandboxing, approvals, and
tool evidence exist. Provider-specific reconciliation and PTC-compatible
bounded tool batching remain partial.

### E. Multi-agent runtime

55. Explicit specialist roles.
56. Foreground versus background execution.
57. Status and partial-result notifications.
58. Parent/child cancellation propagation.
59. Concurrency and nesting limits.
60. Agent-as-tool or handoff semantics.
61. Shared blackboard with version/conflict control.
62. Dependency-aware scheduling.
63. Quorum/critic/verifier patterns.
64. Dead-agent replacement.
65. Distributed runtime boundary.
66. Per-agent resource budget.
67. Isolated worktree or workspace ownership.

Nexus status: Hive implements many items, including dependencies, quorum,
blackboard, replacement, and budgets. Background status/partial output and
distributed ownership need a more uniform contract.

### F. Safety and operations

68. Sandbox tier.
69. Permission mode.
70. Destructive-action confirmation.
71. Secret/credential boundary.
72. Network egress policy.
73. Crash detection.
74. Restart with bounded backoff.
75. Startup recovery.
76. Duplicate supervisor prevention.
77. Crash-loop quarantine.
78. Operator alerting.
79. Health/readiness.
80. Metrics and traces.
81. Backpressure.
82. Rate/cost budgets.
83. Deployment restart policy.

Nexus status: the reliability wave covers most of this list. Backpressure,
rich labels/exporters, paging integrations, and a single operator control
plane remain partial.

### G. Evaluation and release quality

84. Fixed deterministic framework contract tests.
85. Provider-independent agent benchmark.
86. Task success metric.
87. Completion/evidence metric.
88. Tool-call correctness metric.
89. Recovery-after-crash metric.
90. Duplicate-side-effect metric.
91. Context/token/latency/cost metric.
92. Human-review rate.
93. Replayable trajectory artifact.
94. Regression gate.
95. Soak test.
96. Cross-provider comparison with identical task/policy/tool set.

Nexus has a framework benchmark and broad regression suite. A long-horizon
soak harness and a fixed provider-backed task set are still required before
claims of parity with coding agents are credible.

## Prioritized Nexus backlog

| Priority | Capability | Why it matters | Proposed acceptance evidence |
|---|---|---|---|
| P0 | Mission acceptance verifier | Prevents a “successful” queue task from falsely ending a large goal | A verifier rejection replans the milestone; only verified evidence marks it done |
| P0 | Unified durable run projection | Prevents V5, queue, and Hive from disagreeing about progress | Restart/replay test shows identical goal/step/attempt state across surfaces |
| P0 | Mission heartbeat/stuck recovery | Prevents a live lease from hiding a permanently stalled milestone | Artificially age heartbeat; watchdog requeues exactly once and records why |
| P1 | Background task status/partial-result contract | Makes parallel work inspectable and resumable | Parent receives running/failed/partial/done state without treating partial as success |
| P1 | Side-effect reconciliation adapters | Makes retries safe for external APIs/files | Duplicate attempt reconciles existing effect instead of repeating it |
| P1 | Backpressure and event retention policy | Prevents long runs from exhausting memory or SSE clients | Slow consumer receives bounded loss/replay gap, while durable state remains intact |
| P1 | Trajectory/eval artifact | Makes progress measurable against other agents | Same task set produces JSON trajectories and success/evidence/recovery metrics |
| P2 | Declarative agent profiles | Makes roles, tools, skills, model, and policy reproducible | Profile loads deterministically and is persisted with the run |
| P2 | Distributed worker protocol | Allows scaling beyond one process/host | Two workers can claim, heartbeat, resume, and fence attempts without duplication |

## Evidence sources

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents)
- [OpenAI model guidance: PTC, multi-agent, reasoning, and eval considerations](https://developers.openai.com/api/docs/guides/latest-model)
- [Codex CLI documentation](https://developers.openai.com/codex/cli)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [AutoGen teams and termination](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/teams.html)
- [AutoGen runtime architecture](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/core-concepts/architecture.html)
- [Gemini managed agents](https://ai.google.dev/gemini-api/docs/custom-agents)
- [MUSE research paper](https://arxiv.org/abs/2606.14168) (research framework, not evidence about Meta’s Muse Code product)
