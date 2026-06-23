# NEXUS Roadmap Status

This status is generated from real repository files and implemented systems.

- Total items: 29
- Done: 7
- Partial: 21
- Removed: 1
- Weighted completion: 64.3%

> **Note:** The codebase has been restructured. Several paths originally referenced (`tools/nexus_tools/*`, `cognition/`, `code_intel/`, `os_power/`, `hive/`, `world_model/`, `optimization/`) have been reorganized or superseded. Evidence paths below are historical; see `docs/ARCHITECTURE.md` for current directory layout.

## Item Status

| Phase | Status | Item | Evidence | Remaining |
| --- | --- | --- | --- | --- |
| Phase 1 | partial | Git-aware patch ledger with automatic revert points | evolution/ledger/ | Git integration is limited because this workspace is not a Git repo. |
| Phase 1 | partial | Repo map cache with incremental updates | tools/code_search/ | Incremental graph invalidation is still coarse; refresh is mostly full rebuild. |
| Phase 1 | partial | LSP diagnostics integration | evolution/logs/ | Diagnostics are compile/schema/build based; no live LSP server adapter yet. |
| Phase 1 | done | Test-fix loop with failure memory | evolution/self_improvement/scripts/engine.py, evolution/memory_forge/ | none |
| Phase 1 | partial | Tool result contracts and structured observations | tools/<name>/scripts/, evolution/ledger/ | Tool schemas are not yet strictly validated for every tool. |
| Phase 1 | done | Deterministic command risk policy | sandbox/risk.py, permissions/, tools/bash/scripts/bash.py | none |
| Phase 1 | partial | Provider latency registry, health status API, and fallback tuning | providers/router.py, providers/base.py, config/ | gui provider health is still basic; cost tracking is not complete. |
| Phase 1 | partial | gui request audit viewer | gui/api.py, gui/src/App.tsx, optimization/mission_replay.py, optimization/unified_graph.py | Audit control plane exists; needs richer filters/export/replay UX. |
| Phase 2 | done | Hybrid BM25 + vector retrieval | rag/ | none |
| Phase 2 | partial | Timeline memory with decay and importance ranking | evolution/memory_forge/scripts/forge.py | Temporal/episodic memory is basic and deterministic. |
| Phase 2 | done | Project knowledge graph linking files, symbols, tests, failures, and decisions | evolution/knowledge_forge/scripts/forge.py, tools/knowledge/ | none |
| Phase 2 | done | Memory cleanup jobs to remove stale or low-value facts | evolution/memory_forge/scripts/forge.py, tools/memory/ | none |
| Phase 2 | partial | Retrieval regression set for project-specific memory | tests/ | Dedicated RAG answer-quality benchmark set is still thin. |
| Phase 2 | partial | Promote adaptive memory graph into a hybrid graph/vector store | evolution/memory_forge/, tools/memory/ | Memory is graph plus search; not a production vector graph database. |
| Phase 2 | partial | Add contradiction review UI and memory provenance browser | evolution/memory_forge/ | No gui UI for contradiction/provenance review yet. |
| Phase 3 | done | Background job manager | tools/system/scripts/system.py | none |
| Phase 3 | partial | Long-task checkpointing and resume | context/ | Resume is file-backed but not deeply integrated into every long mission. |
| Phase 3 | partial | Hive task economy with explicit artifacts | orchestrators/mission_control.py, evolution/ledger/ | Task economy, artifacts, contracts, and handoffs exist; role-specific LLM workers remain partial. |
| Phase 3 | partial | Role-specific LLM execution adapters for Hive tasks | orchestrators/ | Hive contracts/handoffs exist; independent per-role model adapters are not complete. |
| Phase 3 | partial | Predictive debugging from historical failures | evolution/self_improvement/, evolution/intent/ | Prediction is heuristic, not learned from a large failure corpus. |
| Phase 3 | partial | Benchmark trainer that turns failures into regression tests | evolution/self_improvement/scripts/engine.py | Automatic test file generation from failures is not complete. |
| Phase 3 | partial | Self-improvement loop with verified persistence | evolution/self_improvement/scripts/engine.py | Requires stronger benchmark gates before automatic prompt/tool changes. |
| Phase 4 | partial | Authenticated gui | gui/api.py | Current posture is local-first hardening; full auth UX is not complete. |
| Phase 4 | partial | Profiles for coding, research, automation, architecture, and bug hunt | prompts/, orchestrators/architect.py, evolution/ | Profiles are mostly prompt/tool conventions, not a complete product switcher. |
| Phase 4 | partial | MCP-compatible tool/plugin SDK | mcp/, docs/MCP_CODE_GRAPH.md | Current MCP export is code-graph focused, not full SDK. |
| Phase 4 | done | Provider health checks and fallback router | providers/base.py, providers/router.py | none |
| Phase 4 | partial | CI template and release packaging | .github/workflows/, pyproject.toml | Release publishing workflow is not complete. |
| Phase 5 | partial | Local-first autonomous engineering OS moat | evolution/version/, tools/<name>/ | Still experimental; gui UX, graph RAG, and production packaging remain major gates. |
| Cross-Cut | removed | Browser/computer-use automation with screenshots and action logs | Deleted | Browser automation completely removed to simplify platform architecture. |

## Next Completion Gates

1. Add a real gui audit timeline for mission replay, evidence, tool economy, and unified graph events.
2. Add live LSP integration on top of the current compile/build diagnostics.
3. Promote graph/RAG retrieval into a tested multi-hop GraphRAG path.
4. Finish role-specific LLM swarm adapters with explicit agent contracts.
5. Add release packaging/publishing checks and stronger gui auth UX.
