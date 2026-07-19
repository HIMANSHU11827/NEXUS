# Orchestrators

Multi-step agent pipelines, mission control, and the sovereign reasoning loop.

**Version:** 1.0.0

## Components
- `loop.py` — `NexusLoop`: unified model/tool loop (GROUNDING → INFERENCE ↔ AUDITING/EXECUTION/VERIFICATION → FINALIZE)
- Context sources load concurrently and selectively; safe read tools run in parallel while writes remain sequential.
- Permission/risk checks are deterministic; one session loop owns one active run and request provider/model overrides do not leak into other sessions.
- Sandbox stdout/stderr, generator-based tool output, and canonical lifecycle events propagate live. Model text is held until safe tool-protocol classification and then returned as content.
- `architect.py` is legacy compatibility code; normal planning uses `todo.md` and the registered `planning` tool from `NexusLoop`.
- `mission_control.py` — `MissionOrchestrator`: multi-step mission object with artifacts
- `architect.py` — `NexusArchitect`: roadmap/planning agent (Tier 2 complexity)
- `read.md` — this file
