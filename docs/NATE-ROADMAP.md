# NATE-Route — Zero-Training Universal Tool Router

## Problem
12 skill alignment problems in LLM tool calling — all rooted in **selection bottleneck**, not execution:
1. Tool Explosion (catalog too large)
2. Skill Shadowing (similar tools confuse)
3. Looking≠Picking (reads schema but picks wrong)
4. Knowing-Doing Gap (knows tool but fails to call)
5. Tool Overuse (calls unnecessary tools)
6. Structural Bias (bias toward structural signals)
7. Over-Privileged (privilege leaks into routing)
8. Skill Conflict (70%+ description overlap)
9. Same-Capability Ambiguity (HSR@3 0.693)
10. Canonical Drift (+22.7pp per off-path call)
11. Skill Drift (40% FPR without contracts)
12. Schema Misalignment (80% errors on rename)

## Core Insight
All 12 problems share the same root cause: **LLM sees too many tools**. Fix: send only 3-5 relevant tools. Baaki chhupa do.

## Architecture

```
Query → all-MiniLM-L6-v2 (80MB, CPU) → 384-dim vector
→ FAISS HNSW search against pre-computed tool embeddings
→ Dynamic K (threshold 0.65 pe stop)
→ STRAP: cos-sim > 0.85 tools ko cluster karo, ek slot do
→ Necessity gate: best sim < 0.5 → no tools bhejo
→ Confidence ≥ 0.75 → Path 1 direct (~80% calls)
→ Confidence < 0.75 → Path 2 LLM clarify → re-embed → retry
```

## How Each Problem Is Solved

| # | Problem | Mechanism |
|---|---------|-----------|
| 1 | Tool Explosion | Catalog size irrelevant, sirf top-3/5 jaate hain |
| 2 | Skill Shadowing | Cosine similarity, token overlap nahi |
| 3 | Looking≠Picking | Embedding decides routing, LLM nahi |
| 4 | Knowing-Doing Gap | Generation step bypass — embedding direct route |
| 5 | Tool Overuse | Necessity gate: sim < 0.5 → 0 tools |
| 6 | Structural Bias | Sirf semantic similarity, no structural signals |
| 7 | Over-Privileged | Embedding doesn't encode privilege |
| 8 | Skill Conflict | STRAP: similar tools cluster, LLM picks variant |
| 9 | Same-Capability | FAISS se top-K, LLM chooses from small set |
| 10 | Canonical Drift | Stateless per turn, no path to drift |
| 11 | Skill Drift | Re-index on tool update, zero code change |
| 12 | Schema Misalignment | Embedding model never sees schema |

## Key Metrics

| Aspect | Value |
|--------|-------|
| Model size | 33-80MB on disk |
| CPU latency | 5-50ms per query |
| GPU not needed | ✅ pure CPU |
| Training required | **ZERO** |
| Works with any LLM | ✅ OpenAI, Claude, Gemini, DeepSeek, local |
| Works with any provider | ✅ API or self-hosted |
| Schema token savings | ~86% (3559 → ~500) |
| Path 1 frequency | ~80% queries (direct, no LLM clarification) |
| Accuracy vs full catalog | Better — small choice set, less confusion |

## How It Differs From Existing Work

| Existing | Limitation | NATE-Route |
|----------|-----------|------------|
| NTILC | Needs training encoder | Zero training |
| OATS | Only refines embeddings, full router nahi | Full router + feedback |
| LatentGate | Needs SLM forward pass | No SLM, just embedding |
| SkillRouter | Needs 1.2B model | 80MB model, same quality |
| Tool Attention | OpenAI only | Any provider |
| mind-nerve | Needs custom training | Off-the-shelf model |

## Implementation Plan

### Phase 1: Core Router (this session)
- Replace `EmbeddingRouter` (keyword overlap) with `NATE_Route` (sentence-transformers + FAISS)
- STRAP clustering: cos-sim > 0.85 → consolidate
- Dynamic K: threshold-based cutoff
- Necessity gate: best sim < 0.5 → no tools
- Dual-path: confidence ≥ 0.75 → Path 1, else Path 2
- OATS feedback: interpolate embeddings toward success centroid

### Phase 2: Production hardening
- ONNX export for 2x speedup
- FAISS IVF for 10K+ tool catalogs
- Embedding cache for repeated queries
- A/B test vs full catalog

### Phase 3: Advanced
- Multi-query expansion (embed query variants, merge results)
- Cross-encoder reranking (minilm-6 vs cross-encoder/ms-marco)
- Online embedding drift monitoring

## Dependencies
- `sentence-transformers` (all-MiniLM-L6-v2 auto-downloads)
- `faiss-cpu` (no GPU variant needed)
- `numpy`

## Files to Modify
- `src/nexus/capabilities/intelligence/nate/adaptive_schema.py` — replace `EmbeddingRouter` → `NATE_Route`
- `src/nexus/capabilities/intelligence/nate/nate_engine.py` — expose router stats, dual-path support
- `src/nexus/capabilities/intelligence/nate/__init__.py` — update exports
- `pyproject.toml` — add deps

## Test
- `tests/test_nate/scripts/real_llm_test.py` — live API test before/after
- Target: 86%+ token reduction, 100% accuracy
