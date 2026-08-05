# NEXUS V5 — Framework Research & Lessons (2026)

Research comparing 23+ agent frameworks/applications against the NEXUS V5 loop
(`orchestrators/v5/`, `NexusLoopV5`, 24-entry MRO, 7-phase `_turn_events` pipeline).
Scope: their loops, architectures, source; what V5 already does better; and a
ranked roadmap of concrete V5 improvements. Every claim below was verified
against live repos/docs unless marked `[unverified]`.

---

## 1. How V5's loop works (baseline we compare against)

`NexusLoopV5._turn_events` (core.py:660) runs a 7-phase turn: Meta-learning →
Perceive (skills/hive context injection) → PAORR (LLM plan → tool act → observe →
reflect → retry) → Quantum (opt) → Evolution (opt) → Learning signals → Output
(streamed). Supports: MoE router LLM calls with provider fallback, schema-fed
planner, tool executor with auto-discovery + permission audit + risk-scored
3-tier sandbox, evidence-based verification, deterministic turn learning, abort +
post-tool hooks, canonical event streaming, sub-agent (hive) spawning, cron,
lifecycle state, background runner, evolution forges, config/permissions/sandbox/
log mixins.

---

## 2. What V5 already does better (keep — do not regress)

- **Evidence-based verification**: `V5Verifier` never claims success without
  grounded evidence; Codex / Claude Code / smolagents are bare `while(tool_use)`
  loops where validation is prompt-encouraged, not structural.
- **Deterministic turn learning** (no LLM): failures/reflections/JSONL replay.
  No CLI or framework ships this in-loop.
- **Content-based threat scanning** (55 regex patterns, 3 scopes) + 4 permission
  modes + risk score + decision log — the CLIs rely on OS sandboxes + rule lists.
- **Multi-provider routing + fallback + OAuth** (45+ providers) vs single-vendor.
- **Canonical event system** (~50 typed events, telemetry, chunk streaming) —
  matches Codex JSONL, exceeds Claude SDK-only, feeds GUI/TUI/CLI.
- **Runtime tool auto-discovery** (`./tools/` scan at startup) + free-text tool-call
  extraction + alias canonicalization — no compared tool hot-discovers tools.
- **Fault-tolerant engineering**: every subsystem init wrapped, duck-typed
  fallbacks — loops survive any module failure.

---

## 3. Verified research summaries (23 frameworks/apps)

### Assistant CLIs
- **OpenAI Codex** (openai/codex): `AgentLoop` in `codex-cli`; Rust `codex-rs`
  core with `unified_exec` (approval→sandbox→run→**retry unsandboxed on denial**),
  OS-level sandboxes (Seatbelt / bubblewrap+seccomp / Job Objects), split
  fs+network policies with read-only carveouts, JSONL exec protocol
  (`thread/turn/item` events) + `resume --last`, git workspace rollback,
  `apply_patch`, MCP `required=true` fail-closed.
- **Claude Code**: `while(true){ send → tool_calls → execute → push }`;
  **6 permission modes** (default/acceptEdits/plan/auto/dontAsk/bypassPermissions)
  with ordered rule eval *deny→allow→ask→mode* + invocation matchers
  (`Bash(git*)`); **hooks JSON stdout/stdin contract** (exit 0 + decision, exit 2
  = block); 5 hook handler types; auto-compaction (~83.5%) with `compact_boundary`
  + PreCompact hook; subagents = fresh context window, only final summary returns;
  `max_turns`/`max_budget_usd` caps + ResultMessage cost.
- **Gemini CLI**: **Plan Mode** = read-only phase enforced by policy
  (`enter_plan_mode`/`exit_plan_mode` tools, editable `plan.md`, approval gate);
  `ask_user` clarifications; **phase-based model routing** (Pro plan → Flash
  implement); tiered policy engine; `write_todos` live model-editable task list.

### Autonomous agents
- **OpenClaw** (openclaw/openclaw): multi-channel gateway + per-session lanes with
  queue modes (steer/followup/collect/interrupt); 7-stage loop; SOUL.md/USER.md
  persona reinjected each iteration + drift thresholds; on-demand skill body load;
  plugin hooks at every seam (`before_prompt_build`, `tool_result_persist`,
  terminal block/cancel); memory SQLite+embeddings, compaction w/ retry;
  stuck/stalled/long-running diagnostics.
- **Manus / OpenManus** (closed + FoundationAgents/OpenManus): analyze→plan→
  execute→observe; **live visible plan with per-step ✓**; file-artifact process
  memory (TODO.md + intermediate `.md`); PlanningFlow = planner agent→executors;
  CodeAct-style python-as-action.
- **Devin** (Cognition, closed): planner→actor→verifier; VM (Devbox) + editor/
  shell/browser tools; **interactive editable plan**; traceback→edit→re-run
  self-repair; verification-first ("come back with proof"); Devin Fusion = hybrid
  model routing with sidekick agents [planning internals partially unverified];
  microagents (`.devin/`) reshaping behavior `[unverified]` at source level.
- **OpenHands** (All-Hands-AI/OpenHands): **append-only typed EventStream**
  (Action/Observation, parent/child ids, per-event token cost, replay);
  AgentController state machine + **StuckDetector** (repeating patterns) +
  **security analyzer** (risk class → confirmation only MEDIUM/HIGH);
  `AgentDelegateAction` delegate/suspend-resume; CodeAct kernel; per-session
  Docker runtime.

### Dev-tool cluster
- **Hermes** (`NousResearch/hermes-agent`): self-improving agent; skills-from-
  experience, SQLite FTS5 recall, contextual compression (head/tail + Resolved/
  Pending), security scanning of memories/injection, credential redaction,
  `@file`/`@url` context references; gap: no LSP/AST intelligence on coding.
- **Goose** (block/goose, now Linux-Foundation AAIF): 3-layer (interface/agent/
  extensions=MCP); **errors routed back to the model as tool results** (loop
  self-resolves); context revision with cheaper LLM (compact/truncate);
  YAML recipes (parametrized, sub-recipes, headless `recipe run`);
  `PermissionManager` + GooseMode per tool; ACP JSONL control protocol + JSONL
  sessions.
- **Aider** (Aider-AI/aider): **repo map** = tree-sitter symbol extraction +
  PageRank (chat-file/reference boosts) token-budgeted into context (default
  ~1/8 the context, hard), SQLite-cached; `editblock`/`whole`/`udiff` formats per
  model; **architect/editor two-model split** (benchmarked +5-8%); `--auto-lint`
  + `--auto-test` with failures+TreeContext fed back for auto-repair; auto-commit
  + `/undo` git-native.
- **Open Interpreter**: 2026 = Rust-native harness fork = Codex-fork for low-cost
  models; fail-closed sandbox modes (workspace-read/write/ask) with protected
  paths; profiles YAML; original Python loop superseded.
- **SWE-agent / SWE-bench**: **ACI** = purpose-built agent-computer interface:
  edit-write linter (block invalid edits), windowed file viewer (~100 lines +
  scroll/search), search returns file paths only, empty-output canonical message;
  headless in Docker; **Trajectories = replayable JSONL**; SWE-bench eval harness =
  FAIL_TO_PASS + PASS_TO_PASS per instance in Docker; harness quality is what
  drove rates up over raw prompts.

### Multi-agent frameworks
- **AutoGen / Magentic-One**: Orchestrator outer loop builds/re-architects
  **Task Ledger** (facts/plan/guesses) + inner **Progress Ledger** per round with
  **stall counter → reflection → replan**; 4 specialist delegates (WebSurfer/
  FileSurfer/Coder/Terminal); `save_state`/`load_state` resumability.
- **CrewAI**: Process.sequential vs Process.hierarchical (`manager_llm`);
  task-level tool scoping; unified memory with scope tree + slices; event-driven
  Flows (`@listen/@router`, `@persist`, `@human_feedback`); knowledge sources.
- **LangGraph**: StateGraph + reducers; Pregel supersteps (fan-out/fan-in,
  all-or-nothing); **checkpointing/time-travel** (InMemory/SQLite/Postgres);
  `interrupt()` HITL + `Command(resume)`; `Send` map-reduce; typed streaming
  modes; per-node RetryPolicy.
- **MetaGPT**: SOP assembly line of roles; shared **message pub/sub pool** with
  typed `cause_by` routing; agents exchange **structured documents (ActionNode**
  schemas) not raw text; engineer debug loop; Team quiescence.
- **CAMEL**: RolePlaying (AI user ↔ assistant) + TaskPlannerAgent; **critic-in-
  the-loop** with criteria; Workforce with recovery modes RETRY/REASSIGN/
  DECOMPOSE/REPLAN/CREATE_WORKER; stateful task hierarchy OPEN/RUNNING/DONE.
- **OpenAI Swarm / Agents SDK**: handoffs (agent-as-value) + context_variables;
  `Runner`; **guardrails** (parallel, abort on fail); sessions persistence;
  **agents-as-tools** delegation; tracing spans.

### SDKs / modern tooling
- **smolagents**: **CodeAgent = Python snippets as actions** (papers: ~30%
  fewer steps; success @ hard benchmarks), tools bound as functions, local
  mostly-local executor is not a security boundary — real sandboxes via
  Docker/E2B/Modal/Blaxel; ManagedAgent
  delegation (sub-agent callable as function), `agent.logs` observability.
- **PydanticAI**: internal agent graph + typed tool args (validated pre-exec);
  **RunContext deps DI** (no globals); `output_type` structured returns;
  partial-model streaming validation; MessagePart typing (Text/ToolCall/
  ToolReturn); durable `pydantic_graph` package.
- **LlamaIndex Agent Workflows**: typed step events (AgentToolCall/AgentStream);
  explicit shared `Context` (get/set); human-in-the-loop as `InputRequiredEvent`/
`HumanResponseEvent` stream events; parallel fan-out on same event.
- **Mastra**: Agents (model-driven) vs Workflows (deterministic graph, durable,
  resumable); Zod-typed tools; built-in memory/RAG/evals/tracing; MCP client + server.
- **Vercel AI SDK**: **standard SSE data-stream protocol** (typed parts —
  start/text-delta/tool-call/tool-result/done/data-parts); `stopWhen` declarative
  stop conditions; `prepareStep` per-step model/tools mutation; `activeTools`
  per-step gating; **UIMessage vs ModelMessage separation**.

### Classic loops & evals
- **ReAct**: interleave thought/action/observation; V5 PAORR is structurally ReAct
  with deterministic (not LLM) reflection.
- **BabyAGI**: task queue + execution → embedding storage → creation →
  prioritization → repeat; durable but retrieval-fragile.
- **Voyager**: **automatic curriculum** (self-proposed goals, novelty-based);
  embedding-indexed skill library (code skills, compositional); iterative
  prompting self-verification → commit skill.
- **Generative Agents**: memory stream with scored retrieval
  `recency·α + relevance·embedding + importance(llm 1-10)`; threshold-triggered
  **reflection** into layered abstractions; ablations: reflection matters on
  long horizons.
- **Evals**: SWE-bench Verified (500 human-verified) — FAIL_TO_PASS/PASS_TO_PASS
  Docker harness; τ-bench pass^k (state-grounding/reliability vs LLM judge);
  GAIA level-stratified step chains; Aider polyglot — self-correction magnitudes.
  Lesson: state/programmatic verification beats LLM judgment — V5's philosophy.

---

## 4. Ranked V5 work roadmap (highest impact → do first)

Legend: **M** = major (new mixin), **m** = medium (extend existing module),
**S** = small (config/event/param).

1. **Typed, replayable event log + per-turn checkpoint/resume** — adopt
   OpenHands EventStream / Goose ACP / SWE-agent trajectories. V5 already emits
   canonical events; make the story durable & resumable. Files: `events.py`,
   `log.py`, new `checkpoint.py` mixin, `core.py` phase gates. **M**
2. **Plan visibility + plan-level HITL approval** (Manus/Devin/Gemini plan-mode/
   LangGraph interrupt): emit `plan.updated` per step (pending/running/done/
   failed), `plan.approval_request` in APPROVE mode — reuse `ApprovalBroker`,
   keep plan editable artifact. Files: `planning.py`, `permissions.py`,
   `events.py`, `core.py`. **M**
3. **Bounded self-repair loop on verification failure** (Devin/SWE-agent/Goose):
   on `verification.success == False`, feed evidence back into a corrective
   plan (≤2 iterations) instead of stopping; errors routed to model in-band.
   Files: `verification.py`, `core.py::_fallback_execute`. **M**
4. **Aider-style repo map** (tree-sitter + PageRank, token-budgeted) injected into
   planner context — symbol graph, not file dumps. `planning.py`. **M**
5. **Per-action risk class + confirmation only for risky** (OpenHands): gate
   registry tools by risk class in APPROVE; improve AUTO_PILOT utility.
   `tools.py::_audit_tool_call`, `permissions.py`. **M**
6. **Phase-based model routing** (Gemini/Devin Fusion): strong model for plan/
   verify, cheaper for tool-gather/final; expose thinking-budget knob.
   `model.py`, `planning.py`. **M**
7. **Episodic memory stream + reflection synthesis** (Smallville/Voyager):
   populate `MemoryContext.episodic` from replay JSONL, score recency/importance/
   relevance; on failure → LLM root-cause into stored insight.
   `memory/_prefetch_episodic`, `paorr.py::_reflect`, `learning.py`. **M**
8. **Edit-time quality gate + windowed ACI** (SWE-agent): pre-apply syntax lint
   on `modifying`; expose `reading`/`code_search` as windowed subsections,
   `search` returns file paths only. `verification.py`, `tools.py`. **M**
9. **Hook protocol upgrade** (Claude Code / OpenClaw): matchers + optional JSON
   stdout contract (exit 0 + decision / exit 2 = block) + `pre_phase`/`post_phase`
   fires on `_transition_to` (core.py:909). `control.py`, `plugin.py`. **M**
10. **Workspace rollback / git snapshot** (Codex): per-turn snapshot, `/undo`.
    `tools.py`, `control.py`. **M**
11. **Compaction with boundary event** (+ optional cheap-LLM summarizer):
    `compact_boundary` + `PreCompact` hook. `context_manager.py`, `events.py`. **M**
12. **Map-reduce Send-style fan-out in `V5ParallelExecutor`** — superstep
    semantics (apply branch only if all succeeded). `parallel.py`. **M**
13. **Task ledger + stall-detection + replan** (Magentic-One): progress fallback
    counter → replan instead of repeating a plan. `planning.py`, `parallel.py`. **M**
14. **Hive delegation upgrade** — parent/child refs + suspend/resume + runtime
    result routing mid-plan; `cause_by`-typed message pool for workers.
    `hive.py`, `events.py`. **M**
15. **Curricula / self-proposed goals** (Voyager): promote top gap to a goal on
    idle/cron cycles; embedding-based skill retrieval. `evolution.py`, `core.py`. **M**
16. **Per-run budget + cost reporting** (`max_turns`/`max_budget_usd`, tokens+cost
    in `done` event). `control.py`, `events.py`. **M**
17. **Code-as-action mode (optional)** — fenced-python executed in existing tiers
    with registry tools bound as callable; add `final_answer` sentinel.
    `tools.py::_execute_code_action`, `planning.py`. **M**
18. **Queue lanes + message priority + timeout** (OpenClaw): task→network
    backlog; idle watchdog in `_safe_model_call`. `cron.py`,
    `background_runner.py`, `model.py`. **M**
19. **Per-session / per-repo instruction dirs** (`.devin/` → `.nexus_v5/agents/`)
    merged into planning prompt. `planning.py`. **S**
20. **Config-driven profiles** (permissions.mode + sandbox.tier + tool allowlist
    per session); tiered policy files in `~/.nexus_v5/`. `config.py`,
    `permissions.py`, `sandbox.py`. **S**
21. **V5 eval harness** (SWE-bench subset / GAIA / pass^k): replay `replays.jsonl`
    turns with programmatic PASS/FAIL; wire into tests. New `bench.py`. **M**
22. **Budget/cost telemetry** surfaced as `run.finished` event payload. `events.py`. **S**

### Patterns rejected (with reason)
- Full LangGraph graph formalism — overkill for coordinator+mixins; adopt lessons
  (reducers/interrupts/checkpoints) piecemeal.
- smolagents default code-as-actions — adopt behind a flag for secrets/risks.
- OS-kernel sandbox enforcement (Codex/Claude) — V5 needs a portable Windows +
  Linux path; current 3-tier app sandbox + threat scan is the pragmatic stop-gap;
  add OS hooks when a bounded platform build exists.

---

## 5. One-paragraph decision memo
Highest-leverage for V5 = durable/typed events + checkpoint-resume (1), plan-level
HITL + visibility (2), bounded self-repair (3). Together they convert a single-
pass 7-phase loop into a debuggable, resumeable, self-correcting loop — reusing
existing mixins, approval broker, verifier, and event stream; every one surfaces
in the GUI/SSE wire the moment `events.py` adopts typed streaming parts. Start
from lessons 1, 2, 3, 4, 6, 8 — in that order — as NEXUS V5 "Lesson Rounds".