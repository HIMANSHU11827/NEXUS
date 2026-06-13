"""
NEXUS RAG ENGINE 3.1 — DYNAMIC DELTA-INDEXING
Auto-refreshes search chunks if files change on disk.
"""

import os
import sys

# ── Fix PYTHONHOME contamination ───────────────────────────────────────
# PYTHONHOME (set by uv to cpython-3.11) breaks C extension loading in
# Python 3.14. Must fix here for standalone operation; nexus.py also does
# this at boot.
os.environ.pop("PYTHONHOME", None)
sys.path = [p for p in sys.path if 'cpython-3.11' not in p.lower()]
if sys.version_info[:2] == (3, 14):
    _PY314 = r"C:\Python314"
    for _p in [os.path.join(_PY314, "Lib"), os.path.join(_PY314, "DLLs")]:
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(1, _p)

import json
import math
import re
import time
import threading
from typing import List, Dict, Any, Tuple, Optional
from utils.singleton import ThreadSafeSingleton
from rag.turbo_vector import NexusTurboVectorEngine


class NexusAtlasRAG(ThreadSafeSingleton):
    """
    NEXUS RAG ENGINE 3.1 — DYNAMIC DELTA-INDEXING (SINGLETON)
    """

    K1: float = 1.5
    B: float = 0.75

    root: str
    vault: str
    _index_path: str
    _doc_store: Dict[str, Any]
    _avg_dl: float
    _idf_cache: Dict[str, float]
    _initialized: bool

    def __init__(self, vault_path: Optional[str] = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._inverted_index: Dict[str, List[str]] = {}
        
        try:
            self.turbo_engine = NexusTurboVectorEngine() # Turbo Quant Technology Initialization
        except Exception as e:
            print(f"[RAG_WARN]: Turbo Engine failed to init: {e}")
            self.turbo_engine = None

        if vault_path is None:
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            vault_path = os.path.join(_root, "knowledge")
        
        self.root = os.path.dirname(os.path.abspath(vault_path))
        self.vault = os.path.abspath(vault_path)
        os.makedirs(self.vault, exist_ok=True)
        self._index_path = os.path.join(self.vault, "_rag_index.json") # Fixed path — matches actual file on disk
        
        try:
            self._doc_store: Dict[str, Any] = self._load_index()
            self._avg_dl = self._calculate_avg_dl()
            self._idf_cache: Dict[str, float] = {}
            self._rebuild_idf_cache(self._doc_store)
        except (MemoryError, Exception) as e:
            print(f"[RAG_ERROR]: Failed to load index: {e}")
            self._doc_store = {}
            self._avg_dl = 1.0
            self._idf_cache = {}
        
        self._initialized = True

    def _cleanup_stale_entries(self):
        """Removes documents from the store that no longer exist on disk."""
        with self._lock:
            stale_files = set()
            for doc_id, doc in self._doc_store.items():
                file_path = doc.get("file")
                if file_path:
                    abs_path = os.path.join(self.root, file_path)
                    if not os.path.exists(abs_path):
                        stale_files.add(doc_id)
            
            if stale_files:
                for doc_id in stale_files:
                    del self._doc_store[doc_id]
                    if self.turbo_engine:
                        self.turbo_engine.remove_document(doc_id)
                self._save_index()
                print(f"[RAG_CLEANUP]: Removed {len(stale_files)} stale entries.")

    def _calculate_avg_dl(self) -> float:
        """Calculate average document length."""
        if not self._doc_store:
            return 1.0
        total_len = sum(len(doc.get("tokens", [])) for doc in self._doc_store.values())
        return total_len / len(self._doc_store)

    def _load_index(self) -> Dict[str, Any]:
        """Load index from disk."""
        if os.path.exists(self._index_path):
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data
            except (OSError, json.JSONDecodeError, ValueError):
                return {}
        return {}

    def _save_index(self) -> None:
        """Save index to disk and rebuild caches."""
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._doc_store, f)
        self._rebuild_idf_cache(self._doc_store)
        self._avg_dl = self._calculate_avg_dl()

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text, preserving important code symbols."""
        # Preserves underscores, dots (for paths/methods), and handles camelCase/PascalCase
        tokens = re.findall(r"[a-zA-Z0-9_\.]+", text.lower())
        return [t for t in tokens if len(t) > 1]

    def _tf_map(self, tokens: List[str]) -> Dict[str, int]:
        """Build term frequency map from tokens."""
        freq: Dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        return freq

    def _rebuild_idf_cache(self, store: Dict[str, Any]) -> None:
        """Rebuild IDF cache and inverted index from document store."""
        self._idf_cache = {}
        self._inverted_index: Dict[str, List[str]] = {} # Map tokens to doc IDs
        
        N = max(len(store), 1)
        df_map: Dict[str, int] = {}
        for doc_id, doc in store.items():
            tf_map = doc.get("tf_map", {})
            for term in tf_map.keys():
                df_map[term] = df_map.get(term, 0) + 1
                if term not in self._inverted_index:
                    self._inverted_index[term] = []
                self._inverted_index[term].append(doc_id)

        for term, df in df_map.items():
            self._idf_cache[term] = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

    def _idf(self, term: str) -> float:
        """Get IDF score for a term."""
        return self._idf_cache.get(term, math.log(len(self._doc_store) + 1.0))

    def _chunk_text(self, text: str, size: int = 1500, overlap: int = 150) -> List[str]:
        """Split text into overlapping chunks."""
        chunks: List[str] = []
        for i in range(0, len(text), size - overlap):
            chunks.append(text[i : i + size])
        return chunks

    def store_document(self, filename: str, content: str, mtime: float = 0.0) -> None:
        """Store a document in the RAG index."""
        keys_to_del = [
            k for k, v in self._doc_store.items() if v.get("file") == filename
        ]
        for k in keys_to_del:
            del self._doc_store[k]
            if self.turbo_engine:
                self.turbo_engine.remove_document(k)

        chunks = self._chunk_text(content)
        for i, chunk in enumerate(chunks):
            chunk_id = f"{filename}#c{i}"
            tokens = self._tokenize(chunk)
            self._doc_store[chunk_id] = {
                "id": chunk_id,
                "file": filename,
                "content": chunk,
                "tokens": tokens,
                "tf_map": self._tf_map(tokens),
                "mtime": mtime,
                "metadata": {
                    "chunk_index": i,
                    "chunk_count": len(chunks),
                    "length": len(chunk),
                    "stored_at": time.time(),
                },
            }
            # ⚡ Turbo Quant Integration: Add to Vector Engine
            if self.turbo_engine:
                self.turbo_engine.add_document(chunk_id, chunk, {"file": filename})

        self._save_index()

    def index_workspace(
        self, root_dir: Optional[str] = None, file_path: Optional[str] = None
    ) -> str:
        """Index workspace files into RAG store."""
        count = 0
        exclude = {".git", "__pycache__", "workspace", "knowledge", "node_modules"}
        extensions = {".py", ".md", ".txt", ".json", ".js", ".ts", ".c", ".cpp", ".rs"}

        if file_path:
            abs_path = (
                os.path.join(self.root, file_path)
                if not os.path.isabs(file_path)
                else file_path
            )
            if os.path.exists(abs_path):
                try:
                    rel = os.path.relpath(abs_path, self.root).replace("\\", "/")
                    mtime = os.path.getmtime(abs_path)
                    with open(
                        abs_path, "r", encoding="utf-8", errors="ignore"
                    ) as f_obj:
                        self.store_document(rel, f_obj.read(), mtime)
                        return f"Surgical update complete: {rel}"
                except Exception as e:
                    return f"Error indexing {file_path}: {e}"
            return f"File not found: {file_path}"

        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in exclude]
            for f in files:
                if os.path.splitext(f)[1] in extensions:
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, self.root).replace("\\", "/")
                    mtime = os.path.getmtime(path)

                    if mtime > 0:
                        try:
                            with open(
                                path, "r", encoding="utf-8", errors="ignore"
                            ) as f_obj:
                                self.store_document(rel, f_obj.read(), mtime)
                                count += 1
                        except (OSError, IOError):
                            pass

        if count > 0:
            self._save_index()
            
        print(f"[RAG_3.3]: BM25 Index Complete. {count} files updated.")
        return f"Refreshed {count} documents."

    def retrieve_as_text(self, query: str, top_k: int = 5) -> str:
        """Retrieve top-k relevant documents for a query using BM25 with inverted index."""
        if not self._doc_store:
            return "RAG store empty."
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return "Empty query."

        # Use inverted index to find candidate documents
        candidate_ids = set()
        for t in q_tokens:
            if t in self._inverted_index:
                candidate_ids.update(self._inverted_index[t])
        
        if not candidate_ids:
            return "No relevant matches found."

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for doc_id in candidate_ids:
            doc = self._doc_store[doc_id]
            dl = len(doc.get("tokens", []))
            score = 0.0
            tf_map = doc.get("tf_map", {})
            for t in q_tokens:
                if t in tf_map:
                    idf = self._idf(t)
                    tf = tf_map[t]
                    num = tf * (self.K1 + 1)
                    den = tf + self.K1 * (1 - self.B + self.B * (dl / self._avg_dl))
                    score += idf * (num / den)

            if score > 0.1:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return "No relevant matches found."

        parts: List[str] = []
        for s, d in scored[:top_k]:
            rel_path = d.get("file", d.get("id", "unknown"))
            parts.append(
                f"### [Source: {rel_path} | Score: {s:.2f}]\n{d['content'][:1500]}..."
            )

        return "\n\n---\n\n".join(parts)

    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return structured hybrid keyword + vector results.

        BM25 is the primary reliable path. If the vector engine is available,
        its results are blended in without making retrieval depend on it.
        """
        bm25_results: Dict[str, Dict[str, Any]] = {}
        q_tokens = self._tokenize(query)
        if q_tokens and self._doc_store:
            candidate_ids = set()
            for token in q_tokens:
                candidate_ids.update(self._inverted_index.get(token, []))
            for doc_id in candidate_ids:
                doc = self._doc_store[doc_id]
                dl = len(doc.get("tokens", []))
                score = 0.0
                tf_map = doc.get("tf_map", {})
                for token in q_tokens:
                    if token in tf_map:
                        tf = tf_map[token]
                        den = tf + self.K1 * (1 - self.B + self.B * (dl / self._avg_dl))
                        score += self._idf(token) * ((tf * (self.K1 + 1)) / den)
                if score > 0:
                    bm25_results[doc_id] = {
                        "id": doc_id,
                        "file": doc.get("file"),
                        "content": doc.get("content", ""),
                        "metadata": doc.get("metadata", {}),
                        "bm25_score": score,
                        "vector_score": 0.0,
                    }

        if self.turbo_engine:
            try:
                for vector_score, item in self.turbo_engine.search(query, top_k=top_k):
                    doc_id = item.get("id")
                    if not doc_id:
                        continue
                    entry = bm25_results.setdefault(
                        doc_id,
                        {
                            "id": doc_id,
                            "file": item.get("metadata", {}).get("file"),
                            "content": item.get("content_summary", ""),
                            "metadata": item.get("metadata", {}),
                            "bm25_score": 0.0,
                            "vector_score": 0.0,
                        },
                    )
                    entry["vector_score"] = max(entry.get("vector_score", 0.0), float(vector_score))
            except Exception:
                print("[RAG_WARN]: hybrid_search turbo engine failed — BM25 only")
                pass

        results = list(bm25_results.values())
        for result in results:
            result["score"] = result.get("bm25_score", 0.0) + result.get("vector_score", 0.0)
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def rebuild_index(self) -> str:
        """Clear and rebuild the persistent index from the project root."""
        self._doc_store = {}
        self._inverted_index = {}
        self._idf_cache = {}
        if self.turbo_engine:
            self.turbo_engine.clear()
        return self.index_workspace()

    def cleanup_memory(self) -> int:
        """Remove stale indexed chunks whose source file no longer exists."""
        before = len(self._doc_store)
        self._cleanup_stale_entries()
        return before - len(self._doc_store)

    def turbo_search(self, query: str, top_k: int = 5) -> str:
        """
        Retrieves relevant documents using Turbo Quant Technology (Vector Search).
        Provides semantic awareness beyond keyword matching.

        Raises RuntimeError if the Turbo Quant Engine is unavailable or search fails,
        allowing callers to fall back to BM25 retrieval.
        """
        if self.turbo_engine is None:
            print("[RAG_WARN]: turbo_engine not available — will fall back to BM25")
            raise RuntimeError("Turbo Quant Engine not initialized")
        try:
            results = self.turbo_engine.search(query, top_k=top_k)
        except Exception as e:
            print(f"[RAG_ERROR]: turbo_search failed: {e}")
            raise RuntimeError(f"Turbo Quant Search failed: {e}") from e
        if not results:
            return "Turbo Quant Search: No matches found."

        parts: List[str] = [f"⚡ [TURBO QUANT ENABLED SEARCH RESULTS]"]
        for score, item in results:
            doc_id = item["id"]
            content = item["content_summary"]
            parts.append(f"### [Source: {doc_id} | Neural Match: {score:.4f}]\n{content}...")

        return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    rag = NexusAtlasRAG()
    print(rag.retrieve_as_text("Kernel boot logic"))
