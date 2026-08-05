# NEXUS AI — Overhaul Campaign Changelog

> Consolidated record of the 2026-08-05 full-system overhaul campaign.
> Companion to `docs/RUNTIME_FLOW.md`. Every item below was verified with code
> (compile) + tests, not asserted.

## Verification baseline

- Full suite (serial): **1417 passed, 8 skipped, 0 failed** (pre-overhaul: 1030 passed).
- All modified packages compile clean (`compileall -q`). GUI `npm run build` clean;
  TUI `tsc --noEmit` clean + `npm test` green.
- Serial pytest only — concurrent pytest processes corrupt shared state here.

## Wave 3-4 — Reference-driven redesign (Hermes/OpenClaw/OmniRouter/claude-code)

The strongest ideas from each reference were **re-implemented** (not copied) into
NEXUS, building on NEXUS's own strengths. All tested.

### Agent loop (`orchestrators/v5/direct_loop.py`, `context_manager.py`, `checkpoint.py`)
- Tool-result budgeting: &gt;50K chars → `context_archive/tool-results/&lt;id&gt;.txt` + first-2000 preview; empty → `"(<tool> completed with no output)"`.
- Cloud context budget: real provider-window trims oldest turns + `[dropped N]` summary (local models unchanged).
- Prompt-too-long compact-and-retry: detect `context/too long/413`, collapse oldest half, retry once.
- Checkpoints now persist `recent_messages` (last12) for future resume.

### Permissions/sandbox (`permissions/`, `orchestrators/v5/tools.py`, `sandbox/`)
- Ask-mode shell commands now route through `ApprovalBroker` + re-execute (fixed latent bug where registry-tool ask-mode silently hard-denied).
- `pre_tool_call` hook `{"action":"block"}` now denies tools.
- Decisions persisted to `~/.nexus/permissions/decisions.jsonl` + rehydrated; per-agent deny scoping via `config/permission_agents.yml`.
- Docker tier: `--network=none --read-only`, fail-closed on missing daemon.

### Tools/MCP (`tools/nexus_tools/`, `mcp/`, `tools/modifying|reading`)
- Strict schema validation (`additionalProperties:false`, enum checks).
- Persist-to-disk oversized tool results + preview envelope.
- MCP reconnect+bounded backoff, `degraded|healthy|unavailable` health, park/deregister dead servers' tools.
- Edit precision: `replace_all` param, count diagnostics ("Found N matches…"), quote normalization.

### Reliability/24-7 (`queue/`, `gateway/`, `providers/reliability.py`, `health.py`)
- Startup lease-reap sweep; `ack_lease` renewal heartbeat.
- Gateway ingress dedupe (message_id / sha256 LRU) in gateway + webhook paths.
- `call_with_reliability` bounded retries (tools/gateways); `ComponentBreakerRegistry` per-component.
- Telegram poll reconnect with exponential backoff.

### Slash commands (`nexus/commands.py`)
- Added: `compact`, `context`, `resume`, `plans`, `agents`, `rewind`, `hooks`, `mcp`, `login`, `cost` — each wired to real backend functions.

### Hive (`orchestrators/v5/hive.py`)
- Sub-agent timeouts (env-default120s) + cancel; states persisted to `~/.nexus/hive/subagents.jsonl`; `[HIVE_RESULT]` validated before inject; cancel propagation.

### TUI (`tui/`)
- Monolith `nexus-tui.tsx` split 5059→2705 lines into7 modules (`helpers`, `chat-view`, `task-list`, `details-panel`, `workspace-panel`, `banner`, `command-palette`). Tasks as compact rows with real state glyphs; real status bar (provider/model/active tool/context%); no fabricated status. `tsc`0 errors, all tests green.

### Gateway lifecycle (`gateway/`)
- `PlatformRuntime` + `GatewaySupervisor`: per-platform states + health, exponential-backoff reconnect across all platforms, crash-loop disable, atomic state persistence honored on restart, graceful stop_all.

### Evolution + forges (`evolution/`)
- Version unification (one `VersionManager`); quality gate `promoted` (rejected results not written); ledger audit trail + `rollback(kind,name)`; `@forge_guard` fault isolation; forges reject error-shaped evidence.

### Skills + experience (`skills/`, `tools/nexus_tools/skill_adapter.py`, `orchestrators/v5/skill.py`)
- Runtime skill selector (top-3 by token overlap; `required` always; `NEXUS_ALL_SKILLS_INJECT=1` rollback); skill-as-tool returns real SKILL.md instructions; skill health (3-fail→unhealthy); experience store `~/.nexus/skills/experience.json`.

### Component lifecycle (`lifecycle/`)
- `LifecycleStage` + `ComponentSupervisor`: validated transitions (no ghost states), `after=` startup ordering + reverse shutdown, restart recovery, persistence, honest `read.md`.

### Voice (`voice/`)
- 4-backend STT failover with lazy heavy imports (missing torch never crashes import), VAD silence-trim, lifecycle states + double-start guard +30s timeout, ref-counted idempotent close.

### Kernel (`kernel/`)
- Subsystem fault isolation (`FailedSubsystem`), dependency ordering, memoized lazy loads, `reload(reason)`/`reset()`, `health_check()`, read-only lifecycle stage map.

### Memory/context (`memory/`, `context/`, `tools/memory|knowledge`)
- `estimate_tokens`, `MemoryBudget` with `[truncated N chars]` marker, call/result-safe compaction (`compact_messages` never splits tool_call/result), expiry keeps verified facts, `inspect()` breakdown.

### Plugins (`plugins/`)
- `PluginStage` lifecycle + `state.json` (fingerprint restore), fault isolation (3-fail→`crash_loop` disable), capability allowlist gating + denied-registration trail, hook block-return normalization.

## Wave 1 — Runtime, providers, memory, gateway, auth, knowledge

### Provider function-calling (the big one)
All LLM providers now forward native `tools`/`tool_choice` and parse
`tool_calls` back into V5 `<function=name>{json}` envelopes:
- Fixed: `openai`, `anthropic`, `universal` (were silently dropping tools /
  losing tool responses), `azure_openai` (was completely BROKEN: empty endpoint,
  no `model` in body), `google_gemini` (functionDeclarations).
- Batch-fixed OpenAI-compat: `groq`, `fireworks`, `mistral`, `together`, `qwen`,
  `xai`, `sambanova`, `nvidia`, `commandcode`, `vlm`.
- Native formats: `ollama`, `llama_cpp`, `cohere`.
- Enum gate enabled in `config/provider.yml` `model_capabilities.providers.<id>.tools`
  so `providers/router.py:_apply_model_limits` stops stripping schemas.
- Tests: `tests/test_*_tool_calls.py` (~73 tool-call tests + azure/gemini suites).

### V5 agent loop
- Removed dead code from `orchestrators/v5/core.py` (2479 → 2053 lines): the
  unreachable PAORR/quantum/consciousness block, `_v1_compat_turn`, and the
  `_verify_all_parallel` stub. 160/160 `tests/v5` pass — live path
  (`_run_direct_model_tool_loop`) untouched.

### Memory — verified-results gate (P0)
- `memory/__init__.py` `sync_all` now accepts `verified_actions`/`tool_results`;
  `.opencode/memory/learned.md` and MemoryForge only persist verified tool
  evidence; session transcript tags assistant entries `verified: True/False` and
  recall skips unverified claims; `MemoryTool.store` records provenance
  (`source: llm_claim`, `verified: False` by default).
- Tests: `tests/test_memory_manager/scripts/test_memory_manager.py`.

### Gateway hardening
- Meta + Twilio webhook signature verification (constant-time, fail-closed).
- whatsapp/email env-gates require the full credential set (no more sends to the
  wrong endpoint / register-then-fail).
- `gateway/telegram_bot.py` import crash fixed; malformed `ALLOWED_TELEGRAM_IDS`
  no longer crashes import.
- Tests: `tests/test_gateway/test_security_hardening.py`.

### Auth / OAuth
- Wired the previously-dead auth CLI: `nexus auth login|logout|add-key|list|
  set-default|delete-profile|auto-detect|strategy`.
- Fixed minimax/copilot `on_manual_code_input` TypeError (signature-aware kwargs).
- Fixed `asyncio.run` inside a running event loop in `providers/factory.py`.
- `auth login` failures now render clean messages, never shell tracebacks.
- **Boot bug fixed**: `_resolve_root()` prepended the `nexus/` dir to
  `sys.path[0]`, shadowing the top-level `commands/` package with
  `nexus/commands.py`. Project root is now always first on `sys.path`.

### Knowledge / persistence
- Created `knowledge/vault.py` (`KnowledgeVault`), rewrote `knowledge/__init__.py`
  (`KnowledgeStore`), created `context/persistence.py` (`NexusFilePersistence`).
  `import knowledge; import knowledge_memory_context` now works.

### File-system / data hygiene
- `evolution/memory_forge/scripts/forge.py` output moved from `memory/` (package
  collision) to `data/memory_forge/`; 69 stray folders relocated.

### Evolution / lifecycle
- `StrategicHorizons` no longer crashes the prompt path
  (`prompts/__init__.py:172`).
- `SelfEvolutionLayer._test_candidates` scores from real evidence; valid
  candidates can now deploy in safe mode.
- `VersionManager` persists per-name versions (`.nexus/versions.json`) so every
  forge bump works.
- Lifecycle managers persist state to `~/.nexus/lifecycle/`.

## Wave 2 — Security, forges, RAG

### RAG / knowledge truthfulness
- `rag/atlas` self-heals: lazy `refresh_index()`, excludes virtualenvs/research/
  site-packages →6,168 first-party symbols in ~3.5s with real hits.
- `KnowledgeTool` — honest description + ranked keyword search (was overclaiming
  "semantic search").
- `faiss-cpu` + `sentence-transformers` moved to optional `[ml]` group in
  `pyproject.toml`; runtime degrades to NumPy/BM25 cleanly.

### Evolution subsystems — stubs made real
- `NexusResearcher` — local evidence-gathering (docs/skills/tools), no LLM.
- `OmniEvolutionKernel` — orchestrates real subsystems with fault isolation.
- `EnsembleManager` — honest candidate scoring → winner.
- `HyperKernel` — module health-check registry.
- Tests: `tests/test_evolution_subsystems/` (14 tests).

### Security audit
- **7 confirmed issues fixed at root cause** (no security disabled), 34 new tests:
  1. HIGH path-traversal/workspace-escape in `tools/reading` and `tools/deleting`
     (prefix-match `startswith` → `os.path.commonpath` containment).
  2. MED workspace escape in `tools/code_search` and `tools/shortcuts` path handling.
  3. MED **token leakage** — `tools/system` `env` action dumped API keys → credential
     name redaction.
  4. MED **SSRF** in `tools/web_search._fetch_url` (loopback/private/link-local/
     cloud-metadata blocked; operator opt-out `NEXUS_WEB_FETCH_ALLOW_PRIVATE=1`).
  5. MED sandbox workspace guard bypass via `%VAR%`/`$VAR` expansion (now `expandvars`).
  6. `.gitignore` hardened (`.key`/`.pem`/`.p12`/`.pfx`/`.oauth_store.json`).
- Verified OK: no hardcoded secrets in source, no command injection, no unsafe
  deserialization, webhook signatures correct, no token leakage in logs.
- Tests: `tests/test_security/` (34 tests). Residual/external-only items documented.

## Infrastructure
- Reusable specialist subagents in `.claude/agents/` (provider-engineer,
  memory-gate, gateway-engineer, evolution-engineer, auth-fixer, rag-keeper,
  nexus-dev).
- `docs/RUNTIME_FLOW.md` — message→answer runtime map.

## Known external blockers (honest)
- OAuth logins need real registered client credentials for claude/gemini/grok/
  openrouter/qwen/chutes (code paths work; live auth requires real app IDs).
- Codex/Claude/Copilot OAuth tokens need runtime endpoints in `provider.yml`.
- Some gateway platforms (LINE/Teams/Feishu/Qi…) have inbound parsers but no
  server route wiring them.
