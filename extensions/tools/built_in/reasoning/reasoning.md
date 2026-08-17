# Reasoning Tool
**Version:** 3.0.0 — LLM planner + critic + verifier (`HyperReasoningEngine`).

Deep chain-of-thought reasoning powered by `reasoning/hyper_engine.py`.

## Parameters
- `problem` (string, required): Problem to reason about
- `depth` (string, optional, default=detailed): simple | detailed | deep
- `steps` (int, optional, default=5): Maximum reasoning steps
- `context` (string, optional): Additional context for reasoning

## Features
- **LLM planner**: rationale plus per-step objectives with suggested tool, risk rating, and verifier
- **Critic**: flags blocking issues; replan signal and confidence feed uncertainty
- **Verifier**: final `averify` result — PASS/FAIL with an evidence-based reason
- **Deterministic fallback**: keyword/heuristic scaffolding when the LLM is unavailable
- **Decomposition**: step count capped by depth — simple=3, detailed=5, deep=8
- **Uncertainty estimation**: 0.2–0.95 from task length, step count, and critic confidence
