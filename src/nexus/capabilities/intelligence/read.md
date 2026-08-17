# Intelligence

MoE Router, NATE tool engine, and intelligence subsystems.

**Version:** 2.0.0

## Components
- `moe_router.py` — `NexusMoERouter`: provider routing with auto-detection, fallback chains, profile switching, 8-attempt fallback loop, thinking mode
- `moa.py` — `MixtureOfArchitects`: hybrid compatibility facade that delegates
  to the configured MoE provider mesh and never returns fake empty success
- `local_brain.py` — `NexusLocalBrain`: lazy local-provider adapter with
  bounded provider fallback and explicit unsupported-vision errors
- `nate/` — NATE 5-layer fused tool calling runtime:
  - `nate_engine.py` — Main NATE engine with layer fusing and A/B testing
  - `adaptive_schema.py` — AdaptiveSchemaEngine + NATE_Route: embedding-based tool router (all-MiniLM-L6-v2 + FAISS)
  - `universal_adapter.py` — UniversalTool/UniversalAdapter: auto-converts tool schemas between provider formats
  - `execution_graph.py` — ToolGraph + ExecutionGraph: Dijkstra shortest-path on tool DAG
  - `gene_map.py` — GeneMap + SelfHealingEngine: triple-redundant recovery (RL Q-learning + longest-prefix + strategy fallback)
