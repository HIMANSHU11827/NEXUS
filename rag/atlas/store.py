"""
NEXUS ATLAS RELATIONAL STORE (SQLITE FTS5)
High-performance persistent fact memory with Full-Text Search.
Ported from Hermes-Agent store.py logic.
"""

import sqlite3
import json
import logging
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class NexusAtlasStore:
    """
    Relational Fact Store for NEXUS AI.
    Features: FTS5 search, entity resolution, and trust scoring.
    """

    def __init__(self, db_path: str = "knowledge/atlas.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if not exist."""
        with sqlite3.connect(self.db_path) as conn:
            # Main Fact Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT,
                    source TEXT,
                    trust_score REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            # FTS5 Virtual Table for Fast Search
            try:
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(content, content_rowid=id)")
            except sqlite3.OperationalError:
                # Fallback if FTS5 is not available (rare in modern sqlite)
                logger.warning("[ATLAS_SQL]: FTS5 not available. Falling back to standard indexing.")

    def add_fact(self, content: str, category: str = "general", source: str = "manual", metadata: Optional[Dict] = None):
        """Insert a new fact and index it for search."""
        meta_json = json.dumps(metadata or {})
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO facts (content, category, source, metadata) VALUES (?, ?, ?, ?)",
                (content, category, source, meta_json)
            )
            fact_id = cur.lastrowid
            # Index in FTS5
            cur.execute("INSERT INTO facts_fts (rowid, content) VALUES (?, ?)", (fact_id, content))
            conn.commit()
            return fact_id

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Perform high-speed FTS5 BM25 search."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # FTS5 Rank search (BM25)
            sql = """
                SELECT f.*, rank 
                FROM facts f
                JOIN facts_fts fts ON f.id = fts.rowid
                WHERE facts_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            try:
                rows = conn.execute(sql, (query, limit)).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError as e:
                # Fallback if query syntax is complex
                logger.error(f"[ATLAS_SEARCH_ERROR]: {e}")
                return []

    def clear(self):
        """Purge all facts."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM facts")
            conn.execute("DELETE FROM facts_fts")
            conn.commit()
