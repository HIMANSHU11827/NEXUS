# NEXUS OPTIMIZATION Next-Gen Blueprint

This document is the forward architecture for NEXUS after the current hardening
cycle. It is intentionally ambitious, but each idea is phrased as something that
can become code, tests, gui state, or benchmark cases.

## Research Signals

Current agent research and production practice are converging on these themes:

- Agents are not just prompts. They are runtimes combining planning, memory,
  tool use, evaluation, and environment interaction.
- Memory is becoming a first-class system with episodic, semantic, procedural,
  and temporal graph layers.
- RAG is moving from static retrieval to agentic retrieval: planning, searching,
  graph traversal, evidence judging, and answer composition.
- GraphRAG and temporal knowledge graphs are becoming core for long-horizon
  agent memory.
- Context engineering is replacing prompt engineering: agents need context
  routing, compression, memory ranking, and just-in-time retrieval.
- MCP is becoming the tool/resource protocol layer. A2A/ACP-style protocols are
  becoming the agent-to-agent layer.
- Tool use needs cost/risk/success telemetry, not blind model-emitted JSON.
- Coding agents win through repo maps, diagnostics, test selection, patch
  verification, and failure learning.
- Protocol-enabled agents create new security risks: tool impersonation,
  untrusted servers, secret leakage, agent-to-agent accountability gaps, and
  runaway autonomy.

Useful references:

- `AI Agent Systems: Architectures, Applications, and Evaluation`, 2026.
- `Memory in the Age of AI Agents`, 2025.
- Zep / Graphiti temporal knowledge graph memory.
- MA-RAG and mRAG multi-agent retrieval architectures.
- Agentic RAG surveys.
- MCPToolBench++ and MCP/A2A protocol analysis.
- Efficient agents surveys focused on memory, tool learning, and planning.

## NEXUS OPTIMIZATION

AURORA means:

```text
Autonomous Universal Reasoning, Orchestration, Retrieval, and Action
```

The new target architecture:

```text
User Intent
  -> Intent Radar
  -> Context Budget Broker
  -> Temporal Memory Graph
  -> Agentic RAG Swarm
  -> Repo Consciousness Map
  -> Tool Economy Router
  -> Execution Kernel
  -> Diagnostics / Critic / Verifier
  -> Mission Replay
  -> Failure Vaccine
  -> Memory Update
```

## Core Design Laws

1. Memory is infrastructure, not chat history.
2. Retrieval is an agent workflow, not a vector query.
3. Tool calls are economic decisions with risk, cost, and trust.
4. Context is routed just-in-time, never dumped blindly.
5. Every autonomous action must be replayable.
6. Every repeated failure must create a regression.
7. Every external tool or agent is untrusted until scored.
8. Every risky code edit needs edit planning, rollback, diagnostics, and tests.
9. gui state must be honest, not aspirational.
10. NEXUS should become better through benchmarked self-improvement, not hype.

## OPTIMIZATION Modules

```text
optimization/
  intent_radar.py
  context_budget.py
  temporal_memory.py
  graph_rag.py
  agentic_rag.py
  repo_consciousness.py
  tool_economy.py
  agent_contracts.py
  patch_court.py
  mission_replay.py
  failure_vaccine.py
  protocol_firewall.py
  model_economy.py
  world_simulator.py
  self_compression.py
  benchmark_trainer.py
```

## 120 Next-Gen Systems To Invent

### Memory

1. Temporal Memory Graph: facts with valid time, observed time, source, confidence.
2. Episodic Event Graph: every mission becomes a connected timeline.
3. Procedural Skill Graph: successful workflows become reusable procedures.
4. Semantic Project Graph: architecture facts, APIs, files, conventions.
5. Failure Memory Graph: bugs, traces, root causes, fixes, regressions.
6. User DNA Graph: durable user preferences and operating style.
7. World State Graph: OS, providers, tools, installed packages, ports, processes.
8. Memory Confidence Scoring: rank facts by recency, source quality, test proof.
9. Contradiction Detector: find facts that disagree.
10. Contradiction Repair Queue: ask verifier to resolve memory conflicts.
11. Memory Immune System: delete stale, low-value, duplicated, wrong memories.
12. Memory Promotion Engine: repeated useful facts move to higher-trust layers.
13. Memory Decay Engine: unused low-confidence memories fade.
14. Source-Linked Memory: every important memory links to file/test/log/source.
15. Memory Diffing: see how a fact changed over time.
16. Memory Trace: explain why a memory was retrieved.
17. Memory Quarantine: uncertain memories cannot influence high-risk actions.
18. Memory Merge Protocol: merge duplicate nodes safely.
19. Memory Compaction Packets: dense summaries with pointer IDs.
20. Memory Fitness Score: measure whether memories improve benchmark outcomes.

### Zero-Token Context

21. Context Packet Ledger: record every packet injected into prompts.
22. Pointer Dereference Tool: expand memory/file/test pointers only when needed.
23. Context Budget Broker: allocate token budget across repo, memory, tools.
24. Context Rot Detector: detect stale or overlarge context.
25. Just-In-Time Context Router: retrieve context at action boundaries.
26. Duplicate Context Purger: remove repeated facts from prompt packets.
27. Confidence-Based Context: low-confidence facts require verification.
28. Context Heat Score: rank context by mission relevance.
29. Context Capsule Cache: reuse compressed packets for repeated tasks.
30. Noisy Context Firewall: block irrelevant retrieval results.

### Agentic RAG

31. RAG Query Planner: decide which retrieval modes to use.
32. Keyword Retriever: BM25 and exact code identifiers.
33. Vector Retriever: semantic similarity.
34. Graph Retriever: memory/repo graph traversal.
35. Temporal Retriever: recent changes and time-sensitive facts.
36. Failure Retriever: similar past bugs.
37. Workflow Retriever: successful previous plans.
38. Symbol Retriever: functions/classes/imports/tests.
39. Negative Retriever: what failed before and should be avoided.
40. Evidence Judge: reject weak retrieval.
41. Multi-Hop Retriever: answer questions that require chained evidence.
42. RAG Self-Query: rewrite query if evidence is weak.
43. Retrieval Budgeter: stop retrieval when evidence is sufficient.
44. Source Truth Map: every answer references files/tests/docs.
45. RAG Benchmark Set: test retrieval accuracy on known project questions.
46. Stale Source Detector: detect deleted or outdated retrieved chunks.
47. GraphRAG Builder: extract entities/relations from code/docs/memory.
48. Hypergraph RAG: represent many-way relations like file-test-failure-fix.
49. Retrieval Replay: show why each source was selected.
50. RAG Confidence Calibration: compare retrieval confidence with test outcomes.

### Coding Agent Intelligence

51. Repo Weather Map: risky files, hot spots, stale tests, dependency hubs.
52. Test Selection Engine: choose smallest useful test set for a change.
53. Diagnostic Router: Python/JSON/YAML/TS/build checks by file type.
54. Patch Risk Scorer: risk by imports, blast radius, churn, missing tests.
55. Edit Plan Contracts: required checks before a file edit.
56. Side-Effect Simulator: predict files/tests affected by a change.
57. Bug Forecast Engine: predict likely failures before editing.
58. Test Gap Detector: find code with no obvious tests.
59. Symbol Ownership Map: map symbols to files/tests/memories.
60. API Contract Extractor: infer public function/class contracts.
61. Regression Generator: propose tests from fixed failures.
62. Patch Court: planner, engineer, critic, verifier, judge.
63. Red-Team Diff Trial: adversarial review before risky edits.
64. Multi-File Refactor Planner: staged dependency-aware refactors.
65. Architecture Drift Detector: warn when code violates docs/design.
66. Codebase Consciousness Snapshot: compact repo intelligence packet.
67. Dependency Gravity Score: identify files that attract many changes.
68. Fragility Score: files with high failure/churn/impact.
69. Build-Aware Planner: include frontend/backend/package checks.
70. Rollback-Aware Editor: every high-risk edit has recovery metadata.

### Tool Economy

71. Tool Reputation Market: success rate, latency, risk, cost.
72. Tool Risk Profiles: read/write/destructive/network/secret categories.
73. Tool Fitness Decay: old success rates decay over time.
74. Tool Alternative Planner: fallback tools for each capability.
75. Tool Cost Router: prefer cheap local tools when enough.
76. Tool Latency Router: avoid slow tools for simple tasks.
77. Tool Health Checks: verify tools before critical missions.
78. Tool Schema Validator: strict argument validation.
79. Tool Output Normalizer: consistent JSON/text/error envelopes.
80. Tool Failure Clustering: group repeated failures by root cause.
81. Tool Forge Loop: generate missing tools with tests.
82. Tool Sandbox Profiles: isolate risky external tools.
83. Tool Audit Replay: replay every call and result.
84. Tool Capability Cards: machine-readable tool descriptions.
85. Tool Scope Firewall: tool can only access allowed paths/secrets/network.

### Protocols And Multi-Agent

86. MCP Client Firewall: validate external MCP tools before use.
87. MCP Server Export: expose safe NEXUS tools through MCP.
88. A2A Agent Adapter: delegate tasks to external agents.
89. Agent Card Registry: discover agents and capabilities.
90. Agent Contract Protocol: objective, role, tools, deadline, output schema.
91. Agent Trust Score: rank agents by past performance.
92. Agent Task Market: agents bid/qualify for tasks.
93. Hive Checkpointing: pause/resume long Hive missions.
94. Hive Merge Judge: merge conflicting worker results.
95. Agent Accountability Ledger: who did what, with which evidence.
96. Agent Secret Firewall: never leak secrets across agent boundaries.
97. Cross-Agent Memory Permissions: memory visibility by role.
98. Consensus Verifier: require multiple agents for high-risk claims.
99. Agent Drift Monitor: detect agents that stop following role contract.
100. Multi-Protocol Gateway: MCP for tools, A2A/ACP for agents.

### Autonomy And Safety

101. Mission Replay Black Box: full trace of prompt/context/tools/tests.
102. Failure Vaccine Engine: failure -> fix -> regression -> memory rule.
103. Shadow Execution: simulate risky plan before doing it.
104. Process Tree Governor: kill runaway subprocess trees.
105. Network Allowlist Profiles: task-specific network boundaries.
106. Filesystem Scope Profiles: per-task read/write roots.
107. Secret Access Broker: explicit secret use events and redaction.
108. Rollback Browser: inspect and restore snapshots from gui.
109. Destructive Action Simulator: predict blast radius before command.
110. Autonomy Modes: fast, balanced, forensic, lockdown.

### Product And gui

111. Mission Control Timeline: live run timeline.
112. Repo Weather gui: risk heatmap.
113. Memory Graph Viewer: inspect memory nodes and links.
114. Tool Market gui: tool success/risk/latency.
115. Provider Economy Panel: cost, latency, health, capability.
116. Benchmark History Graph: quality over time.
117. Patch Ledger Browser: inspect diffs and rollbacks.
118. Swarm Board: tasks, roles, artifacts, failures.
119. Context Packet Viewer: see what context entered a prompt.
120. Failure Vaccine gui: regressions generated from failures.

## Implementation Phases

### Phase 1: Make Current NEXUS Smarter

- Add mission replay. `[started: optimization/mission_replay.py]`
- Add tool economy telemetry. `[started: optimization/tool_economy.py]`
- Add test selection engine. `[started: optimization/test_selection.py]`
- Add failure vaccine engine. `[started: optimization/failure_vaccine.py]`
- Expand edit planner into a required pre-edit workflow.
- Add benchmark cases for diagnostics, RAG, memory, and provider routing.

### Phase 2: Build Memory-Native NEXUS

- Temporal memory graph v2.
- Memory confidence and contradiction repair.
- Context packet ledger.
- Failure memory graph.
- Memory cleanup scheduler.

### Phase 3: Build Agentic RAG

- Query planner.
- Multi-mode retrievers.
- Evidence judge.
- GraphRAG builder.
- Retrieval benchmark suite.

### Phase 4: Build Agent Runtime

- Agent contracts.
- Patch court.
- Swarm checkpointing.
- Mission replay.
- Tool economy router.

### Phase 5: Build Protocol Mesh

- MCP client with firewall.
- Safe MCP server export.
- A2A/ACP adapter.
- Agent trust registry.
- Protocol audit logs.

### Phase 6: Productize

- Repo weather gui.
- Memory graph viewer.
- Tool market gui.
- Benchmark history.
- Rollback browser.
- Mission replay viewer.

## The First 20 Features To Actually Build

1. Mission replay JSONL event log.
2. Tool economy metrics store.
3. Tool reputation routing.
4. Test selection engine.
5. Memory graph v2 schema.
6. Context packet ledger.
7. Failure vaccine engine.
8. Regression generator draft mode.
9. Agentic RAG query planner.
10. Evidence judge.
11. Repo weather map.
12. Patch court for high-risk edits.
13. gui benchmark history panel.
14. gui rollback browser.
15. MCP client firewall.
16. MCP server exposing read-only NEXUS tools.
17. Agent contract YAML format.
18. Swarm checkpoint/resume.
19. Provider economy routing by latency/cost/capability.
20. Architecture drift detector.

## What To Avoid

- Do not add fake AGI labels without working systems.
- Do not add more agent names unless they have contracts, tools, and tests.
- Do not depend only on vector search for memory.
- Do not trust MCP/A2A tools without security wrappers.
- Do not route everything through the biggest model.
- Do not use huge prompts as a substitute for context engineering.
- Do not add gui cards that show fake active systems.
- Do not skip regression tests after fixing bugs.

## North Star

NEXUS should become:

```text
A local-first autonomous engineering OS with temporal memory, agentic RAG,
repo consciousness, tool reputation, auditable execution, secure protocol
integration, and self-generated regression learning.
```
