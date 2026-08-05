# NEXUS AI — Prioritized Issue List (Real-Shell Testing)
# Generated: 2026-08-03

## P0 — CRITICAL: Nexus cannot complete real work, falsely claims success

### P0-1: LLM API calls lack tool/function definitions
- **Trigger**: Any user request requiring tool execution
- **Expected**: LLM receives tool definitions via `tools` parameter, can use native function calling
- **Actual**: `_call_model` and `_stream_model` in `model.py` pass only `messages` — no `tools` parameter
- **Root cause**: The model layer was designed for text-only interactions; tool calling via native function calling was never implemented
- **Impact**: LLM generates natural language claims about completing work instead of executing actual tool calls
- **Files**: `orchestrators/v5/model.py` (lines 54-87, 177-246)
- **Fix**: Add `tools` parameter support to model calls; pass tool definitions from the tool registry

### P0-2: Tool execution stub returns fake output
- **Trigger**: Any code path using `_execute_tools` 
- **Expected**: Real tool execution with actual results
- **Actual**: Returns hardcoded `["[tool_output]"]`
- **Root cause**: Method is a V1 compatibility stub (line 972-973 in core.py)
- **Files**: `orchestrators/v5/core.py:972-973`

### P0-3: False success claims stored in memory
- **Trigger**: LLM generates text like "I created the file" without tool execution
- **Expected**: Memory only stores verified results
- **Actual**: Memory records hallucinated claims as facts
- **Files**: `memory/__init__.py`, orchestration pipeline

## P1 — CORE WORKFLOW BROKEN

### P1-1: FAISS not installed — warning printed 19 times
- **Trigger**: Every import of tool/NATE modules
- **Expected**: Single warning or graceful fallback
- **Actual**: "FAISS not installed" printed 19 times on every import
- **Files**: NATE engine, tool initialization
- **Fix**: Log warning once; suppress repeat messages

### P1-2: Server startup takes 30+ seconds
- **Trigger**: `python -m nexus --server`
- **Expected**: Startup in < 10 seconds
- **Actual**: 30+ seconds, causes shell timeouts
- **Root cause**: Lazy initialization of 19 subsystems on first request

### P1-3: Windows command incompatibility  
- **Trigger**: Shell commands on Windows
- **Expected**: Uses Windows commands (type, Get-Content)
- **Actual**: Uses Unix commands (cat)

## P2 — PARTIALLY WORKING

### P2-1: Tool registry list_tools() returns strings, not structured data
- **Files**: `tools/nexus_tools/registry.py`

### P2-2: Some skills/plugin integrations are stubs
- **Files**: `intelligence/moa.py`, `intelligence/local_brain.py`, `tools/reasoning/`

## P3 — MINOR

### P3-1: Deprecation warnings (starlette httpx)
### P3-2: Pip upgrade notice on every install
