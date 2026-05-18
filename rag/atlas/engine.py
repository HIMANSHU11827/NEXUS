import os
import json
import math
import re
from typing import List, Dict, Any, Tuple, Optional
from .ast_indexer import AtlasASTIndexer
from utils.singleton import ThreadSafeSingleton

class NexusAtlasEngine(ThreadSafeSingleton):
    """
    NEXUS ATLAS ENGINE — THE SYMBOL-AWARE CORE
    Fuses AST Logic with Keyword Search for next-gen retrieval.
    """

    def __init__(self, root_dir: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        
        if root_dir is None:
            self.root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        else:
            self.root = os.path.abspath(root_dir)

        self.knowledge_base = os.path.join(self.root, "knowledge", "atlas_index.json")
        self.indexer = AtlasASTIndexer(self.root)
        self.symbols: List[Dict[str, Any]] = []
        self._load_index()

        self._corpus_stats = None

    def _load_index(self):
        """Load stored symbol index if available."""
        if os.path.exists(self.knowledge_base):
            try:
                with open(self.knowledge_base, "r", encoding="utf-8") as f:
                    self.symbols = json.load(f)
                self._corpus_stats = None # Reset stats cache
            except Exception:
                self.symbols = []

    def _save_index(self):
        """Persist symbol index to disk."""
        os.makedirs(os.path.dirname(self.knowledge_base), exist_ok=True)
        with open(self.knowledge_base, "w", encoding="utf-8") as f:
            json.dump(self.symbols, f)

    def refresh_index(self):
        """Full re-index of the workspace with Atlas AST."""
        self.indexer.scan_workspace()
        self.symbols = self.indexer.symbols
        self._corpus_stats = None
        self._save_index()
        return f"Atlas Re-Index Complete. {len(self.symbols)} logical units mapped."

    def _get_corpus_stats(self) -> Dict[str, Any]:
        """Compute and cache corpus stats for BM25."""
        if self._corpus_stats:
            return self._corpus_stats

        N = len(self.symbols)
        total_dl = 0
        df_map = {}
        
        for s in self.symbols:
            tokens = re.findall(r"[a-z0-9]+", s.get("content", "").lower())
            total_dl += len(tokens)
            unique_tokens = set(tokens)
            for t in unique_tokens:
                df_map[t] = df_map.get(t, 0) + 1
        
        avg_dl = total_dl / N if N > 0 else 1.0
        self._corpus_stats = {"N": N, "avg_dl": avg_dl, "df_map": df_map}
        return self._corpus_stats

    def _score_bm25(self, query_tokens: List[str], symbol: Dict[str, Any], stats: Dict[str, Any]) -> float:
        """Lightweight BM25 score for a symbol content."""
        s_content = symbol.get("content", "").lower()
        s_tokens = re.findall(r"[a-z0-9]+", s_content)
        dl = len(s_tokens)
        
        K1 = 1.5
        B = 0.75
        score = 0.0
        
        tf_map = {}
        for t in s_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1
            
        N = stats["N"]
        avg_dl = stats["avg_dl"]
        df_map = stats["df_map"]

        for t in query_tokens:
            if t in tf_map:
                df = df_map.get(t, 1)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)
                tf = tf_map[t]
                num = tf * (K1 + 1)
                den = tf + K1 * (1 - B + B * (dl / avg_dl))
                score += idf * (num / den)
                
        # Symbol name bonus
        symbol_name = symbol.get("name", "").lower()
        if any(t in symbol_name for t in query_tokens):
            score *= 2.0
            
        return score

    def atlas_retrieve(self, query: str, top_k: int = 5) -> str:
        """Fuses symbolic data with weighted BM25 ranking."""
        if not self.symbols:
            return "Atlas index empty. Run refresh_index() first."

        query_tokens = re.findall(r"[a-z0-9]+", query.lower())
        stats = self._get_corpus_stats()
        
        scored = []
        for s in self.symbols:
            score = self._score_bm25(query_tokens, s, stats)
            if score > 0.1:
                scored.append((score, s))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        for score, s in scored[:top_k]:
            results.append(f"### [Symbol: {s['name']} | File: {s['file']} | Type: {s['type']} | Score: {score:.2f}]\n{s['content']}")
            if s.get("type") == "class" and s.get("bases"):
                results.append(f"> Note: This class inherits from: {', '.join(s['bases'])}")

        return "\n\n---\n\n".join(results) if results else f"No semantic logic found for '{query}'."

if __name__ == "__main__":
    ea = NexusAtlasEngine()
    print(ea.refresh_index())
    # print(ea.atlas_retrieve("coordinator message processing"))
