"""
NEXUS RAG WRAPPER — Ensures PYTHONHOME is cleared before importing rag modules.
The uv-managed PYTHONHOME env var points to a broken cpython-3.11, causing
"SRE module mismatch" in Python 3.14. This wrapper is the canonical entry point
for all rag operations.

Usage:
    PYTHONHOME="" python scripts/rag_wrapper.py [action]

Actions:
    index          — Full workspace re-index
    query <text>   — BM25 text retrieval
    rebuild        — Clear & rebuild all indices
    verify         — Quick health check
"""
import os
import sys

# ── CRITICAL: Fix PYTHONHOME contamination ─────────────────────────────
# PYTHONHOME (set by uv to cpython-3.11) causes "SRE module mismatch" and
# broken C extensions in Python 3.14. Two fixes needed:
#   1. Clear PYTHONHOME from environment (prevent subprocess contamination)
#   2. Strip cpython-3.11 paths from sys.path (already cached by interpreter)
os.environ.pop("PYTHONHOME", None)
sys.path = [p for p in sys.path if 'cpython-3.11' not in p.lower()]

# Now safe to import non-builtin modules
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rag.engine import NexusAtlasRAG


def do_index():
    rag = NexusAtlasRAG()
    result = rag.index_workspace()
    print(f"[RAG] {result}")
    print(f"[RAG] Total docs in store: {len(rag._doc_store)}")
    return result


def do_query(text):
    rag = NexusAtlasRAG()
    result = rag.retrieve_as_text(text)
    print(result)


def do_rebuild():
    rag = NexusAtlasRAG()
    result = rag.rebuild_index()
    print(f"[RAG] {result}")
    print(f"[RAG] Total docs in store: {len(rag._doc_store)}")
    return result


def do_verify():
    rag = NexusAtlasRAG()
    print(f"Index:     {rag._index_path}")
    print(f"Exists:    {os.path.exists(rag._index_path)}")
    print(f"Docs:      {len(rag._doc_store)}")
    print(f"Turbo:     {'loaded' if rag.turbo_engine else 'None'}")
    print(f"Avg DL:    {rag._avg_dl:.2f}")
    print(f"IDF cache: {len(rag._idf_cache)} terms")

    from rag.turbo_vector import NexusTurboVectorEngine
    tv = NexusTurboVectorEngine()
    print(f"Vector:    {len(tv.store)} entries")

    from rag.atlas.engine import NexusAtlasEngine
    ae = NexusAtlasEngine()
    print(f"Atlas:     {len(ae.symbols)} symbols")

    from rag.deep_indexer import NexusDeepIndexer
    di = NexusDeepIndexer()
    print(f"DeepIdx:   {os.path.exists(di.db_path)}")

    print("\n[RAG] All systems operational.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    action = sys.argv[1]
    if action == "index":
        do_index()
    elif action == "query" and len(sys.argv) > 2:
        do_query(" ".join(sys.argv[2:]))
    elif action == "rebuild":
        do_rebuild()
    elif action == "verify":
        do_verify()
    else:
        print(f"Unknown action: {action}")
        print(__doc__)
        sys.exit(1)
