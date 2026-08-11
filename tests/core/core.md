# Test Core

Core system tests covering runtime contracts, task workflow, web search, tool approval, and the evolution subsystem.

**Version:** 2.0.0

## Files
- `scripts/test_runtime.py` — `nexus/runtime` contracts: safe session/turn IDs, session file path confinement, `parse_max_tokens`, `build_chat_request` normalization (prompt trimming, provider/model normalization, empty-prompt rejection), `build_resume_prompt`
- `scripts/test_task_workflow.py` — `nexus/task_workflow`: `start_task_workflow` reuses a resume snapshot; `complete_task_workflow` marks running todos `failed` on error (dependency-injected adapters, no real services)
- `scripts/test_web_search.py` — `tools/web_search`: "today" queries retried with `latest` variants via a mocked `_search`; DuckDuckGo results parser captures real source metadata
- `test_approval_broker.py` — `permissions/approval_broker` (Co-Pilot ask-mode): decision normalization (unknown answers never mean consent), waiter/request resolution, decisions posted before the agent waits are not lost
- `test_evolution/scripts/test_evolution.py` — `evolution` subsystem basics: imports of the 13 public classes plus instantiation/record flows for EvolutionLog, EvolutionLedger, and the forges
