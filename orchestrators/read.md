# Orchestrators

Sovereign reasoning loop — the core agent orchestration layer.

**Version:** 2.0.0

## Components
- `loop.py` — `NexusLoop` (3555 lines): unified model/tool loop (GROUNDING → INFERENCE ↔ AUDITING/EXECUTION/VERIFICATION → FINALIZE)
- Context sources load concurrently and selectively; safe read tools run in parallel while writes remain sequential.
- Permission/risk checks are deterministic; one session loop owns one active run; provider/model overrides do not leak between sessions.
- 8 tool call extraction strategies: colon-function, inline JSON, dotted, compact XML, action fences, explicit run, explicit file, DSML invoke
- HookRegistry for lifecycle events; SelfImprovementEngine, EvolutionLog, SkillCurator integration
- `architect.py` (legacy) and `mission_control.py` have been removed — planning uses `todo.md` + `planning` tool
- Permission modes: AUTO, AI_DECIDE, ASK_ALL, CHECKLIST
