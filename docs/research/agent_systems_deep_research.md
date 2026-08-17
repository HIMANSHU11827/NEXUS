# Agent Systems Deep Research

**Scope:** How six agent systems — **Manus, Hermes, DeepSeek, Claude Code, OpenAI Codex, OpenCode** — handle tool use, prompts, failure handling, testing, memory, security, permissions, skills/plugins/MCP, multi-agent orchestration, and configuration. Every system has 50+ researched questions and answers. A final chapter compares each topic against **Nexus AI** (this repository).

**Method:** Answers are grounded in primary sources researched for this document: official documentation (code.claude.com, developers.openai.com/codex, api-docs.deepseek.com, opencode.ai, manus.im blog), the NousResearch/hermes-function-calling repository, and the Hermes Agent framework source vendored in this repo (`.research/hermes-agent-main/`, `external/hermes-agent/`, `references/hermes-agent/`). Claims marked "public knowledge" are well-established facts about the product rather than sourced from the primary docs above. Where a system does not publicly document something, that gap is stated explicitly rather than guessed.

**Topic groups used for every system:**
1. Agent loop & orchestration
2. Tool use & function calling
3. Prompts & context management
4. Memory & state
5. Failure handling & recovery
6. Testing & evaluation
7. Planning & delegation (multi-agent)
8. Human-in-the-loop & permissions
9. Security & sandboxing
10. Observability
11. Skills / plugins / MCP ecosystem
12. Configuration & customization

---

# 1. Manus

> Manus is the general-purpose agent by the Monica team. Public documentation is thin: Manus has never published full internals. The richest primary source is the team's own engineering blog, *Context Engineering for AI Agents* (manus.im/blog/Context-Engineering-for-AI-Agents), which describes how they rebuilt their agent framework four times. Answers marked (blog) come from that post; (public) are general knowledge about the Manus product; (undocumented) means no public source exists.

## 1.1 Agent loop & orchestration

**Q1. What is Manus's basic agent loop?**
(public) Manus is a cloud VM-based general agent: user submits a task → the agent decomposes it, operates a browser and terminal inside an isolated virtual machine, observes the results, and iterates until the task is done. The user watches a live view of the VM.

**Q2. What does the blog say about designing the loop itself?**
(blog) The Manus team rebuilt their agent framework roughly four times ("Stochastic Graduate Descent" — repeatedly replacing the scaffolding while keeping the behavior). The lesson they publish: the agent loop's *structure* (how context, action space, and observations are composed) matters more than prompt wording, and it must be treated as the product.

**Q3. How is the loop structured per iteration?**
(blog) Each iteration = current action space → execute action in the environment (VM sandbox) → append the observation to context → next iteration. Context is append-only: observations accumulate and are never rewritten in place.

**Q4. Does Manus use sub-agents?**
(public) Manus launches parallel sub-agents for independent sub-tasks (file handling, code execution, web research) and consolidates their results in the main loop. This is a standard part of how it handles multi-step tasks, though exact orchestration details are undocumented.

**Q5. Is there a fixed number of iterations?**
(undocumented) Manus does not publish a step budget. (blog) The closest public guidance: because every iteration is an expensive context append, the team engineered the context so that iterations stay cache-friendly (see prompts section) — implying iteration count/cost is a first-class design concern.

**Q6. What terminates the loop?**
(public) The agent decides the task is complete and produces a final result/artifact. No documented "done-detector" or state machine exists publicly.

## 1.2 Tool use & function calling

**Q7. What tools does Manus use?**
(public) OS-level actions inside the VM: file operations, terminal/code execution, browser automation (computer use), web search. The action space is defined per task context rather than being a fixed catalog.

**Q8. What is the blog's key tool-usage rule?**
(blog) **Do not add or remove tools mid-loop.** Manus found that changing the action space between iterations degrades model behavior and destroys prompt-cache continuity. Decide the action space once, at loop start, and keep it stable.

**Q9. How should tool definitions be serialized?**
(blog) Deterministically. Tool names and their rendered definitions must be byte-identical across turns so the prefix stays cacheable; nondeterministic ordering (e.g., dict iteration order) breaks caching and model predictability.

**Q10. How are tool outputs handled?**
(blog) Observations are appended in a deterministic order with a consistent format, so the model can parse prior results reliably and the cache break happens at known points.

**Q11. What metric should you watch for tool-using agents?**
(blog) **KV-cache hit rate** is called the single most important production metric. Tool definitions + system prompt dominate the input tokens of every call; if the prefix changes between calls, every call pays full price and behavior becomes unstable.

**Q12. Does Manus use native function calling or text-format tool calls?**
(undocumented) Manus does not publish its tool-call wire format (likely provider-native tool calling inside a framework loop, but this is not confirmed publicly).

## 1.3 Prompts & context management

**Q13. What is the core prompt-stability rule?**
(blog) Keep the prompt prefix **completely stable**: no timestamps, no dynamic state at the top. Everything that changes goes below a cache boundary. The stable prefix is what the KV cache keys on.

**Q14. What are "cache breakpoints"?**
(blog) Explicit markers in the prompt where the system deliberately breaks the cache (e.g., before appending a large observation batch). They give the team control over when the cache refreshes instead of letting it happen implicitly and unpredictably.

**Q15. Why append-only context?**
(blog) Rewriting earlier context (a) invalidates the cache for everything after the rewrite, (b) changes what the model "remembers" mid-run, and (c) is the #1 cause of observed performance collapses in their agent runs. New information is appended after existing content.

**Q16. What does "deterministic serialization" mean concretely?**
(blog) The same piece of state (tool list, environment, observation) is rendered identically every time it appears. Non-deterministic rendering (random key order, changing phrasing of identical facts) was measured to hurt both cache hit rate and task success.

**Q17. Why is KV-cache hit rate the "top production metric"?**
(blog) Because it is a leading indicator: a drop predicts latency spikes, cost growth, and degraded agent behavior *before* task failure shows up in success metrics. Manus monitors it continuously rather than only measuring end-of-task success.

**Q18. How does Manus structure the prompt hierarchy?**
(blog) Stable identity/system content at the top (maximal cache reuse), then the action space, then append-only task state/observations below explicit breakpoints. This mirrors the "stable prefix / dynamic suffix" pattern that Anthropic also uses in Claude Code (see section 4) — two independent teams converging on the same design.

## 1.4 Memory & state

**Q19. Does Manus have long-term memory?**
(undocumented) Manus has not published a long-term memory design. Its working model is in-context: the append-only context is the memory, bounded by the context window.

**Q20. How is state carried across iterations?**
(blog + public) In-context observations plus the VM's filesystem: artifacts, downloaded files, and intermediate results persist in the sandboxed workspace for the duration of the task.

**Q21. What happens when context approaches the window limit?**
(blog) Earlier observations are compressed/summarized — but the team's guidance is that this is a cache-breaking event to be planned, not a silent fallback. There is no published automatic compaction threshold.

**Q22. What is the relationship between memory and caching?**
(blog) Stable memory (system prompt, tool definitions, initial instructions) is deliberately cached; changing memory (observations) is appended past breakpoints. Memory placement is a caching decision, not just a content decision.

**Q23. Does Manus persist state across sessions?**
(undocumented) No public cross-session persistence design.

## 1.5 Failure handling & recovery

**Q24. How does Manus handle tool/command failures?**
(blog) A failed action produces an error observation that is appended to context like any other observation; the agent re-plans and retries from that state. There is no published automatic retry ladder.

**Q25. What role does the VM sandbox play in recovery?**
(public) Isolation is the failure-containment strategy: a crashed browser or runaway command cannot take down the agent process or the user's machine, and the workspace survives so the agent can recover from the last good state.

**Q26. How does Manus deal with provider/API failures?**
(blog) Mostly by prevention: stable prefixes → cache hits → fewer requests → fewer rate limits (429s). The blog explicitly advises pacing requests and switching providers when throttled, but publishes no retry policy numbers.

**Q27. Does Manus have a documented retry policy?**
(undocumented) No retry counts, backoff schedules, or escalation ladders are published.

**Q28. How does the user learn about failures?**
(public) Through the live VM view and the final result. Mid-task failure messaging is undocumented.

## 1.6 Testing & evaluation

**Q29. How does Manus evaluate its agent?**
(blog + public) Real-task success on user workloads plus benchmark tasks (e.g., GAIA-style general-assistant tasks at launch). The blog emphasizes *production metrics* — especially KV-cache hit rate — as the continuous evaluation signal.

**Q30. What does the blog recommend as the first eval metric?**
(blog) KV-cache hit rate: it is measurable on every production run and predicts cost, latency, and stability problems before success-rate metrics move.

**Q31. How did Manus validate its framework rewrites?**
(blog) "Stochastic Graduate Descent": rebuild the loop, run the same task corpus, keep the rebuild only if behavior does not regress. This is an A/B eval harness over loop designs.

**Q32. Does Manus publish its test suite?**
(public) No open-source test harness is published (the OpenManus community reimplementation has its own tests, but that is not Manus's code).

**Q33. What testing practice is transferable?**
(blog) Instrument cache hit rate per turn in production; use its drop as an alert condition. This is the closest Manus comes to a documented "test."

## 1.7 Planning & delegation

**Q34. How does Manus plan?**
(public) It decomposes the task at the start and keeps the plan in context; the plan is revised as observations arrive (re-planning is part of the loop, not a separate phase).

**Q35. When does Manus delegate to sub-agents?**
(public) For independent parallel work streams (research, code execution, file handling). The main agent consolidates their outputs. Parallelism is used when sub-tasks are independent; sequential otherwise.

**Q36. Is delegation cost-aware?**
(blog) The blog's caching discipline implies delegation decisions are made with context cost in mind, but no explicit delegation-cost policy is published.

**Q37. Does the user approve plans?**
(public) Manus executes autonomously; there is no documented plan-approval gate (unlike Claude Code's plan mode / Codex's on-request approvals).

## 1.8 Human-in-the-loop & permissions

**Q38. Does Manus ask for permission before actions?**
(public) No granular per-action permission prompts are documented. Manus is an autonomous cloud agent; supervision happens by watching the live VM view, not by approving individual tool calls.

**Q39. How does the user interact during a run?**
(public) Task submission up front, live view during execution, final artifact at the end. Interruption controls exist in the product UI (stop), but no per-step approval flow is documented.

**Q40. How are credentials handled?**
(public) Users configure credentials/API keys; the VM isolates them from the agent's web-visible context. Details are undocumented.

## 1.9 Security & sandboxing

**Q41. Where does Manus execute code?**
(public) In per-session cloud VMs with browser + terminal access — the user's machine is never the execution environment.

**Q42. What does the VM contain?**
(public) A workspace filesystem scoped to the task, browser automation targets, and command execution. Network access is a tool the agent uses, not an ambient capability.

**Q43. How does Manus defend against prompt injection from web content?**
(blog, partial) The blog's determinism discipline (stable prefix, controlled breakpoints) is their published defense posture: context is engineered to be predictable. A specific injection-defense policy is not published.

**Q44. Is per-session isolation documented?**
(public) Manus markets sandboxed per-task environments; exact isolation boundaries are not published.

## 1.10 Observability

**Q45. What metrics does Manus track in production?**
(blog) KV-cache hit rate (top), per-turn latency, cost per turn, and task success. The blog presents these as the core dashboard for an agent product.

**Q46. How is progress shown to the user?**
(public) Live screen/action feed of the VM in the web UI.

**Q47. What debugging method does the blog recommend?**
(blog) Find where cache misses occur — that locates the context instability. Context assembly is the primary debugging surface for agent behavior.

## 1.11 Skills / plugins / MCP

**Q48. Does Manus support MCP?**
(public) Manus's 2025 platform announcements include MCP support for connecting external tools; details are thin and product-side rather than documented in an engineering reference.

**Q49. Does Manus have skills?**
(public) Later 2025 releases introduced reusable task templates/skills in the product; the blog predates most of this. No SKILL.md-style open format is published.

**Q50. Does Manus have a plugin system?**
(public) An app/extension ecosystem was announced alongside the general agent; engineering docs are not public.

## 1.12 Configuration & customization

**Q51. How is Manus configured?**
(public) Via the web product: user profile, custom instructions, connected accounts, tool toggles. There is no local config file.

**Q52. Can users provide standing instructions?**
(public) Yes — personal instructions/context provided by the user load at session start. Per the blog's own rules, this user context should sit in the stable prefix zone so it is cacheable.

**Q53. What can't be configured?**
(undocumented) Model selection, retry behavior, and sandbox settings are not user-configurable in documented form.

---

# 2. Hermes

> "Hermes" is ambiguous and the repo contains both meanings, so this section covers both:
> **2a. NousResearch Hermes** — an open model family trained for function calling, with a public tool-calling prompt format repo (github.com/NousResearch/hermes-function-calling).
> **2b. Hermes Agent** — the open-source "Personal AI Agent" framework (v0.17.0, Python + TS) vendored in this repo at `.research/hermes-agent-main/`, `external/hermes-agent/`, and `references/hermes-agent/`. Earlier repo work compared it to Nexus in `docs/HERMES_COMPARISON.md` (historical; see `docs/research/HARNESS_LANDSCAPE_2026-07.md` for the current landscape). Answers for 2b are grounded in the vendored source and docs.

## 2a. NousResearch Hermes — function-calling models

**Q1. What is Hermes in the model sense?**
NousResearch's Hermes line is an open-weight chat model family (Hermes 1–4, and their function-calling variants) that Nous fine-tuned for tool use. The public repo `NousResearch/hermes-function-calling` demonstrates a prompt-level tool-calling format plus supporting utilities.

**Q2. What message format does the repo use?**
ChatML: messages with explicit `system` / `user` / `assistant` / `tools` roles. ChatML's explicit role tags are what make the tool-calling sections parseable by the model and by code.

**Q3. How are tools declared in the prompt?**
A `<tools></tools>` XML block inside the messages carries JSON function signatures: `name`, `description`, and `parameters` as a JSON Schema. Example: `<tools>{"function": {"name": "get_current_weather", "description": "...", "parameters": {...}}}</tools>`. The model is trained to emit a tool call as a JSON object naming the function and its arguments.

**Q4. What does `prompter.py` do?**
It builds the system prompt from a YAML template plus formatted variables — keeping the *structure* of the prompt deterministic while allowing content injection. This mirrors the "stable scaffold, variable content" pattern from Manus's context engineering.

**Q5. What does `schema.py` do?**
It defines Pydantic models for the tool-call payloads and validates the model's emitted arguments before they are executed — a client-side validation layer that rejects malformed tool calls instead of running them.

**Q6. What does `jsonmode.py` do?**
It forces JSON output for tool calls (a constrained decoding/formatting helper), reducing the chance the model emits free-text instead of a parseable tool call.

**Q7. What is the repo's signature guidance line?**
"Don't make assumptions about what values to plug into functions." The model is trained to *ask the user* for missing required arguments rather than inventing values — the flip side of hallucinated tool arguments.

**Q8. What does Hermes prove about tool use?**
That function calling can be *prompt-engineered and trained into open models*: an XML-tagged tool list + JSON Schema signatures in a ChatML prompt, with client-side validation, is a complete tool-calling stack without any proprietary API feature.

**Q9. What is the failure mode this format guards against?**
Malformed tool calls (unparseable JSON, wrong arg names/types). The defense is layered: trained format → JSON mode enforcement → Pydantic validation at the client.

**Q10. Where does Hermes function calling fit vs. native tool calling?**
Native API tool calling (OpenAI/Anthropic/DeepSeek) handles the same job server-side; the Hermes approach is what you need when the model is an open-weight model accessed via a plain chat endpoint (which is exactly the situation Nexus's providers handle for 40+ backends).

## 2b. Hermes Agent — the framework

**Q11. What is Hermes Agent?**
(hermes-agent-main README) An open-source "Personal AI Agent": one core agent loop exposed across 20+ messaging surfaces (Telegram, Discord, Slack, Signal, Matrix, WhatsApp, email, SMS, …) with a plugin ecosystem, multi-instance profile isolation, MCP support, and a kanban/chronos task layer. Version 0.17.0 in the vendored copy.

**Q12. What is the agent loop?**
A shared core loop (LLM call → tool call → observation) reused by every gateway surface; `delegate_task` spawns sub-agents with leaf/orchestrator roles. Task boards (kanban) and scheduled jobs (chronos) sit on top of the same loop.

**Q13. How does Hermes structure prompts per model?**
From the edgecrab prompt-dispatch analysis (which reverse-engineers Hermes's `prompt_builder`): Hermes injects `TOOL_USE_ENFORCEMENT_GUIDANCE` for gpt/codex/gemini/gemma/grok families, uses the `developer` role for gpt-5/codex, and applies model-family guidance blocks that patch known failure modes (early stopping, narration instead of tool calls, side-effect claims without calls). Anthropic models get no extra enforcement (native tool calling).

**Q14. What is HERMES_HOME?**
The per-profile config/data home. A profile is "just a HERMES_HOME directory": isolated config, secrets, plugins, skills, MCPs. `get_hermes_home()` vs `display_hermes_home()` distinguishes real path from display path (relevant when the real path differs, e.g., Docker).

**Q15. How do profiles work?**
Multi-instance profiles with fully isolated HERMES_HOME dirs; TUI/profile builder can create/switch/delete profiles; model, MCPs, and skills are written per profile (`_write_profile_model`, `_save_mcp_server`). Env overrides like `HERMES_HOME` are the runtime switching mechanism.

**Q16. How does the plugin system work?**
`PluginContext` + `register_tool()`; lifecycle hooks: `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`, CLI command registration; discovery from multiple plugin directories. 18 plugin categories in the vendored tree. `HERMES_HOME`-level plugins override built-ins (e.g., model-provider plugins at `$HERMES_HOME/plugins/model-providers/<name>/`).

**Q17. How are model providers handled?**
29 providers, cloud-API focused, plugin-based: `plugins/model-providers/README.md` documents per-user overrides under `$HERMES_HOME/plugins/model-providers/<name>/`, with provider-specific env vars and config (e.g., `HERMES_<PROVIDER>_*`).

**Q18. What is the tool system?**
AST-based auto-discovery registry (tools found by parsing the codebase) rather than Nexus's explicit BaseTool ABC registry — per the historical `docs/HERMES_COMPARISON.md`. Tools can be registered dynamically by plugins via `register_tool()`.

**Q19. What are Hermes's memory providers?**
8 memory providers; `plugins/memory/supermemory` shows the pattern: a provider config file (e.g., `$HERMES_HOME/supermemory.json`), env-driven setup, and pluggable backends behind one memory interface.

**Q20. How does the gateway work?**
20+ platform adapters (Telegram, Discord, Slack, Signal, Matrix, WhatsApp, DingTalk, WeCom, Feishu, QQ Bot, iMessage, email, SMS, …) all drive the same core agent loop; multi-gateway kanban dispatch is configurable (`HERMES_KANBAN_DISPATCH_IN_GATEWAY=false`).

**Q21. How does MCP work in Hermes?**
A structured MCP catalog: `mcp_config.json`, server registration, requirement checking, auto-discovery, and install from catalog URLs — more advanced than Nexus's catalog-only state at the time of the comparison report (Nexus has since implemented `mcp/catalog.py`).

**Q22. How does Hermes handle failures?**
(session-lifecycle.md) Consecutive restarts are counted in a JSON file (`{HERMES_HOME}/restart_counts.json`); repeated restarts trigger escalation rather than looping forever. RCA docs in-tree (e.g., `rca-ssl-cacert-post-git-pull.md`) show post-incident mitigations: preflight checks with explicit bypass env (`HERMES_SKIP_SSL_GUARD=1` for sandboxed/trusted environments), CA bundle env (`HERMES_CA_BUNDLE`).

**Q23. How does chronos (scheduled tasks) handle failure?**
(chronos-managed-cron-contract.md) Gateway replicas share one HERMES_HOME; a managed lease ensures exactly one replica runs each cron job — a distributed lock pattern to prevent duplicate execution.

**Q24. What security model does Hermes have?**
(network-egress-isolation.md) Network egress isolation is documented as a Docker-based containment pattern (`HERMES_UID`/`HERMES_GID`/docker compose). The comparison report summarizes: Hermes relies on approval gates and guardrails, where Nexus (at that time) had command risk scoring, patch ledger, rollback, and a logic prover.

**Q25. How does Hermes test itself?**
~1,688 test files with subprocess-per-test isolation, hermetic environment (credential stripping, isolated temp dirs, deterministic TZ/locale), 30s test timeouts, and a change-detector that prevents tests from being silently modified. This discipline (hermeticity, timeouts, subprocess isolation) was one of the highest-impact lessons Nexus adopted (tests/conftest.py hermetic isolation).

**Q26. How do skills work?**
A skills hub at `$HERMES_HOME/skills` (`tools/skills_hub.py` binds `SKILLS_DIR = HERMES_HOME / "skills"` at module import — a noted seam: hub-skill install can't use the HERMES_HOME override without a subprocess re-import). Skills are per-profile and installable from a hub; `google_meet` skill shows the pattern (env-driven config, timeout handling like `HERMES_MEET_LOBBY_TIMEOUT`, status reporting with leave reasons).

**Q27. How does Hermes handle secrets?**
Per-profile secret scope inside HERMES_HOME (profile routing doc); env-based credentials in `~/.hermes/.env`-style files per skill; Docker HOME pitfall documented (`/opt/data/home` vs `/opt/data`) — the kind of operational gotcha the repo's skills document for users.

**Q28. What is the observability story?**
Plugins: `plugins/observability/nemo_relay` (NeMo-compatible ATIF/ATOF JSONL/JSON export, incl. subagent export modes `embedded`/`all`) and `plugins/observability/langfuse` (public/secret keys, base URL, sample rate, max chars). Observability is plugin-provided, not core.

**Q29. How is Hermes configured?**
Per-profile `config.yaml` + env vars (`HERMES_*` family, e.g., `HERMES_NEMO_RELAY_PLUGINS_TOML`), `.env` files, and plugin TOMLs (e.g., `.nemo-relay/plugins.toml`). Env var names are stable per feature area.

**Q30. How does Hermes handle multi-agent work?**
`delegate_task` with leaf/orchestrator roles — a single delegation primitive, no consensus/DAG/swarm/blackboard primitives (Nexus's Hive engine has those; the comparison report lists them as a Nexus advantage).

**Q31. What platforms does Hermes target for local models?**
Primarily cloud APIs; local model support is secondary (unlike Nexus's local-first stance with LM Studio/Ollama/llama.cpp backends).

**Q32. What are Hermes's desktop/TUI surfaces?**
TUI (TypeScript) and Desktop app; desktop plugins live at `$HERMES_HOME/desktop-plugins/<name>/plugin.js` ("the disk door").

**Q33. How does Hermes do subagent telemetry?**
NeMo relay export modes cover nested subagent traces (`nested-subagent-atif-{session_id}.json`, `embedded` vs `all`), showing trace propagation across delegation.

**Q34. What is the Docker deployment model?**
Full Dockerfile + docker-compose + .dockerignore + hadolint, multi-arch considerations, HERMES_HOME mounted at `/opt/data`, HOME remapped to `/opt/data/home`.

**Q35. What did Nexus adopt from Hermes?**
(hermes comparison report) Plugin system with lifecycle hooks + trust model, hermetic test infrastructure, profile system (`nexus_path/`, `profiles.py`), additional gateway platforms (Slack, Signal), MCP server catalog (`mcp/catalog.py`), Docker support. **Wait** — that report is historical (June 2026) and its "actions" are marked as already implemented; current status should be verified against the live codebase before citing.

**Q36. What does Hermes lack that Nexus has?**
(comparison report) World model / command risk scoring, cognition & reasoning stack (adaptive memory graphs, zero-token compression, self-improvement), Hive multi-agent orchestration (consensus/DAG/swarm/blackboard), safety infrastructure (logic prover, evidence ledger), local model sovereignty.

**Q37. How does Hermes handle tool-call validation?**
(Contrast with Nous Hermes schema.py — in the framework, validation is done in the tool registry/plugin layer; specific validation depth is not separately documented in the vendored tree.)

**Q38. What concurrency controls exist?**
Multi-gateway kanban dispatch toggle and managed cron leases (exactly-one executor) — the framework's main concurrency mechanisms.

**Q39. How does Hermes isolate plugin state for testing?**
(middleware README) One HERMES_HOME per plugin enablement test; documented `HERMES_HOME=/tmp/...` patterns for isolated local testing of plugins.

**Q40. What are Hermes's install/update mechanics?**
A full git checkout under `$HERMES_HOME/hermes-agent`; documented update workflow; profile keeps itself updated from the checkout (README/CONTRIBUTING).

**Q41. What is the Hermes skill-authoring format?**
SKILL.md markdown with env-documented setup sections (the `xurl` skill demonstrates Docker HOME pitfalls and setup commands in the SKILL body) — similar spirit to Nexus's SKILL.md frontmatter but less standardized (Nexus formalized frontmatter: name/description/categories).

**Q42. What failure-recovery primitives exist for LLM calls?**
(undocumented in vendored tree) No explicit retry ladder documentation; the plugin lifecycle hooks (`pre_llm_call`/`post_llm_call`) are the extension point where retries/observability would be injected (e.g., langfuse plugin).

**Q43. What does the Hermes profile-builder design document say about MCP profiles?**
(design/profile-builder.md) Profiles store MCP servers via `mcp_config._save_mcp_server` + `/api/mcp/catalog`; per-profile MCP catalog access; backend E2E tests with isolated HERMES_HOME are the acceptance criteria.

**Q44. What is the Hermes philosophy vs Nexus's?**
(comparison report) Hermes: "Personal AI Agent" — multi-surface, plugin-extensible, cloud-API oriented. Nexus: "OS of Intelligence" — local-first, sovereign, self-evolving, safety-centric.

**Q45. How does Hermes handle scheduled/background work?**
Chronos (managed cron) with gateway-replica lease coordination; kanban boards for task tracking; `HERMES_KANBAN_*` env controls.

**Q46. What secret hygiene practices does Hermes document?**
Secret scope per profile; env-file conventions per plugin/skill; the Google Meet skill's `HERMES_MEET_REALTIME_KEY` in `~/.hermes/.env`; remote-node bearer tokens persisted in workspace dirs with explicit approve flows (`hermes meet node approve`).

**Q47. What testing isolation does Hermes enforce at CI level?**
Credential stripping from env, isolated temp dirs, deterministic TZ/locale, subprocess-per-test, 30s timeouts, change-detector (tests may not be modified without detection). Source: vendored CONTRIBUTING/testing docs.

**Q48. Does Hermes have a web dashboard?**
(design docs) Yes — a dashboard surface that writes profiles, models (`_write_profile_model`), and MCP servers via APIs; the profile-builder doc defines its seams and E2E tests.

**Q49. What is the Hermes network model?**
Egress isolation by default in container deployments; preflight SSL checks; documented bypass envs are labeled "intended only for sandboxed or managed-trust environments" — an explicit trust-tier model.

**Q50. What is Hermes's version maturity?**
v0.17.0 vendored, ~1,688 test files, 18 plugin categories, 29 model providers, 8 memory providers, 20+ platforms — a mature, heavily-tested framework whose plugin/hook/test discipline is the main transferable lesson for Nexus.

---

# 3. DeepSeek

> DeepSeek is a model/API provider, not an agent framework. The agent loop lives entirely on the client side. This section documents what DeepSeek's official API docs (api-docs.deepseek.com: error codes, tool calls, strict mode, thinking mode, pricing/context caching) tell an agent builder, and how Nexus consumes it.

## 3.1 Agent loop & orchestration

**Q1. Does DeepSeek provide an agent loop?**
No. DeepSeek serves LLM APIs only (deepseek-chat, deepseek-reasoner). The agent loop — call → tool_calls → execute → append results → repeat — must be built by the host (Nexus's `orchestrators/v5` loop, for example).

**Q2. What is the documented tool-call loop?**
(api-docs tool calls guide) The model emits `tool_calls` in an assistant message; the client executes the tools; tool results are returned as `tool` role messages; the model continues. The guide emphasizes that the *model never executes tools* — the client does.

**Q3. Does the loop support parallel tool calls?**
Yes — a single assistant response can contain multiple `tool_calls`; the client should execute them (in parallel where possible) and return results in order.

**Q4. How does thinking mode interact with the loop?**
Since V3.2, tool use works inside thinking mode: the model can reason (`reasoning_content`) and emit tool calls; the docs detail how `reasoning_content` is exposed separately from the final content, and clients must include it in the next request to preserve the thinking chain.

**Q5. Is there a server-side agent mode?**
No. Everything beyond the chat completion is client responsibility — a key contrast with Claude Code/Codex/Manus which ship full loops.

## 3.2 Tool use & function calling

**Q6. How are tools declared?**
Standard OpenAI-compatible `tools` array with JSON Schema `parameters`. The docs stress: put the schema in `parameters`, keep function bodies empty (no implementations in the payload).

**Q7. What is strict mode?**
(beta) A mode where the API server validates tool-call arguments against the JSON Schema server-side. Enable by calling the beta base URL (`base_url=.../beta`) and passing `strict: true` per function. Invalid calls are rejected instead of silently mis-executed.

**Q8. What validation does strict mode add?**
Server-side JSON Schema validation of `arguments` — the *server* (not just client-side Pydantic, as in Nous Hermes's schema.py) rejects non-conforming tool calls, reducing malformed-call failures in production agents.

**Q9. What does strict mode require from the schema?**
The docs require that strict-mode schemas follow JSON Schema subset rules (e.g., `required` fields, no arbitrary defaults) — "strictness" applies to how strictly the schema itself is validated and how arguments are checked.

**Q10. How should tool descriptions be written?**
Follow the official guidance: concise, specific descriptions; place all parameters in `properties`; avoid describing behavior the function doesn't implement.

**Q11. How does the model signal "I need more info"?**
Standard refusal/asking behavior — same as Nous Hermes's "don't make assumptions" rule; the client should surface the model's request for missing arguments rather than auto-filling them.

**Q12. Does DeepSeek support JSON output mode?**
Yes — `response_format={"type":"json_object"}` for constrained JSON output; the prompt must contain the word "json" and an example for best results.

## 3.3 Prompts & context management

**Q13. What message ordering does the API expect?**
system → user → assistant (with tool_calls) → tool results → … The tool results must reference the exact `tool_call_id` returned by the model.

**Q14. Does DeepSeek offer prompt caching?**
Yes — automatic context caching: cache hits are billed ~10× cheaper than misses; caching is disk-level at block granularity, automatic, and requires the *prefix* of the prompt to match (older blocks can be reused even if newer blocks changed).

**Q15. What is the agent-building implication of that caching design?**
(infers the Manus lesson from DeepSeek's own pricing docs) Keep the prompt prefix stable: system prompt, tool definitions, and standing instructions must not change between turns; only append new content. A stable prefix makes most tokens cache hits; a shifting prefix makes every turn a cache miss and multiplies cost.

**Q16. How can the client verify cache effectiveness?**
The `usage` object includes `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` per response — the client can compute the hit rate per turn and use it as a monitoring signal (this is exactly the metric Manus's blog calls the top production metric).

**Q17. What is the recommended system prompt practice?**
Keep the system prompt short and stable; move volatile state (tool results, progress) into later user/tool messages so the cacheable prefix stays intact.

**Q18. Does DeepSeek document a "dynamic boundary"?**
No — that's Claude Code's internal design; DeepSeek's docs only expose the pricing mechanics that make the same boundary pattern economically necessary.

## 3.4 Memory & state

**Q19. Does the DeepSeek API have memory?**
No — stateless per-request API. Memory is entirely the host's job (Nexus's MemoryManager, session history, durable run context).

**Q20. How is state carried across turns in an agent?**
By the client resending history: assistant tool_calls + tool results must be included in subsequent requests; `reasoning_content` from prior thinking turns should be forwarded when continuing a thinking session.

**Q21. How should long agent sessions be compressed?**
Client-side: summarization or truncation of old turns. DeepSeek's docs don't provide an auto-compaction feature; the client must manage the window (Nexus's run-context compression path).

**Q22. What happens when context exceeds the window?**
The API returns a 400 error (context length exceeded); the client must compact/trim and retry. This is a documented failure the agent host must handle explicitly.

## 3.5 Failure handling & recovery

**Q23. What error codes must an agent host handle?**
(api-docs error codes) 400 invalid format/context exceeded; 401/403 auth failures; 402 insufficient balance; 404 model not found (wrong model name — a config error); 413/422 payload too large / invalid body; 429 rate limit / insufficient balance for some plans; 500 internal; 503 service unavailable / overloaded.

**Q24. What is the official advice for 429 (rate limit)?**
Pace requests; if quota is exhausted, **switch to another provider** (DeepSeek explicitly suggests a fallback provider — exactly what Nexus's provider failover adapters implement).

**Q25. What is the official advice for 500/503?**
Retry after a brief wait; the errors are transient. The docs do not specify backoff math — the host should implement exponential backoff with jitter.

**Q26. Which errors are retryable vs fatal?**
Retryable: 429, 500, 503, network timeouts. Fatal/config: 400 (bad request), 401/403 (auth), 404 (model name), 402 (balance). An agent host should classify before retrying (Nexus's reliability package does exactly this classification in its escalation ladder).

**Q27. How should stream interruptions be handled?**
Client-side: treat a dropped stream as retryable for non-streaming requests; for streaming, resume/retry per host policy. No server-side resumption.

**Q28. Does DeepSeek provide a status page?**
Yes (status.deepseek.com) — a documented place the host's error messaging should point users to during 500/503 incidents.

**Q29. What is the timeout guidance?**
The docs recommend generous timeouts (DeepSeek can be slow under load; non-streaming requests may take longer than typical OpenAI calls). Hosts should set per-request timeouts with retry rather than failing fast.

## 3.6 Testing & evaluation

**Q30. Does DeepSeek provide an eval harness?**
No. Evaluation is the host's job.

**Q31. What can strict mode contribute to testing?**
(infers from docs) Server-side schema validation gives deterministic rejection of malformed tool calls — useful for contract tests of tool schemas before they ship to the model.

**Q32. What is the best testable unit in a DeepSeek agent?**
The tool-contract: JSON Schema + prompt description. Changes to schema/description are the main source of tool-call regressions; regression-test them by replaying recorded prompts.

**Q33. How should prompt/context changes be validated?**
Measure `prompt_cache_hit_tokens` before/after: a change that drops hit rate is an economic regression even if accuracy is unchanged.

**Q34. Is there official guidance on eval datasets?**
No. (The team's own blog/research about reasoning models exists separately, but the API docs don't cover evaluation.)

## 3.7 Planning & delegation

**Q35. Does DeepSeek offer planning or multi-agent primitives?**
No. The model can be prompted to produce plans and a host can run multi-agent topologies on it, but nothing is provided server-side.

**Q36. Can DeepSeek models be used as sub-agents?**
Yes — any host multi-agent framework (Nexus Hive, Hermes delegate_task, OpenCode subagents) can target deepseek models per role. Role-specialization (planner vs executor) is a host concern.

**Q37. Are there model-tiering docs (fast vs deep)?**
(api-docs) deepseek-chat (general) vs deepseek-reasoner (reasoning) are the documented tiers; the docs note that thinking-capable models should be used for planning/verification and chat models for fast iterations — a two-tier delegation hint, not a full orchestration spec.

## 3.8 Human-in-the-loop & permissions

**Q38. Does DeepSeek have a permission system?**
No — the API is a bare model endpoint. All permission gating, ask/deny flows, and approval UIs are host-side (Nexus's permission gates, OpenCode permissions, Codex approvals are the agent-host layers that sit on top).

**Q39. How are API keys handled?**
`Authorization: Bearer <key>` header; docs instruct keeping keys server-side and never in prompts. Hosts must avoid logging keys (Nexus's security scan enforces this).

## 3.9 Security & sandboxing

**Q40. What security boundaries does DeepSeek provide?**
Only the API boundary: TLS, key auth, content moderation on the provider side. No sandbox, no tool-execution containment — the host owns that.

**Q41. What is the documented prompt-injection posture?**
Not addressed in API docs beyond general content-moderation; the host is responsible for treating web/tool content as untrusted (the lesson mirrored in Codex's cached-web-search default).

**Q42. How should tool execution be secured?**
Host-side entirely: sandbox, allowlists, risk scoring. DeepSeek provides zero execution environment — an agent host like Nexus must supply the 3-tier sandbox itself.

## 3.10 Observability

**Q43. What telemetry does the API return?**
`usage`: prompt_tokens, completion_tokens, total_tokens, plus `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens` — the key signal for context-cache health (see Q16).

**Q44. What observability must the host add?**
Turn latency, retry counts, error classification, tool success/failure, cache-hit rate aggregation per session — everything beyond the raw usage object.

**Q45. Does streaming include usage?**
Yes, in the final stream chunk when `stream_options={"include_usage": true}` — hosts that want per-turn metrics must enable this.

## 3.11 Skills / plugins / MCP

**Q46. Does DeepSeek ship skills or plugins?**
No — model provider only. Skills/plugins/MCP are host-side (Nexus skills/, plugins/, mcp/).

**Q47. Can DeepSeek power MCP servers?**
As a client model behind any MCP client (Nexus MCPClient, OpenCode, Claude Code with a DeepSeek-compatible gateway) — no provider-side MCP support exists.

**Q48. What is the implication for provider abstraction?**
An agent host should treat DeepSeek as one of many OpenAI-compatible backends behind a common interface — which is precisely Nexus's providers/ layer (40+ providers) and why DeepSeek's "switch provider on 429" advice is practical there.

## 3.12 Configuration & customization

**Q49. What request parameters does DeepSeek document?**
temperature, top_p, max_tokens, presence/frequency penalties, stream, response_format, tools, tool_choice, and (beta) strict per-function schema flags. `tool_choice` controls forced vs free tool selection.

**Q50. What is the base-URL configuration?**
Default `https://api.deepseek.com` (v1-compatible); strict mode requires the `.../beta` base URL — a config-level switch, and a good example of why agent hosts need per-provider endpoint/feature configuration (Nexus NexusConfigLoader).

**Q51. What model names are stable?**
`deepseek-chat` and `deepseek-reasoner` (aliases that track latest versions) — stable aliases are valuable for agent configs that must not break on provider version bumps.

---

# 4. Claude Code

> Anthropic's terminal agent. Unlike Manus/DeepSeek, Claude Code is fully documented (code.claude.com/docs): permissions, hooks, memory, settings, errors. Its prompt-construction internals are additionally well documented by third-party source analysis (blog.lienjack.com prompt-construction analysis; codex.cadences.app 18-section breakdown) that corroborate each other and the docs.

## 4.1 Agent loop & orchestration

**Q1. What is the Claude Code loop?**
Interactive agent loop: user input → per-turn context assembly (system prompt sections + memory + git/env state + message history + tool results) → model call → tool calls → results fed back into messages → repeat. Context assembly happens at the *entrance of every turn*, not once per session.

**Q2. What modes exist?**
Plan mode (model proposes, doesn't execute), acceptEdits, manual mode, and auto mode (permission classifier). Modes are runtime switches that change both toolset exposure and permission behavior.

**Q3. Does Claude Code run sub-agents?**
Yes — the Task tool spawns subagents from markdown files (name, description, tools, model in frontmatter). Subagents get their own context; hooks fire inside subagents too, with `agent_id`/`agent_type` in hook input. Coordinator mode strips the main agent's toolset to Agent + TaskStop + SendMessage.

**Q4. What is compaction?**
Automatic/`/compact` summarization of history to fit the window; compaction also clears the system-prompt section cache and fires a `PreCompact`-style lifecycle (via hooks: SessionStart matcher "compact" is a documented pattern for reminding the model after compaction).

**Q5. Is the loop stateful across sessions?**
Sessions resume via `--continue`/`--resume`; per-project state (allowed tools, trust settings) persists in `~/.claude.json`. No durable goal/state machine is published — recovery is human-visible, not machine-recoverable like Nexus's.

## 4.2 Tool use & function calling

**Q6. What native tools does Claude Code expose?**
Bash, Edit, Write, Read, Glob, Grep, TodoWrite, Task, WebFetch, WebSearch, MCP tools, plus mode-specific sets (plan mode proposes; simple mode strips to Bash+Read+Edit). Tool descriptions are part of the cached prompt prefix.

**Q7. How does tool denial work?**
A bare-tool-name `Deny` rule (e.g., `Bash`) **removes the tool from the model's context entirely** — the model cannot even see it (except EndConversation). Scoped rules like `Bash(rm *)` don't remove the tool; they block matching invocations.

**Q8. What is the permission hierarchy?**
Tiered: Allow / Ask / Deny, with scoped rules (`Bash(rm *)`, `Edit(specific-file)`, `Read(.*\.env.*)`), ordered most-specific-first semantics, and per-project/per-user settings layers. Rules are enforced by Claude Code's runtime, not by the model.

**Q9. What is auto mode?**
A permission mode where a classifier (not the model) decides ask/allow for each tool call; unknown-safety actions trigger the user prompt. Deny rules are always respected; auto only converts "would ask" into "allowed."

**Q10. How are tool results sized?**
Tool outputs stream into context; the CACHED_MICROCOMPACT feature auto-clears old tool results to bound context growth — a documented context-budgeting mechanism for the tool loop.

**Q11. What is the tool-error contract?**
Tool failures return error text into context for the model to react to; there is no automatic host-side retry of tool calls (retries are model-driven or hook-driven via PostToolUse).

## 4.3 Prompts & context management

**Q12. How is the system prompt built?**
`getSystemPrompt()` assembles an 18-section prompt in fixed order: first 12 sections static/cacheable (identity, rules, tool guidance), then a sentinel `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__`, then 6 per-session sections (working dir, date, git state, CLAUDE.md, memories, MCP instructions). Ordering is deliberate: identity at the top, user instructions (CLAUDE.md) at the bottom — primacy/recency.

**Q13. Why the boundary?**
Prompt caching keys on prefix; everything above the boundary stays byte-stable and hits the cache (~70% of the system prompt reused per turn), everything below changes per session. The source has explicit warnings about moving sections across the boundary.

**Q14. What is the memoization design?**
`systemPromptSection(name, compute)` computes each section once, cached until `/clear` or `/compact`. A deliberately-named `DANGEROUS_uncachedSystemPromptSection` recomputes per turn — the DANGEROUS prefix is a warning that it breaks the cache.

**Q15. What else is per-turn?**
Attachments (files, diagnostics) recompute each turn with a 1s timeout; git status/date/env are in the dynamic zone; tool results and compressed summaries feed the next turn's messages.

**Q16. How does caching economics work?**
CLAUDE.md is prompt-cached (content-addressed): full price once per session, cache-read price for ~5 minutes afterward; editing CLAUDE.md invalidates the cache. The docs explicitly tell users: keep CLAUDE.md lean for context space, but don't ration lines purely for cost.

**Q17. What is the user-visible prompt tooling?**
`/context` (what memory/context is loaded), `/config`, `/status`; CLAUDE.md delivered as a **user message after the system prompt**, not inside it.

## 4.4 Memory & state

**Q18. What is the CLAUDE.md hierarchy?**
Load order (later = higher priority): managed `/etc/claude-code/CLAUDE.md` (org policy) → user `~/.claude/CLAUDE.md` → project `CLAUDE.md`/`.claude/CLAUDE.md` → `CLAUDE.local.md` (private). Directory walk from CWD up to root; files closer to CWD load last (highest priority).

**Q19. What are rules?**
`.claude/rules/*.md` modular instruction files; path-scoped rules have `paths` frontmatter and load **only when the model reads a matching file** (context-saving); unconditional rules load at launch. `@include` directives allow recursion up to depth 5 with cycle protection.

**Q20. What is auto memory?**
Claude writes `~/.claude/projects/<project>/memory/MEMORY.md` itself: build commands, debugging insights, preferences. First 200 lines / 25KB of MEMORY.md load every session; the rest is topic files loaded on demand via normal Read. Over-limit writes succeed but return an error telling the model to rewrite the index (hard truncation on next load).

**Q21. Is CLAUDE.md enforced?**
No — it is context, not configuration. The docs state this explicitly: to *block* an action, use a PreToolUse hook. Guidance: <200 lines per file, structured with headers/bullets, most-specific-last ordering.

**Q22. When is memory re-read?**
CLAUDE.md is not re-read from disk each turn; edits apply at next session or after `/compact`/`/memory`. The memory cache is cleared on compaction, worktree changes, settings sync, and `/memory`.

**Q23. What protects binary files from loading?**
A whitelist of 100+ text extensions prevents images/PDFs from entering context (documented in the source analysis).

## 4.5 Failure handling & recovery

**Q24. What is the retry policy?**
Transient failures retry **up to 10 times with exponential backoff** before surfacing an error; the spinner shows `Retrying in Ns · attempt x/y`. The retry budget applies to server errors, overloaded (529), request timeouts that arrive before any streaming, and dropped connections.

**Q25. What happens on mid-response failures?**
If a server error/drop occurs after the model completed a block of text or a tool call but before finishing: Claude Code **keeps what was completed**, shows "The response above may be incomplete", still runs completed tool calls, and continues the turn from their results (behavior since v2.1.199; older versions discarded partial output).

**Q26. What about stalled streams?**
No data for 20 seconds → "Waiting for API response · will retry in …" countdown; then abort and re-issue at most once (outside the 10-attempt budget). If a stall repeats after thinking but before any text/tool call: "The response stalled before a response was produced."

**Q27. What about double-execution risk?**
For failures after a tool call completed, Claude Code deliberately does NOT re-run the request (would double-execute tools); it continues from the tool results — a documented idempotency decision.

**Q28. What about context overflow?**
`prompt is too long` triggers automatic compact-and-retry; `CLAUDE_CODE_AUTO_COMPACT_WINDOW` configures the trigger (clamped ≥100k tokens). Gateway-enforced limits that don't match Anthropic wording need manual `/compact`.

**Q29. What retry knobs exist?**
`CLAUDE_CODE_MAX_RETRIES` (budget cap; with <3 allowed, the spinner label logic adapts), `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`. Error categories (rate-limited, overloaded, server error, timed out, connection failed) are surfaced in messages so the user knows what to do.

**Q30. What diagnostics exist?**
`/doctor` (session health, MCP status, context usage), `claude doctor` (install-level), `/terminal-setup`, `/mcp`, `/status`, `/hooks` (browser for hooks + trust state).

**Q31. How do gateway/proxy failures surface?**
Distinct messages: Connection refused / ENOTFOUND / TLS / 401 invalid token / 403 WAF blocking (prompt bodies look like XSS to WAFs — documented!), empty 200 responses, apiKeyHelper failures. Each has a documented fix path.

**Q32. What is the documented "waiting" behavior?**
A "Waiting for API response" banner appears at 20s idle; if it reappears on every attempt, treat as network issue — a failure-classification rule for hosts.

## 4.6 Testing & evaluation

**Q33. How does Claude Code test itself?**
Anthropic does not publish Claude Code's eval harness. Public documentation covers *user-side* verification: `/init` to generate CLAUDE.md (build/test commands), hooks to enforce test runs (e.g., PostToolUse edit→format; PreToolUse Bash check "verify lint and type-check before committing").

**Q34. What is the documented test-enforcement pattern?**
Hooks, not prompts: "Use hooks instead of CLAUDE.md for linting rules — LLMs are expensive compared to linters." A PreToolUse prompt-hook evaluates a condition (block/remind/warn) or a command-hook runs a checker; this is the documented quality-gate pattern.

**Q35. How are hooks themselves tested?**
The statusline-setup troubleshooting docs show the pattern: feed mock JSON input to the script outside Claude Code, verify trust prompts, check stdout vs stderr, add fallbacks for optional fields — unit-test hooks as shell scripts with fixture JSON.

**Q36. What is the community testing story?**
Plugins/skills encode workflows (`/verify` → type check → spec walkthrough; `/grill` review through 7 lenses; TDD skills) — workflow-level "tests" packaged as skills. Claude Code ships no built-in benchmark runner.

**Q37. How does `/init` generate project memory?**
`/init` explores the codebase (with a subagent in the interactive multi-phase flow), discovers build/test commands, conventions, and writes/improves CLAUDE.md — the documented onboarding-eval loop (if instructions are wrong, add a rule; the "got it wrong twice → add a line" rule).

## 4.7 Planning & delegation

**Q38. What is plan mode?**
Manual activation: the model proposes a plan instead of executing; ExitPlanMode surfaces the plan for approval; hooks can fire on ExitPlanMode (e.g., inject context or enforce plan format).

**Q39. What are subagents used for?**
Delegating research/exploration/parallel analysis to keep the main context clean; they run in separate contexts and return distilled findings. Skills like `/grill` spawn review agents automatically; `/implement` spawns research agents.

**Q40. How are subagents declared?**
Markdown files with frontmatter (name, description, tools, model); hooks fire inside subagent tool calls with agent_id/agent_type; the same settings/hook stack applies (with trust).

**Q41. Is there a delegation policy?**
No documented cost/parallelism policy — the model decides when to use Task based on tool descriptions (prompt-driven, like most frameworks).

## 4.8 Human-in-the-loop & permissions

**Q42. What is the permission UI?**
`/permissions` shows/edits rules; `/config` for settings; status bar shows mode (e.g., "manual mode on"); desktop notifications via Notification hook when input is needed.

**Q43. What permission actions exist?**
Allow once / allow always / deny at the prompt; rules persist in settings (user/project/local). Scoped rules like `Bash(rm *)` block only matches; bare-tool Deny removes the tool from context.

**Q44. What runs before trusting a folder?**
A first-run trust prompt gates project-level settings/env blocks; untrusted folders don't apply project config. Worktree-aware settings resolution keeps one config per repo.

**Q45. How are destructive actions gated by default?**
Via default permission presets (destructive tools Ask by default) and auto-mode classifier for anything not explicitly allowed/denied; hooks can hard-block regardless of model behavior (`PreToolUse` deny).

## 4.9 Security & sandboxing

**Q46. Does Claude Code sandbox commands?**
No OS-level sandbox: Bash runs on the host with the user's permissions. The control layers are: permission tiers, deny-removes-tool, hooks (PreToolUse can deny), and auto-mode classifier. This is a documented design choice: enforce in the loop, not the OS.

**Q47. What hook-security mechanisms exist?**
`allowedHttpHookUrls` allowlist for HTTP hooks (wildcards; empty = block all), `httpHookAllowedEnvVars` (which env vars may be interpolated into hook headers), `disableAllHooks` (can't disable managed hooks), hook trust review for new/changed hook definitions.

**Q48. What is the managed-policy model?**
Managed settings (org-admin) can force hooks/permissions that user settings can't disable (`allowManagedHooksOnly`, managed marketplace restrictions) — an enterprise security layer.

**Q49. What about secrets?**
`apiKeyHelper` runs an external command to fetch keys at request time (keeps keys out of settings files); OAuth session stored in `~/.claude.json`; docs warn against putting credentials in hooks/env blocks that get committed.

**Q50. What prompt-injection posture is documented?**
WebFetch content is treated as untrusted data in context; the defense is user-visible provenance + permission discipline on WebFetch/WebSearch, plus hook-based guardrails. No automatic sanitization is documented.

## 4.10 Observability

**Q51. What is the statusline?**
A user-configured command that receives JSON (workspace, model, context_window.used_percentage, cost, etc.) and renders a status line — the documented observability extension point (plus the `%` printf-format-injection gotcha from the community: never use variables as printf format strings).

**Q52. What session visibility exists?**
`/status` (model, gateway, auth), `/context` (memory files, context usage visualization), `/doctor`, session logs; OTel/export is not built in (Enterprise telemetry exists but is not documented as an open feature).

**Q53. How do hooks serve observability?**
PostToolUse hooks can append to an audit log; SessionStart hooks can inject reminders/state; Notification hooks alert on wait states — hooks are the general-purpose telemetry channel.

## 4.11 Skills / plugins / MCP

**Q54. What are Claude Code skills?**
SKILL.md files (frontmatter: name, description, allowed-tools, hooks) loaded on demand when invoked or when the model judges them relevant — task-specific instructions that don't occupy context until used. Skills can carry their own hooks (active for the rest of the session once invoked).

**Q55. What are plugins?**
Installable packages (`/plugin marketplace`, `~/.claude/plugins/`) that bundle agents, MCP servers, skills, and hooks; plugin hooks live in `hooks/hooks.json`; plugin marketplaces can be restricted (`strictKnownMarketplaces`) in managed deployments. Plugins are the distribution unit; skills/agents/hooks are the contents.

**Q56. How does MCP work?**
`.mcp.json` for project-scoped servers; user/local servers in `~/.claude.json`; MCP tools surface with server prefixes; per-server instructions can be injected into context (MCP instructions section); `/mcp` shows connection status (STDIO/SSE).

**Q57. What is the MCP context cost warning?**
Docs warn that MCP servers add tool descriptions to context and can exceed limits — a documented reason to be selective (same warning as OpenCode's docs).

## 4.12 Configuration & customization

**Q58. What is the settings layering?**
`~/.claude/settings.json` (user) → `.claude/settings.json` (project, committed) → `.claude/settings.local.json` (private, gitignored) → managed policy settings (org). Hooks/permissions/statusline/env all live here; settings hot-reload mid-session (ConfigChange hook fires); timestamped backups of config files kept (5 most recent).

**Q59. What slash commands customize behavior?**
`/config`, `/permissions`, `/hooks`, `/init`, `/memory`, `/context`, `/doctor`, `/statusline`, `/compact`, `/clear`, `/rewind`, `/mcp`, plus user-defined commands. `CLAUDE_CODE_*` env vars control retries, auto-compact, output tokens, etc.

**Q60. What is the env-block pattern?**
Settings can define `env` blocks (e.g., for gateway credentials) applied when sessions start — with the documented caveat that they apply only after the first-run wizard and trust prompt.

**Q61. What customization is NOT possible?**
No plugin API for modifying the model loop itself (hooks are the boundary); no custom tools outside MCP/skills; no OS sandbox config. The system prompt's 18-section assembly is internal — the user-facing customization surfaces are CLAUDE.md, skills, hooks, and MCP.

---

# 5. OpenAI Codex

> OpenAI's coding agent: CLI, IDE extension, ChatGPT desktop integration, cloud jobs, and GitHub code review. Everything here is from the official docs (developers.openai.com/codex), which are unusually complete on configuration, sandboxing, hooks, and approvals. Codex and Claude Code are the two best-documented reference points for an agent host.

## 5.1 Agent loop & orchestration

**Q1. What is the Codex loop?**
Interactive agent loop in TUI/IDE/desktop: user prompt → model → tool calls (shell, apply_patch, file ops, web search, MCP, apps) → observations → next turn. `codex exec` runs the same loop non-interactively for pipelines (progress to stderr, final message to stdout).

**Q2. What are the run modes?**
Sandbox modes (read-only / workspace-write / danger-full-access) × approval policies (untrusted / on-request / never / granular) — the two orthogonal axes of the loop's guardrails. Presets: Auto (workspace-write + on-request), read-only, yolo (danger-full-access + never).

**Q3. Does Codex persist goals?**
`features.goals` (stable): persisted goals with automatic continuation — the agent can resume long tasks across sessions. This is a documented persistence feature absent from Claude Code.

**Q4. What is Fast mode?**
`features.fast_mode` + `service_tier = "fast"`: a cheaper/faster inference tier selectable per task; the availability check goes directly to api.openai.com (documented proxy/gateway caveat).

**Q5. How does Codex handle context limits?**
`enable_compression`-style config and a custom `compact_prompt` file (config sample shows `compact_prompt_file`); auto-compaction with a configurable continuation prompt — the host can customize what the agent "remembers" across compactions.

## 5.2 Tool use & function calling

**Q6. What tools does Codex expose?**
`shell` (default, `features.shell_tool`), unified PTY-backed exec (`features.unified_exec`, off on Windows), `apply_patch` (also matches Write/Edit matchers in hooks), file read/write, `web_search` (cached by default), MCP tools (`mcp__server__tool`), apps/connectors (Linear, GitHub, Slack), and GitHub integration.

**Q7. What are tool timeouts?**
`tool_timeout_sec` (default 60s) and `startup_timeout_sec` (default 10s) for spawned agents/tools — documented per-tool timeout configuration (there is an open GitHub issue asking for a larger configurable tool-call timeout for long-running tasks).

**Q8. What is shell_snapshot?**
`features.shell_snapshot` (stable): snapshots the shell environment so repeated commands start fast — an optimization for the tool loop's most common operation.

**Q9. How are tool calls approved?**
Approval policy gates commands; the TUI shows each command with Approve/Deny; `--ask-for-approval never` skips prompts; granular policy auto-rejects whole categories (see 5.8).

**Q10. What is web_search behavior?**
`web_search = "cached"` (default) uses OpenAI's pre-indexed cache instead of live fetching — a documented prompt-injection mitigation (live content treated as untrusted); `"live"` (`--search`) fetches live; `"disabled"` turns it off.

**Q11. What is the exec tool?**
Unified PTY-backed exec tool (`features.unified_exec`) that runs commands with a TTY (interactive programs work); telemetry distinguishes `tool.unified_exec` calls by tty mode; Windows native uses a different execution path.

## 5.3 Prompts & context management

**Q12. What is the AGENTS.md discovery algorithm?**
Global scope: `~/.codex/AGENTS.override.md` else `~/.codex/AGENTS.md` (first non-empty only). Project scope: walk from project root down to CWD; per directory check `AGENTS.override.md`, then `AGENTS.md`, then `project_doc_fallback_filenames` (e.g., TEAM_GUIDE.md); at most one file per directory. Concatenate root→down with blank lines; later files override earlier guidance.

**Q13. What size limits exist?**
`project_doc_max_bytes` (default 32 KiB) caps the combined instruction chain; empty files skipped; hitting the cap truncates the chain (docs advise raising the limit or nesting instructions in directories).

**Q14. How do overrides work?**
`AGENTS.override.md` at any level temporarily replaces the base `AGENTS.md` at that level (remove the override to restore) — a documented temporary-override pattern.

**Q15. What is the `/init` flow?**
`/init` scaffolds a starter AGENTS.md (repo layout, build/test/lint commands, conventions, constraints, done-criteria). The manual recommends: keep it short and practical; add rules only after repeated mistakes; when the agent errs twice, ask for a retrospective and update AGENTS.md — "guidance based on real friction."

**Q16. How does AGENTS.md serve code review?**
Codex Code Review reads `## Code Review Rules` sections from AGENTS.md files (root = repo-wide, nested = service-specific); findings cite the rule that fired; the Codex team itself keeps review rules in its AGENTS.md (e.g., backward-compat wire-protocol rules).

**Q17. What is the model-context advice?**
The prompting docs: give "what good looks like" from prompt or AGENTS.md; keep main AGENTS.md concise and reference task-specific files (planning.md, code_review.md) — the same lazy-loading pattern as Claude Code rules and OpenCode instructions.

**Q18. How are rules/custom prompts handled?**
`rules` (project-local rules, loaded only when project trusted) and custom prompts are documented customization layers alongside AGENTS.md, memories, skills, MCP, subagents — explicitly framed as "complementary, not competing."

## 5.4 Memory & state

**Q19. What memory does Codex have?**
`features.memories` (experimental): agent-written memories loaded as context for future sessions — the Codex counterpart to Claude Code auto memory. AGENTS.md remains the durable human-authored guidance ("memories carry local context forward").

**Q20. How is state persisted across exec runs?**
`history.jsonl` (if history persistence enabled), auth.json, logs/caches under CODEX_HOME; goals persist for auto-continuation; sessions resume in TUI/IDE.

**Q21. What is the AGENTS.md feedback loop?**
The documented pattern: correct the agent → have the agent update AGENTS.md itself so the fix persists → pair AGENTS.md with enforced infrastructure (pre-commit hooks, linters, type checkers) because instructions alone aren't enforcement.

**Q22. Is AGENTS.md re-read per turn?**
Built once per run (TUI: once per session); "there is no cache to clear manually" — restart Codex in the directory to rebuild the chain (per the guide's troubleshooting section).

## 5.5 Failure handling & recovery

**Q23. What happens on tool timeouts?**
Tool execution is bounded by `tool_timeout_sec` (60s default); the model sees the timeout as a tool result and can retry/replan; long tasks need host-level timeout bumps (open issue #11233).

**Q24. How does exec fail?**
`codex exec` exits non-zero on failures; an enabled MCP server with `required = true` that fails to initialize makes exec exit with an error instead of continuing — a documented fail-closed default for required dependencies.

**Q25. What retry policy is documented?**
No explicit LLM-call retry ladder is published (network-level retries are internal); the documented failure surface is approvals, sandbox denials, and tool timeouts — failures surface to the model as tool results.

**Q26. How does the PermissionRequest hook handle failures?**
A `PermissionRequest` hook can allow/deny/abstain on an approval; if multiple matching hooks decide, **any deny wins**; an allow proceeds without the prompt; otherwise normal approval flow — documented deterministic hook decision logic.

**Q27. What happens on untrusted project config?**
Project `.codex/` layers (config, hooks, rules) are ignored when the project is untrusted; user/system layers still load — a documented fail-closed posture for untrusted repos.

**Q28. How are new hooks gated?**
Hooks require trust by exact hash: new or changed hook definitions are skipped until reviewed via `/hooks`; `--dangerously-bypass-hook-trust` opts out for one invocation; managed hooks are trusted by policy and can't be disabled by users.

**Q29. What is the network failure posture?**
Network is off by default in workspace-write; enabling it is explicit (`network_access = true`); `network_proxy` with domain allowlist (deny wins) constrains egress; local/private-network destinations blocked unless explicitly allowed (`allow_local_binding`).

**Q30. What agent-interrupt handling exists?**
`agents.interrupt_message` (default true): a model-visible message is recorded in the agent's context when its turn is interrupted — the interrupted agent knows why it was cut off.

## 5.6 Testing & evaluation

**Q31. How does Codex test/evaluate itself?**
OpenAI runs internal evals (SWE-bench-style and product evals; public knowledge — not in the docs). The docs cover the *user-side* loop: GitHub Code Review with custom rules, and skills that encode verification workflows.

**Q32. What is GitHub Code Review?**
Codex cloud reviews PRs (`@codex review`), applies `## Code Review Rules` from AGENTS.md, cites rules in findings, and applies only the rules covering changed files (nested = service-scoped).

**Q33. What is the documented "test-first" config pattern?**
AGENTS.md should contain exact build/test/lint commands ("Codex will execute these, so accuracy matters"); verification criteria ("what done means") are part of a good AGENTS.md — the instruction chain doubles as the test contract.

**Q34. How are hook scripts tested?**
The hooks guide implies the same fixture-testing pattern as Claude Code (run the script with mock JSON, check exit codes/statusMessage); hook statusMessages show in the UI.

**Q35. Is there a benchmark story?**
Not in official docs; the model cards/eval reports (public knowledge) cover model-level benchmarks, not the CLI's behavior.

## 5.7 Planning & delegation (multi-agent)

**Q36. What subagents ship with Codex?**
Built-ins: `default` (general), `worker` (execution-focused implementation/fixes), `explorer` (read-heavy codebase exploration). Enabled by default (`features.multi_agent`).

**Q37. How are custom subagents defined?**
TOML files in `~/.codex/agents/` (personal) or `.codex/agents/` (project): name, description, instructions, plus any config.toml keys (model, model_reasoning_effort, sandbox_mode, mcp_servers, skills.config). Custom names override built-ins; loaded as config layers for spawned sessions.

**Q38. How is orchestration done?**
The primary agent (or the ChatGPT/Codex host) spawns subagents, routes follow-ups, waits for results, and returns a consolidated response; each subagent thread is inspectable in the UI.

**Q39. What concurrency limits exist?**
`agents.max_concurrent_threads_per_session` (default chosen by Codex; example shows 6) caps concurrently-open spawned threads; `agents.default_subagent_model` and `default_subagent_reasoning_effort` set defaults; explicit spawn values take precedence, then [agents] defaults, then the parent's value.

**Q40. How does the model get chosen for subagents?**
If unset, Codex chooses per task (may favor `gpt-5.6-terra` for fast scans, higher-effort reasoning model for complex work) — documented automatic model selection by task type.

**Q41. Is there a plan mode?**
Yes — plan mode with separate `plan_mode_reasoning_effort` config; `/permissions` can switch to read-only for planning-only sessions.

## 5.8 Human-in-the-loop & permissions

**Q42. What approval policies exist?**
`untrusted` (only known-safe read-only commands auto-run; everything else prompts), `on-request` (model decides when to ask; default), `never` (no prompts; risky), and `granular` — auto-allow/auto-reject per category.

**Q43. What does granular cover?**
Categories: `sandbox_approval`, `rules`, `mcp_elicitations`, `request_permissions`, `skill_approval` — e.g., auto-reject `request_permissions` and skill scripts while keeping normal prompts interactive (fail-closed for categories you don't want).

**Q44. What is auto_review?**
`approvals_reviewer = "auto_review"`: eligible approval requests are reviewed by an automatic reviewer agent instead of surfacing to the user (with `[auto_review].policy` instructions; managed `guardian_policy_config` takes precedence) — a documented delegated-approval layer.

**Q45. What is the approval UI?**
TUI prompts per command; `/permissions` mode switching; notifications for approval-requested events (`tui.notifications` filtering); desktop notifications via `notify` external program (agent-turn-complete event) or built-in TUI notifications (osc9/bel methods, unfocused/always conditions).

**Q46. What commands are auto-approved?**
Under `untrusted`, only known-safe read-only commands run without approval; the docs recommend granular categories and `--sandbox read-only` for plan-only sessions.

## 5.9 Security & sandboxing

**Q47. What is the sandbox model?**
Three levels: `read-only` (no writes, no network), `workspace-write` (default; writes limited to the active workspace, **network off by default**), `danger-full-access` (no sandbox — `--yolo` / `--dangerously-bypass-approvals-and-sandbox`). OS-level enforcement on macOS/Linux/WSL2/Windows.

**Q48. How does the sandbox propagate?**
Commands spawned by the agent (git, package managers, test runners) inherit the sandbox boundary — enforcement covers the whole command tree, not just the direct tool call.

**Q49. What is workspace-write tuning?**
`[sandbox_workspace_write]`: `writable_roots` (extra writable dirs), `exclude_slash_tmp` / `exclude_tmpdir_env_var` (tighten temp handling), `network_access` (opt-in outbound), plus `network_proxy` domain allowlist (allow/deny, deny wins, allowlist by default) and Unix-socket allowlists (`dangerously_allow_all_unix_sockets=false`).

**Q50. What Windows support exists?**
Native Windows sandbox via `[windows] sandbox = "unelevated" | "elevated"` with `sandbox_private_desktop` (default true); WSL2 is the recommended Linux-like path; `command_windows` fields let hooks specify Windows commands.

**Q51. How does web search reduce injection?**
Cached-by-default search returns pre-indexed results instead of fetching arbitrary live content (documented as reducing prompt-injection exposure; live mode only with `--search`/`"live"`); `web_search_cached` legacy toggles map to this.

**Q52. What is the managed/enterprise layer?**
`requirements.toml` (admin-enforced): pin feature flags (e.g., forbid `approval_policy="never"`, force `features.hooks=true`), define managed hooks (`managed_dir` + `windows_managed_dir`), `allow_managed_hooks_only` to ignore user/project/plugin hooks, `guardian_policy_config` for review policy.

## 5.10 Observability

**Q53. What OTel support exists?**
`[otel]` block: environment (dev/staging/prod), exporter (none/otlp-http/otlp-grpc), `log_user_prompt` (redact prompt text unless policy allows) — telemetry is off by default, explicitly enabled.

**Q54. What metrics are emitted?**
`codex.tool.call` counter (tool, success labels), `codex.tool.call.duration_ms` histogram (tool, success), `codex.tool.unified_exec` (tty), plus request/turn metrics — tool-level success/failure telemetry out of the box.

**Q55. What notification channels exist?**
`notify` (external program, e.g., webhooks/desktop toasts, currently `agent-turn-complete` only) vs `tui.notifications` (built-in, filterable by event type) vs `tui.notification_method` (auto/osc9/bel) vs `tui.notification_condition` (unfocused/always) — layered notification design.

**Q56. What logging exists?**
Logs and caches under CODEX_HOME; `--log-level` style debugging; TUI animations/shimmer toggles; `shell_snapshot` state. No statusline-command equivalent (that's Claude Code's pattern).

## 5.11 Skills / plugins / MCP

**Q57. How do skills work?**
`~/.agents/skills` (global) and `.agents/skills` (repo); skills package repeatable workflows/domain expertise; `skills.config` in config/subagent files; skill scripts can trigger approvals (`skill_approval` granular category) — skills are just-in-time instructions + scripts, like Claude Code skills.

**Q58. How do plugins work?**
Plugins bundle skills/hooks/MCP configs; remote plugin catalog (`features.remote_plugin`); plugin hooks live in `hooks/hooks.json` (overridable via `.codex-plugin/plugin.json` manifest); plugin hooks require hash-based trust; managed deployments can restrict catalogs.

**Q59. How does MCP work?**
`mcp_servers` in config.toml (user and project layers); tools surface as `mcp__server__tool` (matching hooks by that name); `mcp_elicitations` approval category gates MCP prompts; `required = true` servers fail exec on init failure; `features.skill_mcp_dependency_*` flag for skills that depend on MCP servers.

**Q60. What is the customization guidance hierarchy?**
Docs: use AGENTS.md for durable guidance → a plugin when a reusable workflow already exists → create a skill and package it as a plugin to share → MCP for external systems → subagents for delegating noisy/specialized work.

## 5.12 Configuration & customization

**Q61. What is the config precedence?**
CLI flags/`--config` > project `.codex/config.toml` (root→CWD, closest wins; **trusted projects only**) > profile files (`~/.codex/<profile>.config.toml`, via `--profile`) > user `~/.codex/config.toml` > system `/etc/codex/config.toml` > built-in defaults.

**Q62. What can't project config override?**
Credential-redirecting and host-owned keys: `openai_base_url`, `chatgpt_base_url`, `model_provider(s)`, `notify`, `profile(s)`, `experimental_realtime_ws_base_url`, `otel` — a documented trust boundary (startup warning when ignored).

**Q63. What are profiles?**
Named config layers (`~/.codex/<name>.config.toml`) selected with `--profile`; documented for CI (read-only + fast tier), full-auto, and readonly-quiet presets — the documented environment-preset mechanism.

**Q64. What env vars matter?**
`CODEX_HOME` (config home), `OPENAI_API_KEY` etc., `--enable/--disable feature` CLI toggles, `-c 'key=value'` one-off config overrides, `-a never` shorthand, `--sandbox`/`--ask-for-approval` flags.

**Q65. What is config hot-reload?**
No documented mid-session hot reload: instructions rebuild per run/session; config changes take effect on restart — a deliberate contrast with Claude Code's settings hot-reload.

---

# 6. OpenCode

> The open-source terminal coding agent (github.com/anomalyco/opencode). This document's own host. All answers come from opencode.ai/docs (intro, agents, plugins, rules, MCP, skills, tools, permissions, troubleshooting) plus direct experience as a running instance.

## 6.1 Agent loop & orchestration

**Q1. What is the OpenCode loop?**
Interactive agent loop in TUI/desktop/IDE/CLI/Go: user message → model → tool calls → results → next turn. `opencode run` runs non-interactively; the TUI supports `--auto` for autonomous runs.

**Q2. What are the modes?**
Build (all tools) and Plan (permission-restricted: edits and bash default to `ask`) primary agents, switched with Tab — the same plan/build dichotomy as Claude Code and Codex.

**Q3. What limits iterations?**
Agent `steps` (formerly `maxSteps`): when the limit is reached, the agent receives a special system prompt telling it to summarize its work and list recommended remaining tasks — a documented graceful stop instead of a silent cutoff.

**Q4. What are hidden system agents?**
Compaction (summarizes long context, auto-triggered), Title (session titles), Summary (session summaries) — internal agents that run automatically and aren't selectable in the UI.

**Q5. How do sessions nest?**
Subagents create child sessions; `session_child_first`/`session_child_cycle` keybinds navigate parent/child sessions; `/undo` reverts changes (multiple times) and `/redo` reapplies — the documented loop-control surface.

**Q6. How is context compaction handled?**
A compaction agent summarizes long context; plugins can customize it: `experimental.session.compacting` hooks inject extra context or **replace the entire compaction prompt** (`output.prompt`), e.g., for multi-agent swarm summaries.

## 6.2 Tool use & function calling

**Q7. What built-in tools exist?**
bash, edit (exact-string replacement), write, read (line ranges), grep (regex), glob, apply_patch, lsp (experimental), skill, todowrite, webfetch, websearch (Exa-backed, no key needed, OpenAI/Go provider only), question, task (subagents), todo read.

**Q8. How are tools gated?**
One `permission` config: `allow` / `ask` / `deny`, with wildcard patterns matched against tool names (works for built-ins, custom tools, and MCP tools: `"mymcp_*": "deny"`). Legacy `tools` boolean config is deprecated but supported.

**Q9. What is custom-tool support?**
Custom tools defined in config or plugins with Zod schemas (`tool.schema.string()`, etc.) and an `execute` function; plugin tools override built-ins on name collision.

**Q10. How are tool results sized?**
No documented auto-pruning (Claude Code's CACHED_MICROCOMPACT equivalent); context management relies on compaction and the user's tool/permission choices; MCP docs warn that many servers inflate context.

**Q11. What is the question tool?**
A native tool for asking the user questions mid-task (header, question, options, custom answers, multi-question navigation) — human-in-the-loop as a first-class tool rather than only a permission prompt.

**Q12. What are the grep/glob internals?**
ripgrep under the hood, respecting `.gitignore`; a `.ignore` file can re-include ignored paths (`!node_modules/`) — documented search behavior.

**Q13. What is apply_patch?**
Applies unified diffs (`*** Update File:`, `*** Add File:`, `*** Move to:`, `*** Delete File:` markers relative to project root); gated by the `edit` permission; plugin hooks must match `apply_patch` (not `patch`).

## 6.3 Prompts & context management

**Q14. What is the rules system?**
AGENTS.md files: project (`./AGENTS.md`) and global (`~/.config/opencode/AGENTS.md`); `/init` scans the repo and generates/improves AGENTS.md (build/test/lint commands, architecture, conventions, gotchas, references to existing Cursor/Copilot rules).

**Q15. What is the rule precedence?**
Local files (walking up from CWD: AGENTS.md, CLAUDE.md) → global `~/.config/opencode/AGENTS.md` → `~/.claude/CLAUDE.md` (unless disabled); first match wins per category — a deliberately simple single-file-per-category model (no per-directory stacking like Codex).

**Q16. What Claude Code compatibility exists?**
CLAUDE.md, `.claude/rules/`, and `~/.claude/skills/` are honored as fallbacks; `OPENCODE_DISABLE_CLAUDE_CODE[|_PROMPT|_SKILLS]` env vars disable specific compat surfaces — a documented migration path for Claude Code users.

**Q17. What is the instructions field?**
`opencode.json` `instructions`: files, globs (`.cursor/rules/*.md`, `packages/*/AGENTS.md`), even remote URLs (fetched with a 5-second timeout) — loaded alongside AGENTS.md; the documented way to reuse existing rule files.

**Q18. How are external files referenced from AGENTS.md?**
Not parsed automatically; docs teach an explicit lazy-loading convention: "when you encounter @rules/general.md, use your Read tool on a need-to-know basis; do not preemptively load all references" — a prompt-level protocol instead of the `@include` parser Claude Code has.

**Q19. What is the context-economics stance?**
Skills load on demand (keep context lean), MCP docs warn about context inflation, AGENTS.md should stay concise — the same stable/lean-context discipline as Manus/Claude Code/Codex.

## 6.4 Memory & state

**Q20. What persistent state exists?**
Sessions/messages stored per project under `~/.local/share/opencode/project/<slug>/storage/` (or `global/storage` outside git); auth.json for credentials; MCP OAuth tokens in `mcp-auth.json`; logs in `log/` (10 most recent kept). `--print-logs` / `--log-level DEBUG` for diagnosis.

**Q21. Is there agent-authored memory?**
No MEMORY.md-style auto memory (Claude Code) or memories feature (Codex) is documented; durable knowledge is AGENTS.md + skills, which are human/agent-updatable files the model can edit itself.

**Q22. How does state survive restarts?**
Session data persists on disk; sessions can be continued/shared (`/share` creates a share link; conversations aren't shared by default); `/undo`/`/redo` operate on the current session's change history.

**Q23. How does the todo tool work?**
`todowrite`/`todoread` manage structured task lists in-session (disabled for subagents by default) — the built-in progress-tracking state.

## 6.5 Failure handling & recovery

**Q24. What are the documented error classes?**
ProviderInitError (invalid/corrupted provider config → re-auth or clear `~/.local/share/opencode`), AI_APICallError (stale provider packages → clear `~/.cache/opencode` to reinstall), ProviderModelNotFoundError (wrong model reference — must be `provider/model-id`), model-not-available, auth failures.

**Q25. How is a broken session recovered?**
`/undo` to revert the last changes; desktop app: restart, disable plugins (the usual crash cause), clear cache (`~/.cache/opencode`), reset saved state (`.dat` files) as last resort; CLI: check logs, `--print-logs`, `opencode upgrade`.

**Q26. What loop-level guards exist?**
`doom_loop` permission: when the same tool call repeats 3 times with identical input, the user is asked (default `ask`) — a built-in infinite-loop detector. This is the only documented loop-stall protection in the six systems besides Nexus's stall detector.

**Q27. How do plugin errors surface?**
Plugin exceptions in `tool.execute.before` throw and block the tool (the `.env` protection example throws to deny); a crashing plugin can break the desktop app — hence the documented disable-plugins troubleshooting path.

**Q28. What session error signals exist?**
`session.error` event for plugins; desktop notifications when a session errors; log files with timestamps; `--log-level DEBUG`.

**Q29. Is there an LLM retry policy?**
Not documented; provider packages (OpenAI/Anthropic/Google, dynamically installed and cached) handle their own retries; the documented failure surface is config/cache-level.

## 6.6 Testing & evaluation

**Q30. How does OpenCode test itself?**
The repo is open source (GitHub); the docs don't publish an eval harness. User-side: `/init` writes exact build/test/lint commands into AGENTS.md so agents self-verify; formatters config (`formatters`) auto-formats edited files.

**Q31. What is the formatter feature?**
Configured code formatters run on file edits — the documented "automated lint gate" of OpenCode (equivalent of Claude Code PostToolUse prettier hooks, but built-in).

**Q32. How are skills/agents tested?**
The docs' troubleshooting section for skills (SKILL.md spelling, frontmatter presence, unique names, permission deny hiding skills) is the documented verification checklist.

**Q33. What is the plugin-testing story?**
Plugin hooks can log via `client.app.log` (debug/info/warn/error levels) — structured logging is the documented way to debug plugin behavior.

## 6.7 Planning & delegation (multi-agent)

**Q34. What are the built-in subagents?**
general (full tool access except todo; multi-step tasks, can edit), explore (fast read-only codebase exploration), scout (read-only external docs/dependency research; clones repos into managed cache). Plus primary build/plan.

**Q35. How are custom agents created?**
Markdown files in `~/.config/opencode/agents/` or `.opencode/agents/` (frontmatter: description, mode, model, temperature, top_p, permission, steps, tools, prompt, color, hidden) or JSON in `opencode.json`; `opencode agent create` scaffolds them interactively (location, description, prompt, permissions — anything not selected is denied).

**Q36. What is task permission?**
`permission.task` with glob patterns controls which subagents an agent may invoke: `"*": "deny"` + `"orchestrator-*": "allow"` pattern; denied subagents are **removed from the Task tool description entirely** (the model won't attempt them); last matching rule wins; users can still invoke any subagent via `@`.

**Q37. How does the primary choose subagents?**
Subagents are invoked automatically based on their descriptions, or manually via `@mention`; hidden subagents (`hidden: true`) are only invocable programmatically via the Task tool.

**Q38. What model assignment exists?**
Per-agent `model` override; subagents inherit the invoking agent's model by default; `provider/model-id` format (e.g., `opencode/gpt-5.1-codex`); temperature/top_p defaults: 0 for most models, 0.55 for Qwen.

**Q39. What is the delegation documentation example?**
The multi-agent swarm compaction example: a custom compaction prompt summarizing task status, files modified per agent, blockers, next steps — evidence that multi-agent orchestration state is meant to be explicitly carried across compactions.

## 6.8 Human-in-the-loop & permissions

**Q40. What are the permission actions?**
`allow` / `ask` / `deny`; when asked, the UI offers `once` (this request), `always` (approve matching suggested patterns for the session — patterns provided by the tool, e.g., safe bash prefixes like `git status*`), or `reject`.

**Q41. What is auto mode?**
`--auto` (or `opencode run --auto`): automatically approves requests that aren't explicitly denied — deny rules still enforced; the prompt shows a muted `auto` indicator.

**Q42. What granular rules exist?**
Object syntax per tool: `bash: {"*": "ask", "git *": "allow", "rm *": "deny"}` and `edit: {"*": "deny", "packages/web/src/docs/*.mdx": "allow"}`; last matching rule wins; `*`/`?` wildcards; `~`/`$HOME` expansion in patterns.

**Q43. What safety defaults exist?**
Most permissions default to `allow` (permissive by default), but: `external_directory` (any tool touching paths outside the worktree) defaults to `ask`; `doom_loop` defaults to `ask`; `.env`/`.env.*` reads are denied by default (`*.env.example` allowed).

**Q44. What is external_directory?**
A dedicated permission key triggered when read/edit/glob/grep/bash touches paths outside the project worktree; allowed entries inherit workspace defaults (with the documented pattern of layering `edit: deny` over `external_directory: allow`).

**Q45. How do agent-level permissions merge?**
Agent permissions merge with global config; agent rules take precedence (example: build agent bash `git *: allow` but `git push *: deny` while global is stricter/looser).

## 6.9 Security & sandboxing

**Q46. Does OpenCode sandbox commands?**
No OS-level sandbox (like Claude Code): enforcement is permission-based (ask/deny, external_directory, doom_loop, .env denial). The Windows recommendation is WSL for "full compatibility" — no native sandbox layer is documented.

**Q47. What injection defenses exist?**
Websearch results are treated as content (no documented sanitization); the `.env`-denial default and external_directory ask are the documented data-protection defaults; plugin hook example shows a hard block pattern (throw in `tool.execute.before` for `.env` reads).

**Q48. What is the plugin trust model?**
No documented hash-based trust like Codex: plugins load automatically from config/plugin dirs (global and project). The troubleshooting doc's "disable plugins first" step is the practical containment story.

**Q49. How are MCP credentials stored?**
Remote MCP OAuth tokens in `~/.local/share/opencode/mcp-auth.json`; API keys via `{env:VAR}` interpolation (headers, environment); `opencode mcp logout <server>` removes credentials.

## 6.10 Observability

**Q50. What logging exists?**
Log files at `~/.local/share/opencode/log/` (10 most recent kept), `--log-level DEBUG`, `--print-logs`, `opencode uninstall` overview; desktop app shows error details with a Restart button.

**Q51. What plugin events are observable?**
Full event bus: `session.*` (created, idle, error, status, updated, compacted, diff), `message.*` (updated, removed, part.updated), `permission.asked/replied`, `tool.execute.before/after`, `shell.env`, `todo.updated`, `file.edited`, `lsp.*`, `tui.*`, `command.executed`, `installation.updated` — the documented observability surface for plugins.

**Q52. What structured logging exists?**
`client.app.log({service, level, message, extra})` with debug/info/warn/error — plugin authors should use it instead of console.log.

**Q53. What user-facing status exists?**
Agent indicator with `auto` muted indicator; desktop notifications for ready/error states; `session.idle` events for notification plugins; share links for conversations.

## 6.11 Skills / plugins / MCP

**Q54. How do skills work?**
`<name>/SKILL.md` with frontmatter (name required, description required 1–1024 chars, license, compatibility, metadata); discovery in `.opencode/skills/`, `~/.config/opencode/skills/`, plus `.claude/skills/` and `.agents/skills/` compat paths (walking up to the git worktree); names validated (`^[a-z0-9]+(-[a-z0-9]+)*$`, 1–64 chars, must match dir name); unknown frontmatter ignored.

**Q55. How are skills exposed to the model?**
The `skill` tool's description lists available skills (name + description); loading calls `skill({name})` and returns the content; skills can be gated by `permission.skill` patterns (allow/deny/ask; deny hides the skill from the agent), overridden per agent, or the whole `skill` tool disabled (`tools: {skill: false}` removes the `<available_skills>` section).

**Q56. How do plugins work?**
JS/TS modules in `.opencode/plugins/` (project) or `~/.config/opencode/plugins/` (global), auto-loaded at startup; or npm packages in `plugin: [...]` (installed via Bun, cached in `~/.cache/opencode/node_modules/`); load order: global config → project config → global plugin dir → project plugin dir; a `package.json` in the config dir adds npm deps for local plugins.

**Q57. What can plugins do?**
Subscribe to events (see 6.10), intercept tools (`tool.execute.before/after` — can mutate args like bash escaping, or throw to block), add custom tools (`tool: {mytool: tool({description, args: zod, execute})}`), inject shell env (`shell.env`), customize compaction (`experimental.session.compacting`), and log.

**Q58. How does MCP work?**
Local servers (`type: "local"`, command array, cwd, environment, enabled, timeout ms default 5000 for fetching tools) and remote servers (`type: "remote"`, url, headers, oauth, timeout); OAuth auto-detected (401 → RFC 7591 dynamic client registration → token storage; `oauth: false` to disable); CLI: `opencode mcp auth|list|logout|debug`; org defaults via `.well-known/opencode` remote config overridable locally.

**Q59. How are MCP tools managed?**
All MCP tools available alongside built-ins; disabled/enabled via `tools` or `permission` with server-name prefixes (`"my-mcp*": false`); per-agent enabling pattern (disable globally, enable in a specific agent).

## 6.12 Configuration & customization

**Q60. What is the config surface?**
`opencode.json`/`.jsonc` (project) + `~/.config/opencode/opencode.json` (global) with `$schema`; keys: agent, tools/permission, mcp, plugin, instructions, models, keybinds, themes, formatters, commands, lsp, policies; env interpolation `{env:VAR}` throughout.

**Q61. What are commands?**
User-defined slash commands (the `/` surface) — one of the six documented customization layers alongside keybinds, themes, formatters, agents, and plugins.

**Q62. What is Zen?**
A curated, tested model list from the OpenCode team (opencode Zen) — the documented "which models actually work" layer; `opencode models` lists available models.

**Q63. How is LSP integrated?**
Experimental LSP servers with an lsp tool (definitions, references, hover, symbols, call hierarchy) gated by `OPENCODE_EXPERIMENTAL_LSP_TOOL` — code intelligence as an optional tool layer.

**Q64. What Windows support exists?**
Installers (choco/scoop/npm/mise/Docker) with WSL recommended; WebView2 required for desktop; desktop-specific troubleshooting (server URL, cache, .dat state reset).

**Q65. What enterprise features exist?**
Policies (enterprise permission policies), network config, enterprise page — documented but thin; the open-source nature makes self-hosting the primary enterprise story.

---

# 7. Nexus AI — comparison per topic

> Nexus is this repository: local-first autonomous agent framework (Python core, v5 orchestrator, 40+ providers, Hive multi-agent engine, MCP client+server, plugins with trust model, 69 skills, memory manager, 3-tier sandbox, safety layer). Facts below are from the live codebase (verified in the reliability mission, Aug 2026: 599 tests green including chaos-injection tests). For each topic: how Nexus does it, and where the six systems above are ahead or behind.

**Quick matrix (per topic, best-per-topic marked LEADS):**

| Topic | Manus | Hermes Agent | DeepSeek | Claude Code | Codex | OpenCode | Nexus |
|---|---|---|---|---|---|---|---|
| Loop & orchestration | VM agent, internals unpublished | shared loop, restart counts | model API only | modes, no machine state | modes + goals auto-continue | modes + compaction agents | persisted state machine + resume (LEADS) |
| Tool use | fixed action space, VM exec | AST registry + register_tool | tools API + strict mode | deny-removes-tool, scoped rules | exec + apply_patch, 60s timeouts | Zod custom tools | registry + metadata + risk scoring |
| Prompts & context | stable prefix + cache breakpoints (LEADS) | per-model-family guidance | cache pricing + hit-token metrics | 18 sections + dynamic boundary | AGENTS.md chain, 32 KiB cap | rules + instructions field | deterministic serialization, no cache discipline |
| Memory & state | in-context only | 8 memory providers | stateless | CLAUDE.md hierarchy + auto memory (LEADS) | memories (experimental) | session files only | MemoryManager + persisted goals |
| Failure handling | prevention via context | restart counts, cron leases | retry 429/500/503 | 10× retry, incomplete-response idempotency | fail-closed MCP, timeouts | doom_loop guard | escalation ladder + stall detection + chaos tests (LEADS) |
| Testing | production metrics only | 1,688 hermetic tests (LEADS) | schema contract tests | hooks as quality gates | internal evals, unpublished | open source, no harness | 599 tests incl. chaos injection |
| Multi-agent | parallel sub-agents | delegate_task only | none (host-side) | Task tool subagents | 3 built-ins + custom, 6 threads | 3 subagents + task permissions | Hive: spawn/blackboard/DAG/consensus/swarm (LEADS) |
| Permissions | none granular | approval gates | none (host-side) | tiered allow/ask/deny | policies + granular auto-reject (LEADS) | patterns + doom_loop + question tool | binary gates + waiting_for_permission status |
| Security & sandbox | cloud VM (LEADS for isolation) | egress isolation | none | in-loop enforcement only | OS sandbox + network proxy | permission-only | 3-tier sandbox + CommandRiskScorer + laws |
| Observability | cache-hit-rate metric | langfuse/nemo plugins | usage + cache tokens | statusline + /doctor | OTel metrics (LEADS) | logs + plugin event bus | 50 canonical events + SSE + run statuses |
| Skills/plugins/MCP | thin | mature plugins + MCP catalog | none | marketplaces + skills | remote catalog + hash trust | event-bus plugins + skills | 69 skills + trust model + client+server+catalog |
| Configuration | web app only | HERMES_HOME profiles | base_url + models | hot-reload settings (LEADS) | trust-gated layered config | env interpolation | YAML/JSON/env + profiles |

## 7.1 Agent loop & orchestration

**How Nexus does it:** `orchestrators/v5` runs a direct model/tool loop (`NexusLoop`) with a formal, persisted state machine (`reliability/states.py` RunStateMachine: INITIALIZING → PLANNING → ACTING → VERIFYING → GOAL_COMPLETED, plus TIMED_OUT, BLOCKED, PAUSED, QUARANTINED; transition table validated by tests). Goals (`reliability/goal.py` GoalState) persist to disk and are auto-loaded on restart — the loop can resume after a crash. The mission added per-iteration progress tracking (`ProgressTracker` stall detection), checkpoint/resume hooks, and a durable task queue (`queue/driver.py`).

**Comparison:** No other system documents a persisted goal/state machine. Claude Code and Codex have modes (plan/auto/read-only) but no machine-resumable state (Codex goals are prompt-level auto-continuation); OpenCode/Manus/Hermes loop internals are less formal (Hermes tracks restart counts; OpenCode relies on compaction). Nexus's run-context intermediate statuses (`set_intermediate_status`: recovering/blocked/degraded/paused/waiting_for_permission/waiting_for_credentials/waiting_for_dependency) are a documented status vocabulary none of the six expose at this granularity.

**Ahead/behind:** Ahead on loop-state formalism and crash-resumption. Behind on interactive modes (no plan-mode/auto-mode classifier like Claude Code/Codex/OpenCode; planning is todo.md-driven) and on mode-differentiated toolsets.

## 7.2 Tool use & function calling

**How Nexus does it:** Explicit `BaseTool` ABC + `ToolRegistry` with `.jsnol`/`.json` metadata discovery (contrast: Hermes uses AST-based auto-discovery); 18 implemented tools + 13 stubs registered but marked `unavailable`; `terminal` is the sole command-execution tool (bash tool retired); tool calls are risk-scored (`sandbox/risk.py` CommandRiskScorer) and permission-gated (ask before destructive).

**Comparison:** Claude Code's deny-removes-tool-from-context, scoped rules (`Bash(rm *)`), and permission tiers are richer than Nexus's ask/allow gates. OpenCode's Zod-schema custom tools and per-agent permission layering are simpler to extend than Nexus's metadata+registry (but Nexus's registry matches Hermes's register_tool model). DeepSeek strict mode (server-side JSON Schema validation of tool args) is worth adopting as a provider feature. None of the six match Nexus's per-tool risk-scoring world model.

**Ahead/behind:** Ahead on risk scoring and explicit metadata contracts; behind on fine-grained scoped permission rules and tool-removal semantics.

## 7.3 Prompts & context management

**How Nexus does it:** Per-provider prompt construction in the v5 orchestrator with deterministic plan serialization (the reliability work stabilized plan/goal rendering for checkpointing). No documented dynamic-boundary/caching discipline.

**Comparison:** This is the systems' most consistent lesson, and Nexus's biggest gap: Manus (KV-cache hit rate, stable prefix, append-only context, cache breakpoints), Claude Code (18-section prompt with `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__`, ~70% prefix cache hits, memoized sections), and DeepSeek (cache-hit token metrics; 10× cheaper hits) all converge on "stable prefix, append dynamic suffix." Nexus does not yet: (a) order prompts stable-first, (b) monitor per-turn cache-hit tokens (DeepSeek `usage.prompt_cache_hit_tokens`), or (c) track KV-cache hit rate as a production metric.

**Ahead/behind:** Behind on caching economics and prompt-stability discipline. The Claude Code source analyses (18 sections, boundary sentinel, DANGEROUS_uncached section naming) are a concrete design template Nexus's prompt engine can adopt.

## 7.4 Memory & state

**How Nexus does it:** Multi-source `MemoryManager` with parallel prefetch and sync (memory/ module); durable run context (`nexus/run_context.py`); persisted goals/checkpoints (reliability package); durable queue.

**Comparison:** Claude Code's documented CLAUDE.md hierarchy (managed/user/project/local + path-scoped rules + `@include` depth 5 + auto memory MEMORY.md 200-line index) and Codex's AGENTS.md chain (root→CWD walk, 32KiB cap, overrides) are better documented and more granular than Nexus's. Nexus has no agent-authored auto-memory index yet (Claude Code MEMORY.md / Codex memories / Hermes 8 memory providers). Nexus's crash-persistent goal/checkpoint state exceeds all six (Manus is in-context only; Claude Code resumes sessions but not machine state).

**Ahead/behind:** Ahead on durable operational state; behind on layered instruction memory and auto-memory.

## 7.5 Failure handling & recovery

**How Nexus does it:** The strongest documented story of the six: provider failover adapters (outage → next provider), `V5RetryPolicy` exponential backoff + jitter, recovery escalation ladder (`reliability/recovery.py`: attempts ladder per failure class, non-recoverable → resumable), persisted state machine with quarantine, `ProgressTracker` stall detection (per-iteration progress thresholds), checkpoint/resume across the six mid-round loss windows the audit identified, run-context intermediate statuses, and 10 chaos-injection tests (provider outage, network partition → blocked + resume path, MCP disconnect → reconnect, worker crash → reclaim, repeated failures → escalate to blocked, non-recoverable → resumable, restart-resumption).

**Comparison:** Claude Code's documented retry semantics are the sharpest other reference: 10 attempts exponential backoff, mid-response failures keep completed output and **do not re-run completed tool calls** (idempotency decision), 20s stall timeout with one extra re-issue, auto compact-and-retry on context overflow. Codex fails closed on required-MCP init; OpenCode's doom_loop (3 identical calls → ask) is a simple loop guard; Hermes counts consecutive restarts and leases cron jobs; Manus prevents failures via context engineering. Nexus's escalation ladder and stall detector are richer than all of them; the Claude Code incomplete-response/idempotency semantics are worth formalizing in Nexus's checkpoint logic.

**Ahead/behind:** Ahead on structured recovery; adoptable from Claude Code: mid-stream partial-completion semantics, explicit stall timeouts, auto-compact-then-retry on context overflow.

## 7.6 Testing & evaluation

**How Nexus does it:** 150+ test files; the reliability suite alone is 599 green (89 unit + 28 integration + 25 capability + 411 v5 regression + 46 queue/run_context/supervisor/hive/planning), including the chaos-injection tests described above — failure-path tests are Nexus's differentiator.

**Comparison:** Hermes's 1,688 hermetic tests (subprocess isolation, credential stripping, deterministic TZ, 30s timeouts, change-detector) are the largest published suite and the model Nexus's conftest isolation followed. Claude Code/Codex publish no open harness (internal evals, public knowledge); their documented testing is user-side (hooks as quality gates, AGENTS.md exact commands). OpenCode is open source but publishes no eval harness; Manus publishes none. Gaps for Nexus: no per-test timeout convention, no change-detector, and the chaos suite covers v5 paths only (the adoption audit found 104 silent-swallow sites across 13 subsystems, 49 of them `except Exception: pass` — these need the same test treatment).

**Ahead/behind:** Ahead on failure-path testing; behind on hermeticity tooling breadth (timeouts, change detection) vs Hermes.

## 7.7 Planning & delegation (multi-agent)

**How Nexus does it:** `NexusHiveEngine` (hive/) — spawn, consolidate, blackboard, DAG workflows, swarm execution, consensus, merge planning, pulse monitoring: 10 dedicated subagent tools. This is the most complete orchestration vocabulary of the seven systems compared here.

**Comparison:** Codex: 3 built-ins (default/worker/explorer) + custom agent TOMLs + 6 concurrent threads + auto model selection; Claude Code: Task tool + frontmatter subagents, hooks fire in subagents; OpenCode: 3 built-ins + custom markdown agents + `permission.task` globs that remove denied subagents from the model's view; Hermes: `delegate_task` leaf/orchestrator only; Manus: parallel sub-agents, undocumented. None have Nexus's blackboard/consensus/DAG primitives. OpenCode's task-permission glob model and Codex's per-subagent config-file layering are worth mirroring.

**Ahead/behind:** Ahead on orchestration primitives; behind on subagent permission controls and per-subagent model/effort selection (Nexus spawns with the parent model).

## 7.8 Human-in-the-loop & permissions

**How Nexus does it:** Permission gates ask before destructive commands; `sandbox/risk.py` risk scoring; threat-pattern detection (41 regex, 3 scopes); run-context `waiting_for_permission` / `waiting_for_credentials` statuses surface blocked states.

**Comparison:** Claude Code (tiered Allow/Ask/Deny, scoped rules, deny-removes-tool, auto-mode classifier), Codex (approval policies incl. granular auto-reject categories, auto_review reviewer agent), and OpenCode (per-tool granular pattern rules, external_directory, doom_loop, .env-deny default, question tool) all document finer-grained, pattern-based permission systems than Nexus's binary ask/allow gates. Adoptable: scoped rules (OpenCode `"git push *": "deny"` style), deny-removes-tool semantics, doom_loop detection, and an approval-category model like Codex's granular policy.

**Ahead/behind:** Ahead on surfacing blocked states (intermediate statuses); behind on permission rule granularity and mode-based permission presets.

## 7.9 Security & sandboxing

**How Nexus does it:** 3-tier sandbox (NO_SANDBOX / NORMAL / DOCKER) + `CommandRiskScorer` (predicts filesystem/process risk, reversibility, safeguards before execution) + sovereign laws (`safety/laws.py`) + LogicProver + secret scanner + threat patterns. This layered world-model+sandbox+safety composition is unique among the seven.

**Comparison:** Codex has the best OS-level sandbox (read-only/workspace-write/danger-full-access, subprocess inheritance, network proxy allowlists, Windows unelevated/elevated, web-search cache default against injection). Claude Code and OpenCode enforce only in-loop (permissions/hooks), Hermes isolates network egress via Docker, Manus isolates in cloud VMs. Adoptable from Codex: subprocess-tree sandbox inheritance, network egress allowlists, cached-web-default for web research.

**Ahead/behind:** Ahead on risk scoring and safety logic; behind on OS-level enforcement depth (Nexus's DOCKER tier is the closest analog but less documented) and network policy.

## 7.10 Observability

**How Nexus does it:** ~50 canonical `EVENT_TYPES` (`nexus/events.py`) flowing through `work_event_sink` to GUI via SSE; run-context statuses; reliability metrics from the mission (retry attempts, escalation, stall detections, quarantine counts).

**Comparison:** Codex ships OTel exporters with tool-level counters/histograms (`codex.tool.call`, durations by success) — Nexus has no exporter yet. Claude Code's statusline JSON contract is a neat user-facing surface Nexus lacks; OpenCode's plugin event bus (`session.error`, `permission.asked`, `tool.execute.before/after`) and structured `client.app.log` are the template for plugin telemetry; Hermes's langfuse/nemo_relay plugin exporters show how to package telemetry as plugins. Adoptable: DeepSeek's cache-hit token metrics as a production monitor (per 7.3), OTel export, statusline-style surface.

**Ahead/behind:** Ahead on event-model richness; behind on metrics export and structured plugin logging.

## 7.11 Skills / plugins / MCP

**How Nexus does it:** Skills: 69 SKILL.md skills in 14 categories (frontmatter registry). Plugins: lifecycle hooks (`pre_tool_call`, `post_tool_call`, `pre_llm_call`, …) + `plugins/trust.py` trust model + tool registration. MCP: `NEXUSMCPServer` + `MCPClient` + `MCPTool` (stdio) + `mcp/catalog.py` server catalog with registration/validation. Notably, Nexus's plugin hook names match Hermes's — the plugin architecture was adopted from the Hermes comparison (docs/HERMES_COMPARISON.md), and the comparison's MCP-catalog gap was closed by `mcp/catalog.py`.

**Comparison:** Hermes remains the closest peer (plugins, MCP catalog with install-from-URL, per-profile plugins). OpenCode: plugin event bus + Zod custom tools + skills with permission patterns; Claude Code: plugin marketplaces bundling agents/MCP/skills/hooks + hash-trust-free (marketplace trust instead); Codex: remote plugin catalog + skill approval categories + hook hash-trust. Adoptable: Codex's hook hash-trust and OpenCode's per-skill permission patterns (Nexus skills are all-or-nothing), plus skill-name validation rules (OpenCode regex).

**Ahead/behind:** Ahead on MCP breadth (client + server + catalog in one repo); behind on skill-level permissioning and hook trust verification.

## 7.12 Configuration & customization

**How Nexus does it:** `NexusConfigLoader` (YAML/JSON/env layered), profile system (`nexus_path/`, `profiles.py` — adopted from Hermes per the comparison report), 40+ providers with per-provider config, OAuth flows, gateway for 21 platforms.

**Comparison:** Codex's documented precedence chain (CLI > project-trusted > profile > user > system > defaults) and trust-gating of project config are more rigorous than Nexus's loader; Claude Code's hot-reload of settings mid-session (with ConfigChange hook) is unique; OpenCode's env-var interpolation in config (`{env:VAR}`) is convenient; Hermes's HERMES_HOME profile isolation is the model Nexus's profile system follows. Adoptable: trust-gating project config, settings hot-reload, `{env:VAR}` interpolation.

**Ahead/behind:** Ahead on provider breadth and multi-format loading; behind on config trust boundaries and live reload.

## 7.13 Transferable lessons (short list)

1. **Prompt caching discipline** (Manus/Claude Code/DeepSeek): stable prefix, dynamic suffix, cache breakpoints, monitor cache-hit tokens per turn.
2. **Idempotent mid-response handling** (Claude Code): never re-run completed tool calls on retry; keep completed output; explicit stall timeout.
3. **Auto-compact-and-retry** on context overflow (Claude Code) with configurable trigger.
4. **OS-level sandbox + network allowlists + cached web search** (Codex).
5. **Granular permission patterns** (OpenCode/Codex): scoped rules, deny-removes-tool, doom_loop guard, approval categories, subagent task permissions.
6. **Hook hash-trust** (Codex) and **skill-level permissions** (OpenCode).
7. **Hermetic test hardening** (Hermes): per-test timeouts, change-detector, credential stripping — extend to Nexus's non-v5 subsystems (104 silent-swallow sites from the adoption audit).
8. **OTel/metrics export** (Codex) and structured plugin logging (OpenCode) on top of Nexus's event model.
9. **Server-side tool-arg validation** (DeepSeek strict mode) for providers that support it.
10. **Statusline-style user-facing state surface** (Claude Code) driven by Nexus's run-context statuses.

## 7.14 Per-system vs Nexus — one-paragraph verdicts

**Manus vs Nexus.** Manus is ahead on context engineering (stable prefix, KV-cache hit rate as a production metric, cache breakpoints, fixed action space) — Nexus's prompt engine has no caching discipline and should adopt all four. Manus is behind everywhere else *by documentation*: its loop internals, retry policy, permissions, and test harness are unpublished; Nexus has a documented persisted state machine, escalation ladder, and chaos-tested failure paths Manus doesn't describe. Manus's cloud-VM execution is the strongest isolation story of the seven; Nexus's DOCKER tier is its closest analog.

**Hermes vs Nexus.** Hermes is the closest peer architecturally (the comparison report `docs/HERMES_COMPARISON.md` shows Nexus adopted its plugin-hook names, profile system, and MCP-catalog idea). Hermes leads on test volume and hermeticity tooling (1,688 tests, subprocess isolation, 30s timeouts, change-detector) and on documented plugin breadth (18 categories, 8 memory providers, observability plugins). Nexus leads on orchestration (Hive vs `delegate_task`), safety (risk scoring, logic prover vs approval gates), local-model sovereignty, and failure recovery (escalation ladder vs restart counts).

**DeepSeek vs Nexus.** DeepSeek is a model provider, so the comparison is about how Nexus consumes it: Nexus's provider layer with failover is exactly what DeepSeek's docs recommend ("switch provider" on 429). Nexus should use DeepSeek's `usage.prompt_cache_hit_tokens` to monitor context-cache health (per 7.3) and enable strict mode (server-side tool-arg validation) where supported. DeepSeek contributes nothing on the loop side — all of that is Nexus's own.

**Claude Code vs Nexus.** Claude Code is ahead on user-facing interaction design: tiered permissions with deny-removes-tool, auto-mode classifier, plan mode, hooks as guardrails, statusline, `/doctor`. Its documented retry semantics (10× backoff, never re-run completed tool calls, 20s stall timeout, auto-compact-and-retry) are the sharpest idempotency spec Nexus's checkpoint logic should formalize against. Nexus is ahead on machine-recoverable state: Claude Code resumes conversations, Nexus resumes goals, checkpoints, and a validated state machine.

**Codex vs Nexus.** Codex is ahead on security and policy plumbing: OS-level sandbox with subprocess inheritance, network proxy allowlists, cached web search, granular approval categories, auto_review, hook hash-trust, trust-gated project config, OTel export. These are the highest-value adoptions for Nexus (the sandbox/network layer in particular). Nexus is ahead on recovery (persisted state machine vs fail-on-error exec) and orchestration primitives (Hive vs 3 built-in subagents), and on provider breadth.

**OpenCode vs Nexus.** OpenCode is the most similar project in spirit (open-source, config-driven, plugin event bus) and is ahead on: per-tool granular permission patterns (including `external_directory` and doom_loop), Zod-based custom tools, skill-level permissions, `{env:VAR}` config interpolation, and a documented `.env`-deny default. Nexus is ahead on: failure recovery (OpenCode has no retry ladder; doom_loop is its only loop guard), multi-agent primitives, MCP breadth (client + server + catalog), and event-model richness (50 canonical events vs plugin-only events).

**Bottom line.** No system beats Nexus on recovery, orchestration, or safety-layer depth; every system beats Nexus on at least one adoption-worthy surface: prompt-cache discipline (Manus/Claude Code/DeepSeek), permission granularity (Claude Code/Codex/OpenCode), OS-level sandboxing and network policy (Codex), hermetic test tooling (Hermes), and settings ergonomics (Claude Code hot-reload, OpenCode env interpolation). The 10 lessons in 7.13 are the concrete adoption queue.

---

# 8. Sources

- Manus: *Context Engineering for AI Agents* — manus.im/blog/Context-Engineering-for-AI-Agents (accessed via web search, Aug 2026)
- Nous Hermes function calling: github.com/NousResearch/hermes-function-calling (prompter.py, schema.py, jsonmode.py, README guidance)
- Hermes Agent: vendored source in this repo — `.research/hermes-agent-main/` (README, docs/session-lifecycle.md, docs/security/network-egress-isolation.md, docs/rca-ssl-cacert-post-git-pull.md, docs/profile-routing.md, docs/kanban/, docs/design/profile-builder.md, docs/chronos-managed-cron-contract.md, docs/middleware/, plugins/observability/{nemo_relay,langfuse}/, plugins/model-providers/, plugins/memory/supermemory/, plugins/google_meet/, skills/, CONTRIBUTING.md) and `docs/HERMES_COMPARISON.md`
- DeepSeek: api-docs.deepseek.com — guides/error_codes, guides/tool_calls, guides/strict_mode (beta), thinking mode (V3.2 release notes), pricing (context caching)
- Claude Code: code.claude.com/docs/en — permissions, permission-modes, hooks, hooks-guide, settings, memory, claude-md, errors, llm-gateway-connect, context-window; third-party corroboration: blog.lienjack.com/en/blog/AI/Claude code/03-prompt-construction (2026-05), codex.cadences.app/en/blog/claude-code-system-prompt (2026-04), openedclaude.github.io/claude-reviews-claude/chapters/10-context-assembly
- Codex: developers.openai.com/codex — guides/agents-md, concepts/customization, config-reference, config-advanced, config-basic, config-sample, hooks, concepts/sandboxing, agent-approvals-security, subagents, noninteractive, learn/best-practices, integrations/github, blog/custom-code-review-rules-for-codex; github.com/openai/codex issue #11233 (tool-call timeout)
- OpenCode: opencode.ai/docs — intro, agents, plugins, rules, mcp-servers, skills, tools, permissions, troubleshooting, config
- Nexus: live codebase (`orchestrators/v5/`, `reliability/`, `nexus/run_context.py`, `nexus/events.py`, `tools/`, `hive/`, `mcp/`, `plugins/`, `skills/`, `sandbox/`, `safety/`, `memory/`, `queue/`), `docs/research/reliability_mission_report.md`, `docs/audits/reliability_adoption_audit.md`, `docs/audits/reliability_limitation_audit.md`, `docs/research/reliability_architecture.md`, `AGENTS.md`

*Compiled Aug 17, 2026. Research method: web search + official-docs fetches; answers grounded per source, gaps marked "undocumented" rather than guessed.*