# NEXUS Roadmap Status

This status is generated from real repository files and implemented systems.

- Total items: 29
- Done: 7
- Partial: 21
- Removed: 1
- Weighted completion: 64.3%

## Item Status

| Phase | Status | Item | Evidence | Remaining |
| --- | --- | --- | --- | --- |
| Phase 1 | partial | Git-aware patch ledger with automatic revert points | os_power/patch_ledger.py, tools/nexus_tools/advanced_power_tool.py | Git integration is limited because this workspace is not a Git repo. |
| Phase 1 | partial | Repo map cache with incremental updates | code_intel/repo_map.py, code_intel/knowledge_graph.py, workspace/code_graph.json | Incremental graph invalidation is still coarse; refresh is mostly full rebuild. |
| Phase 1 | partial | LSP diagnostics integration | code_intel/diagnostics.py | Diagnostics are compile/schema/build based; no live LSP server adapter yet. |
| Phase 1 | done | Test-fix loop with failure memory | optimization/failure_vaccine.py, cognition/memory_graph.py, workspace/failure_vaccines.jsonl | none |
| Phase 1 | partial | Tool result contracts and structured observations | tools/nexus_tools/base_tool.py, optimization/mission_replay.py, optimization/evidence_ledger.py | Tool schemas are not yet strictly validated for every tool. |
| Phase 1 | done | Deterministic command risk policy | sandbox/risk.py, permissions/, tools/nexus_tools/bash_tool.py | none |
| Phase 1 | partial | Provider latency registry, health status API, and fallback tuning | providers/router.py, providers/base.py, config_loader/ | gui provider health is still basic; cost tracking is not complete. |
| Phase 1 | partial | gui request audit viewer | gui/api.py, gui/src/App.tsx, optimization/mission_replay.py, optimization/unified_graph.py | Audit control plane exists; needs richer filters/export/replay UX. |
| Phase 2 | done | Hybrid BM25 + vector retrieval | rag/engine.py, rag/turbo_vector.py | none |
| Phase 2 | partial | Timeline memory with decay and importance ranking | cognition/memory_graph.py | Temporal/episodic memory is basic and deterministic. |
| Phase 2 | done | Project knowledge graph linking files, symbols, tests, failures, and decisions | code_intel/knowledge_graph.py, optimization/unified_graph.py, workspace/unified_graph.json | none |
| Phase 2 | done | Memory cleanup jobs to remove stale or low-value facts | cognition/memory_graph.py, tools/nexus_tools/advanced_power_tool.py | none |
| Phase 2 | partial | Retrieval regression set for project-specific memory | tests/test_cognition.py, tests/test_hardening.py | Dedicated RAG answer-quality benchmark set is still thin. |
| Phase 2 | partial | Promote adaptive memory graph into a hybrid graph/vector store | cognition/memory_graph.py, optimization/unified_graph.py | Memory is graph plus search; not a production vector graph database. |
| Phase 2 | partial | Add contradiction review UI and memory provenance browser | cognition/memory_graph.py | No gui UI for contradiction/provenance review yet. |
| Phase 3 | done | Background job manager | os_power/process_manager.py | none |
| Phase 3 | partial | Long-task checkpointing and resume | context/persistence.py, optimization/mission_replay.py | Resume is file-backed but not deeply integrated into every long mission. |
| Phase 3 | partial | Hive task economy with explicit artifacts | hive/engine.py, optimization/tool_economy.py | Task economy, artifacts, contracts, and handoffs exist; role-specific LLM workers remain partial. |
| Phase 3 | partial | Role-specific LLM execution adapters for Hive tasks | hive/engine.py | Hive contracts/handoffs exist; independent per-role model adapters are not complete. |
| Phase 3 | partial | Predictive debugging from historical failures | optimization/failure_vaccine.py, cognition/intent_forecaster.py | Prediction is heuristic, not learned from a large failure corpus. |
| Phase 3 | partial | Benchmark trainer that turns failures into regression tests | optimization/failure_vaccine.py, evaluation/benchmark.py | Automatic test file generation from failures is not complete. |
| Phase 3 | partial | Self-improvement loop with verified persistence | cognition/self_improvement.py, workspace/self_improvement.json | Requires stronger benchmark gates before automatic prompt/tool changes. |
| Phase 4 | partial | Authenticated gui | gui/api.py | Current posture is local-first hardening; full auth UX is not complete. |
| Phase 4 | partial | Profiles for coding, research, automation, architecture, and bug hunt | prompts/, orchestrators/architect.py | Profiles are mostly prompt/tool conventions, not a complete product switcher. |
| Phase 4 | partial | MCP-compatible tool/plugin SDK | mcp/server.py, docs/MCP_CODE_GRAPH.md, pyproject.toml | Current MCP export is code-graph focused, not full SDK. |
| Phase 4 | done | Provider health checks and fallback router | providers/base.py, providers/router.py, tests/test_provider_routing.py | none |
| Phase 4 | partial | CI template and release packaging | .github/workflows/ci.yml, pyproject.toml | Release publishing workflow is not complete. |
| Phase 5 | partial | Local-first autonomous engineering OS moat | optimization/unified_graph.py, code_intel/agent_context.py, tools/nexus_tools/advanced_power_tool.py | Still experimental; gui UX, graph RAG, and production packaging remain major gates. |
| Cross-Cut | removed | Browser/computer-use automation with screenshots and action logs | Deleted | Browser automation completely removed to simplify platform architecture. |

## Next Completion Gates

1. Add a real gui audit timeline for mission replay, evidence, tool economy, and unified graph events.
2. Add live LSP integration on top of the current compile/build diagnostics.
3. Promote graph/RAG retrieval into a tested multi-hop GraphRAG path.
4. Finish role-specific LLM swarm adapters with explicit agent contracts.
5. Add release packaging/publishing checks and stronger gui auth UX.
