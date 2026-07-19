# NEXUS Harness Landscape: Public Agent Systems

**Reviewed:** 2026-07-18  
**Purpose:** Compare NEXUS's real runtime harness with leading public coding,
computer-use, messaging, and orchestration systems. This is an engineering
decision record, not a marketing ranking.

## Scope and Method

NEXUS was assessed from its current source, especially `orchestrators/loop.py`,
`nexus/events.py`, `hive/engine.py`, `tools/nexus_tools/registry.py`,
`permissions/`, `sandbox/`, `mcp/`, `plugins/`, `skills/`, `memory/`,
`server/`, and `gui/api.py`.

External comparisons use current public primary documentation or public source.
Private products can only be compared by their observable/public behavior; their
internal loop implementation is not knowable. "All agents" is not a finite or
stable set, so this covers the leading public families rather than pretending to
rank every agent ever released.

Status labels: **Strong** means NEXUS has an implemented foundation; **Partial**
means it exists but lacks a mature end-to-end contract; **Gap** means it is not a
first-class, production-ready capability.

## NEXUS Today

NEXUS is a local-first product runtime, not merely an SDK. A session owns one
active `NexusLoop`; a run grounds context, selects a provider per request,
streams a model response, classifies tool use, applies permissions/risk/sandbox
rules, runs read tools concurrently and writes sequentially, verifies work,
persists memory, and emits one terminal run event. The canonical event model
already covers messages, plans, tools, commands, files, tests, web work,
memory, skills, and subagents.

It also has provider breadth/local providers, an Ink TUI, React GUI, HTTP/SSE
server, messaging gateways, tools, Hive subagents, MCP client and server,
plugins, skills, memory, command risk scoring, and normal/Docker sandbox tiers.

## A-to-Z Comparison Table

| System / family | Public strength | What NEXUS already has | What NEXUS is missing or weaker on |
|---|---|---|---|
| **OpenAI Codex** | Local/cloud coding workflow, sandboxed command execution and approvals | Local-first runtime, provider independence, TUI/GUI, tools, tests, sandbox tiers | Stronger OS-level sandbox policy and a polished parallel-worktree workflow |
| **OpenAI Agents SDK / Responses** | Structured function calls, handoffs, guardrails, traces, resumable approval patterns | Canonical events, Hive, cancellation, provider routing | Strict structured call IDs/schemas everywhere, durable traces, approval-resume state |
| **Claude Code** | Mature deny/ask/allow policy, hooks, MCP lifecycle, sessions, worktree isolation | Rules, risk scoring, plugin hooks, MCP, Hive | Deny-first unified policy, declarative hooks, worktree-backed agents, session branch/export |
| **Google Antigravity** | Agent manager for parallel agents, editor/terminal/browser operation, artifact evidence | GUI/TUI/server, Hive, browser/web tools, event timeline | Dedicated manager UX, browser proof artifacts, visible replay/verification evidence |
| **Cursor / Windsurf / Copilot** | IDE-native code context, edit review, background/cloud coding workflows | Workspace tools, GUI panels, provider flexibility | Deep editor protocol, code intelligence/index UX, worktree/review handoff product polish |
| **Devin** | Cloud software-engineering environment with long-running task execution | Local developer tools, loop, verification, memory | Durable cloud/local task environments, recovery, reviewable task timeline; private internals cannot be compared |
| **Manus** | Browser and local-computer operator, visual task execution, user controls | File/terminal/web tools, gateways, local-first direction | A safe browser/computer control runtime plus screenshots/artifacts and user takeover flow |
| **Genspark** | Publicly presented as a multi-tool "super agent" with generated artifacts | Research/tools, Hive, GUI | Source-backed public harness details are insufficient to treat it as a technical reference; evaluate behavior, not hidden claims |
| **Hermes Agent** | One runtime across surfaces, typed tool schemas, skills/memory, subagents, provider setup | Tools/plugins/skills/memory, Hive, many providers, SSE surfaces | One shared runtime adapter, context accounting/compaction diagnostics, agent profiles, effective-policy view |
| **OpenClaw** | Session-centric gateway, policy-filtered tools, isolated child sessions, channel controls | Gateway, MCP, skills/plugins, canonical events, Hive cancellation | Per-channel/per-agent effective policy, child-session isolation, durable gateway/session store |
| **OpenHands** | Self-hosted coding platform with process/Docker/remote sandbox choices and browser/editor/terminal workspace | Python+React architecture, sandbox tiers, terminal/file flows, skills | Mature sandbox lifecycle/provisioning, archived-readonly session UX, benchmark/evaluation operation |
| **SWE-agent / Aider** | Focused code-agent ergonomics: constrained tool interfaces, repository map, patch workflow | File and terminal tools, tests, diff events | High-signal repository map, patch-review mode, benchmark discipline for coding tasks |
| **Cline / Roo Code / OpenCode** | Open extensibility, provider choice, modes, MCP, IDE workflows | Provider breadth, MCP, tools, TUI/GUI, plans | First-class modes/profiles and editor integration, not another generic abstraction layer |
| **LangGraph / Deep Agents** | Durable graph checkpoints, interrupts, state inspection, long-running recovery | Linear loop, events, memory, Hive | Persistent run checkpoint/resume/replay and explicit state transitions without reintroducing an overbuilt static phase enum |
| **AutoGen / Microsoft Agent Framework** | Multi-agent patterns and OpenTelemetry-oriented observability | Hive roles/events/cancellation | Standard traces, robust parent-child run lineage, reproducible multi-agent evaluation |
| **CrewAI / Google ADK / Semantic Kernel** | Declarative agents, flows, tools, and human checkpoints | Hive, skills/plugins, tools, events | Declarative agent profiles and composable workflow definitions where they simplify real jobs |
| **PydanticAI / Smolagents** | Typed contracts and small, inspectable loops | Frozen canonical event type and direct loop | Strong runtime validation for every tool input/output, no text-pattern fallbacks for production protocol |
| **Browser-use / Playwright-style operators** | Browser control plus assertions/screenshots | Web tools and GUI | Explicit browser state, navigation policy, consent, assertions, screenshot/video evidence and replay |

## Capability Scorecard

| Capability | NEXUS | Leading reference | Decision |
|---|---|---|---|
| Local-first and provider choice | **Strong** | Hermes, Cline, OpenHands | Keep this as a NEXUS differentiator |
| Main tool loop correctness | **Strong** | Codex, Claude Code, Agents SDK | Keep the single-terminal-event and cancellation tests |
| Structured tool protocol | **Improved partial** | OpenAI Responses, PydanticAI | Tool calls now normalize names/params and derive stable IDs when providers omit IDs; next require provider-native JSON schemas where available |
| Event model and streaming | **Improved foundation** | Agents SDK, Hermes, AutoGen | GUI/TUI request canonical SSE events and GUI run details include public event replay; next collapse GUI/server streaming code into one adapter |
| Durable run recovery | **Foundation added** | LangGraph, OpenClaw | `RunContext` records run identity/status and GUI APIs can replay public events for a run; next add safe resume, branch, export |
| Permission policy | **Improved partial** | Claude Code, OpenClaw | Deny-first precedence and a scrubbed decision log now exist; next apply one evaluator across every capability and surface it in GUI/TUI |
| Sandbox containment | **Improved partial** | Codex, Claude Code, OpenHands | Invalid config now fails closed to normal; next make the Windows boundary real with resource/network limits and documented fallbacks |
| Subagents | **Strong foundation** | Claude Code, OpenClaw, AutoGen | Add profiles, inherited-context rules, worktree isolation, and per-agent tool policy |
| Context/memory | **Partial** | Hermes, OpenClaw, LangGraph | Budget accounting, tool-output pruning, compaction that preserves call/result pairs |
| MCP | **Improved partial** | Claude Code, OpenClaw | Failed init cleanup, dead-process restart, tool availability liveness, and catalog env-secret handling now exist; next add health UI, retry/backoff policy, OAuth scope handling, output caps, per-server/tool approvals |
| Plugins and skills | **Improved partial** | Hermes, OpenClaw | Skill precedence, active-prompt filtering, plugin unload cleanup, and inactive plugin load blocking now exist; next add full capability validation and trust reporting |
| Browser/computer use | **Gap** | Antigravity, Manus, OpenHands | Add only with a separate safety and evidence design, not as an unchecked terminal shortcut |
| Observability and evaluations | **Partial** | Agents SDK, LangGraph/LangSmith, AutoGen | OpenTelemetry-compatible traces, cost/latency data, golden tasks, failure regression suite |
| Multi-surface product UX | **Foundation improved** | Antigravity, Claude Code, OpenClaw | Shared request/session parsing, GUI backend cancel, run-context APIs, and gateway session IDs now exist; next unify streaming semantics and build inspector panels |

## Where NEXUS Is Already Better or Different

1. **Local-first by design.** NEXUS is not tied to one model vendor and can use
   local providers alongside cloud providers.
2. **Broad product surface.** One project includes a Python core, Ink TUI,
   React GUI, server, gateways, tools, Hive, MCP, plugins, skills, sandbox,
   permissions, and memory.
3. **Canonical work events.** Its event envelope is broader than a plain token
   stream and already represents tool, file, test, web, plan, and subagent work.
4. **Safety vocabulary exists.** Permissions, risk scoring, sandbox tiers, MCP
   limits, and plugin trust are separate concepts. The next job is making them
   one coherent enforceable policy.
5. **Recent loop repairs are meaningful.** Run ownership, cancellation,
   provider request isolation, tool concurrency, duplicate-error avoidance, and
   Hive task cleanup are now tested behavior rather than promises.

## Important Weaknesses: Do Not Hide These

1. **Two HTTP runtime adapters remain, but the shared runtime foundation has
   started.** `nexus.runtime` now owns session IDs, session paths, turn IDs,
   provider normalization, max-token parsing, and shared chat request parsing.
   `gui/api.py` and `server/__init__.py` still separately implement response
   framing, but both now expose run contexts and public work-event replay.
2. **Run state has a durable identity record and replay APIs, but not full recovery.**
   `RunContext` now persists run/session IDs, provider/model, token limits,
   start time, terminal status, and a prompt preview. GUI and standalone server
   backends can list runs and return public work-event replay. Logs and memory
   are still not sufficient for safe mid-run approval, disconnect recovery,
   branching, export, or idempotent resume.
3. **Permission precedence and core decision logging exist, but the policy
   surface is still split.** `PermissionSystem` blocks explicit deny rules
   before allow rules, including in AUTO_PILOT mode, and stores a scrubbed recent
   decision log. The remaining work is one `deny -> ask -> allow` evaluator that
   covers built-in tools, terminal, MCP, plugins, skills, browser, gateway, and
   Hive, then exposes those decisions consistently in GUI/TUI.
4. **The normal sandbox is a best-effort command/path guard, not an equivalent
   OS security boundary.** Treat it honestly. On Windows, implement enforceable
   filesystem/network/process limits or clearly require Docker for hostile work.
5. **Tool parsing still has compatibility paths.** Tool calls now have
   normalized names/params and stable fallback call IDs, and the harness avoids
   executing ordinary chat text. Production action calls should still converge
   on provider-native structured schemas and validated call/result pairs.
6. **No product-grade context inspector.** Users need to see how much context is
   history, rules, skills, memory, tools, and provider output, plus why compaction
   occurred.
7. **No first-class browser evidence loop.** Any future computer-use feature
   needs consent, policy, screenshots/assertions, takeover/stop, and audit logs.
8. **No systematic agent evaluation gate.** Unit tests are good but do not replace
   repeatable task suites for edit quality, safety refusals, cancellation,
   resume/reconnect, MCP failure, and multi-agent conflict behavior.
9. **MCP/plugin/skill lifecycle still needs hardening.** MCP failed starts now
   clean up child processes, calls no longer reuse exited subprocesses, and
   MCP-backed tools report client liveness to the tool registry. Skill managers
   are root-keyed with safer delete behavior and disabled skills no longer enter
   active prompts. Plugin unload now unregisters owned tools and hooks, and
   inactive plugin metadata prevents runtime loading. MCP catalog env config now
   rejects literal secrets and supports `${ENV_NAME}` references. Remaining work
   includes explicit health UI, retry/backoff policy, and effective capability
   reporting.

## Recommended Build Order

### P0: Make one trustworthy runtime

1. Extend the new persisted `RunContext` beyond run/session IDs, provider/model,
   timing, prompt preview, and terminal status. Add event sequence, tool policy,
   approval state, cancellation token, and parent lineage.
2. Put `gui/api.py`, `server/`, TUI, shell, and gateways behind one runtime/SSE
   adapter. Shared request/session parsing is in `nexus.runtime`, GUI stop now
   calls backend cancellation, and the GUI asks for canonical event streaming;
   next move streaming, event-sink binding, and response framing behind the same
   runtime contract.
3. Replace per-surface permission checks with one policy evaluator. Deny-first
   precedence and recent decision records are now covered in the core permission
   system; extend that guarantee everywhere and render it in the user surfaces.
4. Use structured tool call schemas and call IDs end-to-end; keep text parsing
   only as opt-in legacy compatibility, never as the default execution path.

### P1: Make long jobs safe and inspectable

5. Persist append-only event traces and checkpoints, then implement pause,
   approve/resume, reconnect, replay, branch, and export.
6. Add trace/cost/latency/error-cause fields and an OpenTelemetry-compatible
   exporter. Build a GUI/TUI run inspector from the same data.
7. Give every Hive agent a declarative profile: allowed/denied tools, model,
   max turns, skill set, memory scope, sandbox tier, timeout, and optional Git
   worktree isolation.
8. Upgrade MCP with visible health states, retry/backoff policy, output limits,
   OAuth scope storage without secret leakage, and per-server/per-tool approvals.

### P2: Improve agent usefulness without weakening safety

9. Add context budgets, call/result-safe compaction, diagnostics, and an
   effective-tool/effective-policy report before each model call.
10. Build a browser/computer-use subsystem only with explicit authorization,
    isolated profiles, domain policy, screenshots/assertions, takeover, and
    reproducible artifacts.
11. Add a versioned evaluation suite to CI: repair tasks, safety tests,
    cancellation, provider failure, resume/reconnect, MCP, plugin, gateway, and
    concurrent Hive worktree tests.
12. Add coding ergonomics selectively: repo map, patch review, test selection,
    worktree cleanup, and editor integrations. Do not turn NEXUS into an IDE-only
    product.

## Sources

- [NEXUS agent loop](../AGENT_LOOP.md)
- [OpenAI Agents SDK run loop](https://openai.github.io/openai-agents-python/running_agents/)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI tracing](https://openai.github.io/openai-agents-python/tracing/)
- [OpenAI Codex Windows sandbox](https://openai.com/index/building-codex-windows-sandbox/)
- [Claude Code permissions](https://code.claude.com/docs/en/permissions)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code worktrees](https://code.claude.com/docs/en/worktrees)
- [Google Antigravity overview](https://www.antigravity.google/docs/overview)
- [Google Antigravity announcement](https://developers.googleblog.com/en/build-with-google-antigravity-our-new-agentic-development-platform/)
- [Hermes Agent documentation](https://hermes-agent.nousresearch.com/docs/)
- [OpenClaw agent documentation](https://docs.openclaw.ai/agent)
- [OpenClaw policy/sandbox/elevation boundary](https://docs.openclaw.ai/gateway/sandbox-vs-tool-policy-vs-elevated)
- [OpenHands repository](https://github.com/OpenHands/OpenHands)
- [OpenHands sandbox documentation index](https://github.com/OpenHands/docs/blob/main/llms.txt)
- [Manus Browser Operator](https://manus.im/docs/features/browser-operator)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [AutoGen observability](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tracing.html)
- [Roo Code repository](https://github.com/RooCodeInc/Roo-Code)
