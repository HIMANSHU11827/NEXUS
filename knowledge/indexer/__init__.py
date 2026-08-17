"""Repository indexing facade backed by the canonical Nexus RAG engine.

The kernel historically exposed ``NexusSemanticIndexer`` as a no-op stub while
GUI/V5 used RAG directly.  This facade keeps the kernel contract and routes
indexing/retrieval through the same durable implementation instead of creating
another index format.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


class NexusSemanticIndexer:
    def __init__(self, root: str = "."):
        self.root = os.path.abspath(root or ".")
        self._rag = None

    def _engine(self):
        if self._rag is None:
            from knowledge.rag.engine import NexusAtlasRAG

            self._rag = NexusAtlasRAG(os.path.join(self.root, "knowledge"))
        return self._rag

    def index_workspace(self, file_path: Optional[str] = None) -> str:
        """Index the workspace or one file through the durable RAG store."""
        return self._engine().index_workspace(root_dir=self.root, file_path=file_path)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return structured hybrid retrieval results."""
        return self._engine().hybrid_search(str(query or ""), top_k=max(1, min(int(top_k), 50)))

    def retrieve_as_text(self, query: str, top_k: int = 5) -> str:
        return self._engine().retrieve_as_text(str(query or ""), top_k=max(1, min(int(top_k), 50)))

    def status(self) -> Dict[str, Any]:
        engine = self._engine()
        return {
            "root": self.root,
            "documents": len(getattr(engine, "_doc_store", {}) or {}),
            "index_path": getattr(engine, "_index_path", ""),
            "backend": "NexusAtlasRAG",
        }


__all__ = ["NexusSemanticIndexer"]
