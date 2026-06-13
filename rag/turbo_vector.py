import os
import sys

# ── Fix PYTHONHOME contamination (see engine.py for details) ───────────
os.environ.pop("PYTHONHOME", None)
sys.path = [p for p in sys.path if 'cpython-3.11' not in p.lower()]
if sys.version_info[:2] == (3, 14):
    _PY314 = r"C:\Python314"
    for _p in [os.path.join(_PY314, "Lib"), os.path.join(_PY314, "DLLs")]:
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(1, _p)

import json
import re
import hashlib
from typing import List, Dict, Any, Tuple

class NexusTurboVectorEngine:
    """
    NEXUS TURBO VECTOR ENGINE 1.0
    Bit-wise semantic similarity matching using SimHash.
    Provides O(1) distance computation for local high-speed RAG.
    """
    def __init__(self, dimension: int = 128, bits: int = 64):
        self.dim = dimension
        self.bits = bits
        self.store: Dict[str, int] = {} # doc_id -> simhash (bitset)
        self.metadata: Dict[str, Dict[str, Any]] = {}

    def _simhash(self, text: str) -> int:
        """Computes a 64-bit SimHash for a block of text."""
        features = re.findall(r"\w+", text.lower())
        if not features: return 0
        
        v = [0] * self.bits
        for f in features:
            # Hash feature to bits
            h = int(hashlib.md5(f.encode('utf-8')).hexdigest(), 16)
            for i in range(self.bits):
                bit = (h >> i) & 1
                v[i] += 1 if bit else -1
        
        fingerprint = 0
        for i in range(self.bits):
            if v[i] > 0:
                fingerprint |= (1 << i)
        return fingerprint

    def add_document(self, doc_id: str, content: str, metadata: Dict[str, Any] = None):
        self.store[doc_id] = self._simhash(content)
        self.metadata[doc_id] = metadata or {}
        self.metadata[doc_id]["content_summary"] = content[:200]

    def remove_document(self, doc_id: str):
        self.store.pop(doc_id, None)
        self.metadata.pop(doc_id, None)

    def clear(self):
        self.store.clear()
        self.metadata.clear()

    def search(self, query: str, top_k: int = 3) -> List[Tuple[float, Dict[str, Any]]]:
        q_hash = self._simhash(query)
        if not q_hash: return []
        
        results = []
        for doc_id, doc_hash in self.store.items():
            # Hamming distance calculation (XOR + bit count)
            hamming = bin(q_hash ^ doc_hash).count('1')
            # Normalize to similarity score [0, 1]
            similarity = 1.0 - (hamming / self.bits)
            if similarity > 0.6: # Threshold
                results.append((similarity, {"id": doc_id, **self.metadata[doc_id]}))
        
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]

    def save(self, path: str):
        data = {"store": self.store, "metadata": self.metadata}
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self, path: str):
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                self.store = data.get("store", {})
                self.metadata = data.get("metadata", {})
