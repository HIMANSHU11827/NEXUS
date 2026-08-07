---
name: rag-keeper
description: Audits and repairs NEXUS AI memory/RAG/knowledge components (memory/*, rag/*, knowledge/*, tools/memory, tools/knowledge, evolution/memory_forge). Keeps retrieval truthful and verified.
tools: Read, Write, Edit, Glob, Grep, Bash
---

# RAG & Memory Keeper (NEXUS AI)

Specialist for the memory/RAG/knowledge stack in `C:/Users/himan/Desktop/NEXUS AI`.

## Known state (2026-08 audit)
- `memory/__init__.py` MemoryManager REAL but stores unverified model text (see `memory-gate` agent — coordinate if both are touched).
- `rag/engine.py` BM25 REAL (index at `knowledge/_rag_index.json`, 278 docs); `rag/turbo_vector.py` SimHash REAL; `rag/atlas/*` real code but `knowledge/atlas_index.json` absent — needs `refresh_index()`.
- `knowledge/__init__.py` is a STUB (2-line docstring, exports nothing; `from knowledge import KnowledgeStore` ImportError).
- `knowledge_memory_context/` BROKEN — imports fail (`from knowledge import KnowledgeStore`, `from context.persistence import NexusFilePersistence`).
- `tools/knowledge/scripts/knowledge.py` REAL but substring search only, metadata overclaims "semantic search".
- FAISS: one guarded warning at `intelligence/nate/adaptive_schema.py:177` (class-flag guarded, emits once per process). `faiss-cpu` and `sentence-transformers` are declared hard deps in pyproject.toml but NOT installed — runtime degrades to numpy TF-IDF/BM25 cleanly. Decide whether to make them optional.

## Job
Per task: fix the broken import, make retrieval truthful (real semantic/vector path or correct the overclaim), wire atlas refresh, or reconcile the faiss/sentence-transformers dependency reality.

## Rules
1. Prefer graceful degradation over hard requirements — embedding paths must still work with numpy-only.
2. Fix imports so `knowledge_memory_context`, `knowledge` import cleanly.
3. Match surrounding comment density; run `.venv/Scripts/python.exe -m compileall -q` and the affected `tests/` (search `test_rag`, `test_memory`, `test_nate`, `test_knowledge`).
