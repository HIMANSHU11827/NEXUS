# NATE — NEXUS Native Tool Engine

## What Is NATE?

NATE is a 5-layer fused runtime for universal tool calling. Zero MCP overhead. Any model, any tool, any provider.

Write tool definitions once in OpenAI-format JSON Schema. NATE auto-converts to Anthropic, Google, Ollama, Mistral, Groq, or any other format — no protocol translation cost.

## Layers

### Layer 1 — Universal Format Adapter (`universal_adapter.py`)
One `UniversalTool` definition auto-converts to any provider's native format via `.to_provider(provider)`.

### Layer 2 — Adaptive Schema Engine (`adaptive_schema.py`)
- TSCG-style deterministic compression (short field names `n/d/t/p/r`, drop titles/defaults)
- **NATE-Route**: embedding-based semantic tool router (all-MiniLM-L6-v2 + FAISS, replacing old keyword overlap)
- STRAP clustering: tools with cos-sim > 0.85 grouped as one slot
- Dynamic K threshold + necessity gate (sim < 0.30 → no tools)
- Dual-path: absolute (>=0.50) OR relative confidence (gap > 0.10)
- OATS feedback: interpolate embeddings toward success centroid

### Layer 3 — Deterministic Execution Graph (`execution_graph.py`)
- Dijkstra shortest-path routing on a cost-weighted DAG of tool nodes
- Auto-reroute on failure
- Sub-millisecond routing, 0 LLM calls

### Layer 4 — Self-Healing Gene Map (`gene_map.py`)
- Triple-redundant recovery: Gene Map RL Q-value learning + longest-prefix match of tool call sequences + repair strategy fallback
- 0 LLM calls for recovery

### Layer 5 — NATE Engine (`nate_engine.py`)
Fuses all layers: `register_tool()` → `get_schemas()` → `plan()` → `execute()` → `heal()`
`disable_layer()` toggle for A/B comparison.

## NEXUS Integration

### Two-Phase Schema Loader + NATE-Route
- **Phase 1**: Tool names only in stable prompt — ~140 chars (was ~800 before NATE)
- **Phase 2**: NATE-Route picks 2-5 query-relevant tools via embedding similarity, compressed one-liner schemas
- Necessity gate: chat queries get 0 tools (LLM answers directly)
- Dual-path: Path 1 (high confidence, direct) + Path 2 (low confidence, LLM clarifies)

### Real API Results (DeepSeek `deepseek-chat`)
**Before NATE-Route** (old keyword overlap):
| Metric | Before (Raw) | After (NATE) | Savings |
|--------|:-----------:|:-----------:|:------:|
| Schema chars | 3,559 | ~1,731 | **51.4%** |
| Input tokens | 1,087 | 656 | **39.6%** |
| Tool accuracy | 100% | 100% | same |

**After NATE-Route** (all-MiniLM-L6-v2 + FAISS):
| Metric | Before (Raw) | After (NATE-Route) | Savings |
|--------|:-----------:|:----------------:|:------:|
| Schema chars | 3,559 | ~426 | **88.0%** |
| Input tokens | 1,087 | ~355 | **67.4%** |
| Tool accuracy | 100% | 100% | same |
| Chat detection | sends all tools | 0 tools | correct |

### How All 12 Skill Alignment Problems Are Solved
| Problem | NATE-Route Mechanism |
|---------|---------------------|
| Tool Explosion | Catalog size irrelevant, sirf top-3/5 |
| Skill Shadowing | Cosine similarity in 384-dim, not token overlap |
| Looking=Picking | Embedding decides routing, LLM nahi |
| Knowing-Doing Gap | Generation step bypassed |
| Tool Overuse | Necessity gate: sim < 0.30 → 0 tools |
| Structural Bias | Pure semantic similarity |
| Over-Privileged | Embedding doesn't encode privilege |
| Skill Conflict | STRAP: similar tools cluster as one |
| Same-Capability | FAISS top-K from cluster, LLM picks |
| Canonical Drift | Stateless per turn, no drift path |
| Skill Drift | Re-index on tool update |
| Schema Misalignment | Embedding model never sees schema |

## Self-Improving Lifecycle

### Flow
```
NATE runs → logs tool calls + routing → training_data/harvest/
    ↓ (auto-check every 100 queries)
Enough data? → fine-tune embedding + Zupra-50M LoRA
    ↓
Export → GGUF q8_0 (models/local/*.gguf)
    ↓
llama.cpp auto-loads GGUF → local inference
    ↓
Repeat — cycle improves NATE routing + local brain
```

### Files
- `evolution/local_trainer/scripts/embedding_trainer.py` — fine-tune all-MiniLM-L6-v2 on tool-query pairs
- `evolution/local_trainer/scripts/llm_trainer.py` — LoRA fine-tune Zupra-1.6-50M-Instruct-Ultra-exp
- `evolution/local_trainer/scripts/trainer.py` — `LocalTrainer` orchestrator
- `evolution/local_trainer/scripts/lifecycle.py` — `SelfImprovementLifecycle` + `TrainingDataCollector`

### Thresholds
- Embedding fine-tune: 20+ examples (few hours of use)
- Zupra-50M fine-tune: 50+ examples (1-2 days)
- Cycle gap: configurable (default 5 min, set to 86400 for daily)
- Output: GGUF q8_0 → auto-loaded by `LlamaCPPProvider`

## Local Models
| Model | Type | Params | Size | Use |
|-------|------|--------|------|-----|
| all-MiniLM-L6-v2 | Embedding | 22.7M | 80MB | NATE-Route tool routing |
| Zupra-1.6-50M-Instruct-Ultra-exp | LLM | 50M | 103MB | Local offline brain |

### Zupra Provider
- `models/providers/api/zupra.py` — `ZupraProvider` class for local inference
- Registered in `models/providers/core/factory.py` as "zupra"
- No API key needed, fully offline
- ~0.1s load time on CPU

## Files
- `src/nexus/capabilities/intelligence/nate/__init__.py` — exports `NATE`, `NATE_Route`, `AdaptiveSchemaEngine`
- `src/nexus/capabilities/intelligence/nate/universal_adapter.py` — `UniversalTool`, `UniversalAdapter`
- `src/nexus/capabilities/intelligence/nate/adaptive_schema.py` — `TSCGCompressor`, `NATE_Route`, `AdaptiveSchemaEngine`
- `src/nexus/capabilities/intelligence/nate/execution_graph.py` — `ToolGraph`, `ExecutionGraph`
- `src/nexus/capabilities/intelligence/nate/gene_map.py` — `GeneMap`, `SelfHealingEngine`
- `src/nexus/capabilities/intelligence/nate/nate_engine.py` — `NATE` main engine class
- `evolution/local_trainer/scripts/` — lifecycle + fine-tuning system
- `models/providers/api/zupra.py` — Zupra local provider

## Tests
- `tests/test_nate/` — 56 tests across all 5 layers
- `tests/test_nate/scripts/real_llm_test.py` — real DeepSeek API test with before/after comparison

## Dependencies Added
- `sentence-transformers>=2.2` — embedding model for NATE-Route
- `faiss-cpu>=1.7` — fast similarity search
- `numpy>=1.26` — vector operations
- `peft>=0.19` — LoRA fine-tuning
- `datasets>=5.0` — training data
