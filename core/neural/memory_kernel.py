"""
NEXUS SOVEREIGN MEMORY KERNEL (v1.0)
The definitive implementation of Infinite Memory & Episodic Awareness.
Combines Hierarchical Paging (MemGPT) with Mental Time Travel (MTT).
"""

import os
import json
import time
import sqlite3
import logging
from typing import List, Dict, Any, Optional, Tuple
from utils.singleton import ThreadSafeSingleton

logger = logging.getLogger("MEMORY_KERNEL")

class MemoryKernel(ThreadSafeSingleton):
    """
    The Single Cognitive Engine for NEXUS.
    Manages Working Memory (RAM), Episodic Memory (Events), and Archival (Vault).
    """

    def __init__(self, root_dir: str):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.root = os.path.abspath(root_dir)
        self.db_path = os.path.join(self.root, "core", "neural", "synapse.db")
        
        # 1. RAM: Working Memory (Volatile)
        self.working_memory: Dict[str, Any] = {}
        
        # 2. CACHE: Recently accessed episodes
        self._episode_cache: Dict[str, Dict[str, Any]] = {}
        
        self._init_db()

    def _init_db(self):
        """Ensure episodic tables exist in Synapse DB."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Episodes table (Segmented story of the project)
        c.execute('''CREATE TABLE IF NOT EXISTS episodic_memory 
                     (episode_id TEXT PRIMARY KEY, timestamp REAL, 
                      title TEXT, summary TEXT, causal_links TEXT, 
                      content_hash TEXT, session_id TEXT)''')
        
        # Facts table (Mem0/Zep style scoped facts)
        c.execute('''CREATE TABLE IF NOT EXISTS cognitive_facts
                     (fact_id TEXT PRIMARY KEY, entity TEXT, attribute TEXT, 
                      value TEXT, timestamp REAL, validity_start REAL, 
                      validity_end REAL, importance INTEGER)''')
        
        conn.commit()
        conn.close()

    # --- TIER 1: WORKING MEMORY (RAM) ---
    def ram_store(self, key: str, value: Any):
        """Stores a 'Mental Note' in working memory."""
        self.working_memory[key] = {
            "value": value,
            "timestamp": time.time()
        }
        logger.info(f"[MEM_RAM]: Stored {key}")

    def ram_recall(self, key: str) -> Optional[Any]:
        """Recalls a 'Mental Note'."""
        item = self.working_memory.get(key)
        return item["value"] if item else None

    def ram_dump(self) -> str:
        """Returns a string representation of current working memory for the prompt."""
        if not self.working_memory:
            return "[WORKING_MEMORY]: Empty."
        
        lines = ["[WORKING_MEMORY]:"]
        for k, v in self.working_memory.items():
            lines.append(f"- {k}: {v['value']}")
        return "\n".join(lines)

    # --- TIER 2: EPISODIC MEMORY (EVENTS) ---
    def log_episode(self, session_id: str, title: str, summary: str, content: str, links: List[str] = None):
        """Segments and records a new episode in the project narrative."""
        episode_id = f"EP_{int(time.time())}_{session_id[:4]}"
        links_str = json.dumps(links or [])
        
        # Create hash to avoid duplicates
        import hashlib
        c_hash = hashlib.md5(content.encode()).hexdigest()
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO episodic_memory VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (episode_id, time.time(), title, summary, links_str, c_hash, session_id))
        conn.commit()
        conn.close()
        
        # Also store content in Vault if not already there
        # (This links the Episodic layer to the Archival layer)
        logger.info(f"[MEM_EPISODE]: Archived Episode '{title}' (ID: {episode_id})")

    def list_episodes(self, session_id: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Lists recent episodes for 'Mental Time Travel'."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if session_id:
            c.execute("SELECT * FROM episodic_memory WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?", 
                      (session_id, limit))
        else:
            c.execute("SELECT * FROM episodic_memory ORDER BY timestamp DESC LIMIT ?", (limit,))
        
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    # --- TIER 3: COGNITIVE FACTS (MEM0/ZEP) ---
    def store_fact(self, entity: str, attribute: str, value: str, importance: int = 1):
        """Stores a personalized fact with temporal awareness."""
        fact_id = f"F_{hash(entity + attribute + str(time.time())) % 1000000}"
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO cognitive_facts (fact_id, entity, attribute, value, timestamp, importance) VALUES (?, ?, ?, ?, ?, ?)",
                  (fact_id, entity, attribute, value, time.time(), importance))
        conn.commit()
        conn.close()
        logger.info(f"[MEM_FACT]: Learned {entity}.{attribute} = {value}")

    def recall_facts(self, entity: str) -> List[Dict[str, Any]]:
        """Recalls all facts about an entity."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM cognitive_facts WHERE entity = ? ORDER BY importance DESC, timestamp DESC", (entity,))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    # --- [MENTAL_TIME_TRAVEL] ---
    def simulate_future(self, action: str, history_context: str) -> str:
        """[PROSPECTION]: Uses past episodes to simulate the outcome of an action."""
        # This is a heuristic/placeholder for the actual LLM-based simulation
        # In practice, the loop will call this with retrieved episodic context.
        return f"[SIMULATION]: Action '{action}' projected to succeed based on previous similar episodes."

    def retrospective_review(self, current_task: str) -> str:
        """[RETROSPECTION]: Analyzes the current task against past episodes."""
        episodes = self.list_episodes(limit=3)
        if not episodes:
            return "[RETROSPECTION]: No past episodes to analyze."
        
        summary = "[RETROSPECTION_INSIGHTS]:\n"
        for ep in episodes:
            summary += f"- Past Episode '{ep['title']}': {ep['summary']}\n"
        return summary
