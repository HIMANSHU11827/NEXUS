# NEXUS Memory Store

Unified memory system for NEXUS AI. Stores episodic, working, semantic, and procedural memories with version tracking and token budgeting.

**Version:** 1.0.0

## Structure
- `__init__.py` — `MemoryManager`: unified orchestrator with `prefetch_all()` / `sync_all()`
- `continuity.py` — evidence-based conversation/task continuity
- `memory.json` — schema metadata (types: episodic, working, semantic, procedural)

## Architecture
- **`MemoryManager`** (`memory/__init__.py`) is the single entry point for all memory systems:
  - `prefetch_all(user_msg)` — pre-turn: loads session history, RAG retrieval, failure vaccines, knowledge vault, and episodic digests **in parallel** (thread pool + asyncio), returning an aggregated `MemoryContext`.
  - `sync_all(user_msg, response, verified_actions, tool_results, verified)` — post-turn: persists the session transcript and syncs cross-session learnings to `.opencode/memory/`, plus background `MemoryForge` runs — all **gated on verified evidence** so raw model prose is never stored as a durable fact.
  - Session files live at `logs/sessions/<session_id>.json`; a fresh process resumes the most recent session automatically.
- **Episodic memory**: scored from `<root>/.nexus_v5/replays.jsonl` with Smallville-style recency·α + relevance·β + importance·γ weights; failures get top relevance/importance.
- **Memory budget / expiry**: `MemoryBudget` (per-write `max_fact_tokens` + store-growth `max_entries`, explicit `[truncated N chars]` elision markers) and `expire()` (age-based eviction where **verified facts are exempt**, plus a hard-cap fallback).
- **Hybrid persistence**: JSONL (`replays.jsonl`) + in-memory slots (`episodic`/`working`/`semantic`/`procedural`) + JSON session transcripts + `.opencode/memory/` markdown files.

## Continuity
- `ContinuitySnapshot` dataclass with `as_prompt()` — surfaces only unfinished work backed by **durable evidence** (run contexts, `.nexus_v5/checkpoints` with non-terminal phases, `workspace/todo.md`, task queue) via `inspect_continuity()`.

## Memory Types
- **Episodic** — scored replay digests of past turns
- **Working** — current-session state slots
- **Semantic** — knowledge-vault / RAG-derived context
- **Procedural** — `.opencode/memory/` cross-session learnings and failure vaccines
