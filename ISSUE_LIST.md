# NEXUS AI — Prioritized Issue List (Real-Shell Testing)
# Generated: 2026-08-03 | Last reviewed: 2026-08-08

> Status legend: ✅ Resolved · 🟡 Partially resolved · ❌ Open

## P0 — CRITICAL: Nexus cannot complete real work, falsely claims success

### P0-1: LLM API calls lack tool/function definitions — ✅ Resolved
- **Trigger**: Any user request requiring tool execution
- **Expected**: LLM receives tool definitions via `tools` parameter, can use native function calling
- **Actual**: `_call_model` and `_stream_model` in `model.py` pass only `messages` — no `tools` parameter
- **Root cause**: The model layer was designed for text-only interactions; tool calling via native function calling was never implemented
- **Impact**: LLM generates natural language claims about completing work instead of executing actual tool calls
- **Files**: `orchestrators/v5/model.py` (lines 54-87, 177-246)
- **Fix**: Add `tools` parameter support to model calls; pass tool definitions from the tool registry
- **Status**: Fixed in the V5 direct model/tool loop — tool definitions are now passed from the live `ToolRegistry` (see `tests/v5/` and `LOOP_RESEARCH_REPORT.md`)

### P0-2: Tool execution stub returns fake output — ✅ Resolved
- **Trigger**: Any code path using `_execute_tools` 
- **Expected**: Real tool execution with actual results
- **Actual**: Returns hardcoded `["[tool_output]"]`
- **Root cause**: Method is a V1 compatibility stub (line 972-973 in core.py)
- **Files**: `orchestrators/v5/core.py:972-973`
- **Status**: Resolved — the V5 loop now executes real tool calls (extraction strategies, permission policies, PAORR integrity — see `LOOP_RESEARCH_REPORT.md`)

### P0-3: False success claims stored in memory — ✅ Resolved
- **Trigger**: LLM generates text like "I created the file" without tool execution
- **Expected**: Memory only stores verified results
- **Actual**: Memory records hallucinated claims as facts
- **Files**: `memory/__init__.py`, orchestration pipeline
- **Status**: Fixed — `MemoryManager` now gates storage on verified evidence (`verified_result_id`/evidence → `verified`, otherwise `llm_claim`); covered by `tests/test_memory_manager/scripts/test_memory_manager.py` (VerifiedMemoryGate)

## P1 — CORE WORKFLOW BROKEN

### P1-1: FAISS not installed — repeated fallback warning — ✅ Resolved
- **Trigger**: Every import of tool/NATE modules
- **Expected**: Single warning or graceful fallback
- **Actual (historical)**: "FAISS not installed" was reported repeatedly by
  callers creating multiple NATE routers
- **Files**: NATE engine, tool initialization
- **Fix**: `NATE_Route._lazy_load_faiss()` uses a process-wide class guard and
  keeps FAISS loading lazy; missing FAISS falls back to NumPy search without
  import-time model/index initialization
- **Verification (2026-08-11)**: 19 forced-missing-FAISS router registrations
  emitted exactly one warning; all routers used the NumPy fallback. The NATE
  routing/adaptive-schema regression partition passed `33 tests`.

### P1-2: Server startup takes 30+ seconds — ✅ Resolved / historical
- **Trigger**: `python -m nexus --server`
- **Expected**: Startup in < 10 seconds
- **Actual (2026-08-11)**: current server import was ~346 ms, FastAPI lifespan
  entry ~3 ms, TestClient startup ~254 ms, and real `python -m nexus --server`
  reached port 8000 in ~1.3 seconds
- **Historical root cause**: not reproduced in the current checkout; the
  previous 30+ second measurement is stale and is not evidence for changing
  lazy initialization
- **Additional fix**: the launcher now gives `python -m server` its own process
  group and terminates/reaps the complete owned tree on shutdown, preventing a
  launcher exit from leaving an API child listening on port 8000
- **Verification**: `35 passed` across boot, queue-supervisor, and command
  timeout surfaces; the real launcher reached readiness in `1302 ms`

### P1-3: Windows command incompatibility — ✅ Resolved
- **Trigger**: Shell commands on Windows
- **Expected**: Uses Windows commands (type, Get-Content)
- **Historical actual**: Unix commands such as `cat` could reach the default
  Windows `cmd.exe` path and fail without a useful recovery signal
- **Fix**: the sandbox now detects common unquoted Unix command tokens
  (`cat`, `grep`, `sed`, `awk`, `head`, `tail`, `ls`, `pwd`, `which`) before
  spawning `cmd.exe`, while preserving explicit PowerShell/Bash requests. It
  returns exact recovery guidance (`type`/`findstr`/`more` or
  `shell='powershell'`).
- **Verification (2026-08-11)**: a simulated Windows execution of
  `cat README.md | grep Nexus` was blocked before spawn; sandbox/security
  partitions passed `20 tests`.

## P2 — PARTIALLY WORKING

### P2-1: Tool registry list_tools() returns strings, not structured data — ✅ Resolved / historical
- **Historical actual**: callers were once described as receiving only tool
  names
- **Current contract**: `ToolRegistry.list_tools()` returns a structured
  `Dict[name, summary]` containing version, description, availability,
  missing environment, handler presence, and execution constitution details;
  unavailable entries are opt-in for diagnostics/UI inventory
- **Files**: `tools/nexus_tools/registry.py`
- **Verification (2026-08-11)**: explicit structured-contract regression plus
  registry, MCP, security, and V5 caller suites passed (`112 tests`)

### P2-2: Some skills/plugin integrations are stubs — ✅ Resolved for runtime paths
- **Files**: `intelligence/moa.py`, `intelligence/local_brain.py`, `tools/reasoning/`
- **Status**: `tools/reasoning/` is a real LLM-backed engine; HYBRID routing now
  delegates to the configured provider mesh instead of returning an empty fake
  response; the local-brain path now uses configured local providers with
  explicit bounded fallback/error semantics. `scan_image()` reports a truthful
  capability error until a local vision provider is configured.
- **Verification (2026-08-11)**: adapter, kernel, provider-router, skill, and
  plugin regression partition passed `57 tests`.
- **Remaining capability gap**: a true multi-architect ensemble and local
  vision inference are optional future capabilities, not silent stubs.

## P3 — MINOR

### P3-1: Deprecation warnings (starlette httpx) — ❌ Open
### P3-2: Pip upgrade notice on every install — ❌ Open
