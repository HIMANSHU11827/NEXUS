# NexusResearcher

Autonomous deep research agent for multi-source investigation and synthesis.

**Version:** 2.0.0

## Status
Implemented (`IS_STUB = False`) — `scripts/researcher.py` (v0.2.0).

## Components
- `NexusResearcher` — local keyword-based research over the workspace:
  - `research(topic, ...)` — gathers findings across markdown docs, SKILL.md files, and tool metadata, then synthesizes a summary
  - `investigate(question, ...)` — targeted investigation path
  - `status()` — capability/state report
- `_gather(keywords, max_findings)` — keyword-matching scan of candidate files (`_iter_candidates`, `_walk_md`, `_walk_tool_meta`)
- `_synthesize_summary(topic, findings)` — deterministic summary synthesis

## Notes
- Local keyword research only — no LLM calls. Real-world web research is covered by `tools/deep_research` (sub-agent based).
- Covered by `tests/test_evolution_subsystems/` (asserts `is_stub is False`).
