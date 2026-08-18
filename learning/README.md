# learning — Learning loop (meta-learning, evidence, memory)

## Authoritative implementation
- `src/nexus/main_agent/meta.py` — `MetaLearningLayer`: hyperparameter optimization, architecture search, experience replay, strategy selection
- `src/nexus/main_agent/learning.py` — `V5Learning` mixin: deterministic per-turn learning signals (no LLM), replay audit to `.nexus/v5/replays.jsonl`
- `src/nexus/main_agent/learning_evidence.py` — `LearningEvidenceStore` at `.nexus/v5/evidence.jsonl`: provenance-bearing records; only tool-verified outcomes may be `"verified"`, model prose is always `"assumption"`
- `evolution/self_improvement/scripts/engine.py` — `SelfImprovementEngine`: session analysis → `ImprovementRecord`, logged to `.nexus/logs/improvements/self_improvement.jsonl`
- `memory/__init__.py` — `MemoryManager`: unified `prefetch_all` / `sync_all` API, token budgets, evidence-gated durable fact sinks

## Why this directory exists
This is the approved home for the learning loop. The implementations live in `src/nexus/main_agent/`, `evolution/self_improvement/scripts/`, and `memory/`; `learning/` owns the responsibility map.

## Notes
All learning mixins are defensive (never raise) and write runtime state under `.nexus/` — never into source directories.