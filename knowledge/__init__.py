"""NEXUS Knowledge System — encrypted persistent fact storage with a
curated on-disk knowledge base.

Public surface:
- :class:`KnowledgeStore` — reads the curated fact files
  (``knowledge/store.json`` and ``knowledge/library/*/knowledge.json``) and
  exposes list / store / query retrieval.
- :class:`~knowledge.vault.KnowledgeVault` — legacy encrypted-fact vault
  (``knowledge/vault.json.enc``), re-exported for compatibility.

The data files themselves (``store.json``, ``library/``, ``_rag_index.json``)
are never rewritten at import time — this package is a read path over them.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from knowledge.vault import KnowledgeVault

__version__ = "2.0.0"

__all__ = ["KnowledgeStore", "KnowledgeVault"]


def _default_root() -> str:
    """Project root — the directory that owns this ``knowledge/`` package."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _term_tokens(text: str) -> List[str]:
    """Tokenize text for honest keyword scoring (keeps paths/symbols intact)."""
    return [t for t in re.findall(r"[a-z0-9_\.\-]+", (text or "").lower()) if len(t) > 1]


class KnowledgeStore:
    """Curated knowledge base backed by ``knowledge/store.json`` + ``library/``.

    ``store.json`` holds freeform entries written by tools; ``library/`` holds
    versioned one-file-per-topic fact sheets.  Both are plain JSON on disk and
    the same sources the BM25 RAG index (``knowledge/_rag_index.json``) is
    built from.  Retrieval is substring/term-overlap scoring — real keyword
    search, no vector overclaim.
    """

    def __init__(self, root_dir: Optional[str] = None) -> None:
        self.root = os.path.abspath(root_dir) if root_dir else _default_root()
        self.knowledge_dir = os.path.join(self.root, "knowledge")
        self._store_path = os.path.join(self.knowledge_dir, "store.json")
        self._library_dir = os.path.join(self.knowledge_dir, "library")

    # ─── Data loading (read-only) ────────────────────────────────────

    def _load_store_entries(self) -> List[Dict[str, Any]]:
        """Load ``store.json`` (list of ``{title, content, created}``)."""
        if not os.path.isfile(self._store_path):
            return []
        try:
            data = json.loads(Path(self._store_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict) and e.get("content") is not None]

    def _load_library_entries(self) -> List[Dict[str, Any]]:
        """Load ``library/*/knowledge.json`` fact sheets.

        Each file is a dict with at least ``title`` / ``content``.  The
        relative path is kept as ``source`` so callers can trace provenance.
        """
        entries: List[Dict[str, Any]] = []
        if not os.path.isdir(self._library_dir):
            return entries
        for dirpath, _dirnames, filenames in os.walk(self._library_dir):
            if "knowledge.json" not in filenames:
                continue
            path = os.path.join(dirpath, "knowledge.json")
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                entries.append({
                    "title": str(data.get("title") or os.path.basename(dirpath)),
                    "content": str(data.get("content") or ""),
                    "created": data.get("created_at"),
                    "source": os.path.relpath(path, self.root).replace("\\", "/"),
                })
        return entries

    # ─── Public API ──────────────────────────────────────────────────

    def list_entries(self) -> List[Dict[str, Any]]:
        """All curated knowledge entries (store entries first, then library)."""
        return self._load_store_entries() + self._load_library_entries()

    def store(self, title: str, content: str) -> bool:
        """Append a freeform entry to ``store.json`` (mirrors KnowledgeTool.store)."""
        title = (title or "").strip()
        if not title or not content:
            return False
        entries = self._load_store_entries()
        import time
        entries.append({
            "title": title,
            "content": content,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        try:
            os.makedirs(self.knowledge_dir, exist_ok=True)
            tmp = self._store_path + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2)
            os.replace(tmp, self._store_path)
            return True
        except OSError:
            return False

    def query(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Substring search across title + content of every entry."""
        query = (query or "").strip().lower()
        matched: List[Dict[str, Any]] = []
        for entry in self.list_entries():
            haystack = (str(entry.get("title", "") or "") + "\n"
                        + str(entry.get("content", "") or "")).lower()
            if not query or query in haystack:
                matched.append(entry)
        return matched[: max(0, int(limit))]

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Term-overlap scoring retrieval (importance = 1.0 for all entries)."""
        tokens = _term_tokens(query)
        if not tokens:
            return []
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for entry in self.list_entries():
            haystack = (str(entry.get("title", "") or "") + "\n"
                        + str(entry.get("content", "") or "")).lower()
            hits = sum(1 for t in tokens if t in haystack)
            if hits:
                scored.append((float(hits), entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _score, entry in scored[: max(0, int(top_k))]]

    def retrieve_as_text(self, query: str, top_k: int = 3) -> str:
        """Retrieve top-k entries formatted for prompt injection.  '' when empty."""
        results = self.search(query, top_k=top_k)
        if not results:
            return ""
        parts: List[str] = []
        for entry in results:
            title = str(entry.get("title", "untitled"))
            content = str(entry.get("content", ""))
            source = str(entry.get("source", ""))
            header = f"[{title}]" + (f" ({source})" if source else "")
            parts.append(f"{header}\n{content[:800]}")
        return "\n\n---\n\n".join(parts)
