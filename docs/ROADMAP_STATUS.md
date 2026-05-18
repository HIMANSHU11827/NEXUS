# NEXUS Roadmap Status

This status is generated from real repository files and implemented systems.

- Total items: 29
- Done: 7
- Partial: 22
- Missing: 0
- Weighted completion: 62.1%

## Item Status

| Phase | Status | Item | Evidence | Remaining |
| --- | --- | --- | --- | --- |
| Phase 1 | partial | Git-aware patch ledger with automatic revert points | core/os_power/patch_ledger.py, tools/nexus_tools/advanced_power_tool.py | Git integration is limited because this workspace is not a Git repo. |
| Phase 1 | partial | Repo map cache with incremental updates | core/code_intelligence/repo_map.py, core/code_intelligence/knowledge_graph.py, workspace/code_graph.json | Incremental graph invalidation is still coarse; refresh is mostly full rebuild. |
| Phase 1 | partial | LSP diagnostics integration | core/code_intelligence/diagnostics.py | Diagnostics are compile/schema/build based; no live LSP server adapter yet. |
| Phase 1 | done | Test-fix loop with failure memory | core/aurora/failure_vaccine.py, core/cognition/memory_graph.py, workspace/failure_vaccines.jsonl | none |
| Phase 1 | partial | Tool result contracts and structured observations | tools/nexus_tools/base_tool.py, core/aurora/mission_replay.py, core/aurora/evidence_ledger.py | Tool schemas are not yet strictly validated for every tool. |
| Phase 1 | done | Deterministic command risk policy | core/autonomy/risk.py, core/permissions.py, tools/nexus_tools/bash_tool.py | none |
| Phase 1 | partial | Provider latency registry, health status API, and fallback tuning | core/providers/router.py, core/providers/base.py, core/config_loader.py | Dashboard provider health is still basic; cost tracking is not complete. |
| Phase 1 | partial | Dashboard request audit viewer | dashboard/api.py, dashboard/src/App.tsx, core/aurora/mission_replay.py, core/aurora/unified_graph.py | Audit control plane exists; needs richer filters/export/replay UX. |
| Phase 2 | done | Hybrid BM25 + vector retrieval | rag/engine.py, rag/turbo_vector.py | none |
| Phase 2 | partial | Timeline memory with decay and importance ranking | core/cognition/memory_graph.py | Temporal/episodic memory is basic and deterministic. |
| Phase 2 | done | Project knowledge graph linking files, symbols, tests, failures, and decisions | core/code_intelligence/knowledge_graph.py, core/aurora/unified_graph.py, workspace/unified_graph.json | none |
| Phase 2 | done | Memory cleanup jobs to remove stale or low-value facts | core/cognition/memory_graph.py, tools/nexus_tools/advanced_power_tool.py | none |
| Phase 2 | partial | Retrieval regression set for project-specific memory | tests/test_cognition.py, tests/test_hardening.py | Dedicated RAG answer-quality benchmark set is still thin. |
| Phase 2 | partial | Promote adaptive memory graph into a hybrid graph/vector store | core/cognition/memory_graph.py, core/aurora/unified_graph.py | Memory is graph plus search; not a production vector graph database. |
| Phase 2 | partial | Add contradiction review UI and memory provenance browser | core/cognition/memory_graph.py | No dashboard UI for contradiction/provenance review yet. |
| Phase 3 | done | Background job manager | core/os_power/process_manager.py | none |
| Phase 3 | partial | Long-task checkpointing and resume | core/context/persistence.py, core/aurora/mission_replay.py | Resume is file-backed but not deeply integrated into every long mission. |
| Phase 3 | partial | Multi-agent task economy with explicit artifacts | core/swarm.py, core/aurora/tool_economy.py | Task economy, artifacts, contracts, and handoffs exist; role-specific LLM workers remain partial. |
| Phase 3 | partial | Role-specific LLM execution adapters for swarm tasks | core/swarm.py | Swarm contracts/handoffs exist; independent per-role model adapters are not complete. |
| Phase 3 | partial | Predictive debugging from historical failures | core/aurora/failure_vaccine.py, core/cognition/intent_forecaster.py | Prediction is heuristic, not learned from a large failure corpus. |
| Phase 3 | partial | Benchmark trainer that turns failures into regression tests | core/aurora/failure_vaccine.py, core/evaluation/benchmark.py | Automatic test file generation from failures is not complete. |
| Phase 3 | partial | Self-improvement loop with verified persistence | core/cognition/self_improvement.py, workspace/self_improvement.json | Requires stronger benchmark gates before automatic prompt/tool changes. |
| Phase 4 | partial | Authenticated dashboard | dashboard/api.py | Current posture is local-first hardening; full auth UX is not complete. |
| Phase 4 | partial | Profiles for coding, research, automation, architecture, and bug hunt | core/prompts.py, orchestrators/architect.py | Profiles are mostly prompt/tool conventions, not a complete product switcher. |
| Phase 4 | partial | MCP-compatible tool/plugin SDK | integrations/mcp_server.py, docs/MCP_CODE_GRAPH.md, pyproject.toml | Current MCP export is code-graph focused, not full SDK. |
| Phase 4 | done | Provider health checks and fallback router | core/providers/base.py, core/providers/router.py, tests/test_provider_routing.py | none |
| Phase 4 | partial | CI template and release packaging | .github/workflows/ci.yml, pyproject.toml | Release publishing workflow is not complete. |
| Phase 5 | partial | Local-first autonomous engineering OS moat | core/aurora/unified_graph.py, core/code_intelligence/agent_context.py, tools/nexus_tools/advanced_power_tool.py | Still experimental; dashboard UX, graph RAG, and production packaging remain major gates. |
| Cross-Cut | partial | Browser/computer-use automation with screenshots and action logs | core/browser_automation/agent_browser.py, tools/nexus_tools/advanced_power_tool.py, docs/BROWSER_AUTOMATION.md | Real Playwright browser execution is optional and depends on installing browser extras. |

## Next Completion Gates

1. Add a real dashboard audit timeline for mission replay, evidence, tool economy, and unified graph events.
2. Add live LSP integration on top of the current compile/build diagnostics.
3. Promote graph/RAG retrieval into a tested multi-hop GraphRAG path.
4. Finish role-specific LLM swarm adapters with explicit agent contracts.
5. Add release packaging/publishing checks and stronger dashboard auth UX.
