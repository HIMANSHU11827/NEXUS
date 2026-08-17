# Reasoning Engine

Hyper reasoning engine — deterministic planner/critic/verifier with uncertainty scoring and replan triggers.

**Version:** 2.0.0

## Capabilities
- `HyperReasoningEngine` — produces `ReasoningPlan` with typed `ReasoningStep` objects
- Heuristic uncertainty scoring (0.2–0.95) based on task complexity
- `critique(plan)` — returns critiques (high uncertainty, missing verification, high risk)
- `should_replan(plan, observations)` — detects errors/failures in observations
- Suggested tool mappings for common tasks: understand, reproduce, edit, security, verify, summarize
