# Orchestrators

Multi-step agent pipelines, mission control, and the sovereign reasoning loop.

**Version:** 1.0.0

## Components
- `loop.py` — `NexusLoop`: 7-state sovereign cognitive loop (GROUNDING → PLANNING → INFERENCE → AUDITING → EXECUTION → VERIFICATION → EVOLVE)
- `mission_control.py` — `MissionOrchestrator`: multi-step mission object with artifacts
- `architect.py` — `NexusArchitect`: roadmap/planning agent (Tier 2 complexity)
- `read.md` — this file