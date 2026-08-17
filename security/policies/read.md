# Safety

Safety guardrails — deterministic policy evaluation + proof engine + threat scanning.

**Version:** 2.0.0

## Components
- `laws.py` — `NexusLawKernel`: YAML-based sovereign laws with regex audit of tool calls
- `prover.py` — `LogicProver`: shell command safety (7 dangerous patterns), Python AST inspection, neural-symbolic intent proof via ModelRouter, 3-tier gate
- `sovereign_laws.yaml` — 20 lines of law definitions
- Integration with `tools/threat_patterns.py` for content-level threat detection
