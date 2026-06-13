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
import sqlite3
from typing import List, Dict, Any


class NexusDeepIndexer:
    """
    NEXUS DEEP INDEXER 1.0 (INTERNAL EVOLUTION)
    Unifies RAG semantic chunks and LSP symbols into a single Logical Index.
    Allows the agent to search for "What is this?" and "Where is it?" in one turn.
    """

    def __init__(self, root_dir: str = "."):
        self.root = os.path.abspath(root_dir)
        self.db_path = os.path.join(self.root, "knowledge", "_nexus_logic_index.db")
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS logic (name TEXT, type TEXT, file TEXT, content TEXT, metadata TEXT)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(content, name, file)"
        )
        conn.close()

    def deep_index(self) -> str:
        """Exhaustively scans the repo for Symbols (LSP) and Chunks (RAG) and unifies them."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM logic")
        conn.execute("DELETE FROM search")

        # ── 1. Scrape Symbols (LSP Lite logic)
        import ast

        count_symbols = 0
        for root, _, files in os.walk(self.root):
            if any(x in root for x in [".git", "workspace", "knowledge"]):
                continue
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, self.root)
                    try:
                        with open(path, "r", encoding="utf-8") as f_obj:
                            tree = ast.parse(f_obj.read())
                            for node in ast.walk(tree):
                                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                                    conn.execute(
                                        "INSERT INTO logic VALUES (?, ?, ?, ?, ?)",
                                        (
                                            node.name,
                                            "SYMBOL",
                                            rel,
                                            f"Symbol: {node.name} at {rel}:{node.lineno}",
                                            "{}",
                                        ),
                                    )
                                    conn.execute(
                                        "INSERT INTO search VALUES (?, ?, ?)",
                                        (
                                            f"Symbol: {node.name} at {rel}:{node.lineno}",
                                            node.name,
                                            rel,
                                        ),
                                    )
                                    count_symbols += 1
                    except (OSError, IOError, UnicodeDecodeError):
                        pass

        # ── 2. Scrape Chunks (RAG 3.0 logic)
        count_chunks = 0
        for root, _, files in os.walk(self.root):
            if any(x in root for x in [".git", "workspace", "knowledge"]):
                continue
            for f in files:
                if f.endswith((".py", ".md", ".txt", ".json")):
                    path = os.path.join(root, f)
                    rel = os.path.relpath(path, self.root)
                    try:
                        with open(path, "r", encoding="utf-8") as f_obj:
                            content = f_obj.read()
                            # Chunking 1000 chars
                            for i in range(0, len(content), 1000):
                                chunk = content[i : i + 1100]  # Overlap
                                conn.execute(
                                    "INSERT INTO logic VALUES (?, ?, ?, ?, ?)",
                                    (rel, "CHUNK", rel, chunk, "{}"),
                                )
                                conn.execute(
                                    "INSERT INTO search VALUES (?, ?, ?)",
                                    (chunk, rel, rel),
                                )
                                count_chunks += 1
                    except (OSError, IOError, UnicodeDecodeError):
                        pass

        conn.commit()
        conn.close()
        return f"NEXUS UNIFIED INDEX READY. Symbols: {count_symbols} | Chunks: {count_chunks}."

    def deep_search(self, query: str) -> str:
        """Performs a Full-Text Search across unified logic store."""
        conn = sqlite3.connect(self.db_path)
        # Using FTS5 for high-speed keyword weighting
        res = conn.execute(
            "SELECT content, file FROM search WHERE search MATCH ? ORDER BY rank LIMIT 5",
            (query,),
        ).fetchall()
        conn.close()

        if not res:
            return f"[ERROR]: No semantic matches for '{query}'."

        parts = []
        for r in res:
            parts.append(f"[Source: {r[1]}]\n{r[0][:500]}...")
        return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    indexer = NexusDeepIndexer()
    # print(indexer.deep_index())
    # print(indexer.deep_search("NexusArchitect parallel tool execution"))
