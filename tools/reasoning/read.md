# Reasoning Tool

LLM-backed chain-of-thought reasoning — planner, critic, and verifier pipeline.

**Version:** 3.0.0

## Behavior
- Runs on `HyperReasoningEngine` (`reasoning/hyper_engine.py`) with an LLM planner, critic, and verifier via `NexusProviderFactory`
- Deterministic keyword/heuristic fallback when no provider/LLM is reachable (never fails)
- Problem decomposition with per-step suggested tools, risk, and verifier
- Uncertainty estimation in the 0.2–0.95 range
- Final `averify` verdict: PASS/FAIL with a reason

See `reasoning.md` for parameters.
