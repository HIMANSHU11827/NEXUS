"""
NEXUS SOVEREIGN MEMORY KERNEL (v1.1)
The definitive implementation of Infinite Memory & Episodic Awareness.
Combines Hierarchical Paging (MemGPT) with Mental Time Travel (MTT).

V1.1 changes:
  - Added write-access validation for storage directory with tempdir fallback
  - Thread-safe _initialized guard via threading.Lock
  - _init_db wrapped in try/except/finally for SQLite error resilience
  - Added validate() and reset() classmethods for testing and diagnostics
  - Proper docstrings on all methods
"""

import os
import json
import time
import sqlite3
import logging
import tempfile
import threading
from typing import List, Dict, Any, Optional, Tuple
from utils.singleton import ThreadSafeSingleton

logger = logging.getLogger("MEMORY_KERNEL")


class MemoryKernel(ThreadSafeSingleton):
    """
    The Single Cognitive Engine for NEXUS.
    Manages Working Memory (RAM), Episodic Memory (Events), and Archival (Vault).

    Initialisation validates the storage directory is writable and falls back
    to a system temp directory if the primary path cannot be created/accessed.
    """

    def __init__(self, root_dir: str):
        # Thread-safe singleton guard — __init__ is called every time the
        # singleton is dereferenced, but we only run setup once.
        with self._init_lock():
            if getattr(self, "_initialized", False):
                return
            self._initialized = True

        self.root = os.path.abspath(root_dir)

        # Resolve the database path with write-access validation & fallback
        primary_db_path = os.path.join(self.root, "core", "neural", "synapse.db")
        self.db_path = self._resolve_storage_path(primary_db_path)
        logger.info(f"[MEM_INIT]: db_path={self.db_path}  root={self.root}")

        # 1. RAM: Working Memory (Volatile)
        self.working_memory: Dict[str, Any] = {}

        # 2. CACHE: Recently accessed episodes
        self._episode_cache: Dict[str, Dict[str, Any]] = {}

        self._init_db()

    # -----------------------------------------------------------------
    # INTERNAL HELPERS
    # -----------------------------------------------------------------

    @staticmethod
    def _init_lock() -> threading.Lock:
        """Return a class-level lock for thread-safe singleton init."""
        if not hasattr(MemoryKernel, "_class_init_lock"):
            MemoryKernel._class_init_lock = threading.Lock()
        return MemoryKernel._class_init_lock

    @staticmethod
    def _resolve_storage_path(primary_path: str) -> str:
        """
        Return *primary_path* if its parent directory is writable; otherwise
        fall back to a temp-directory path.
        """
        db_dir = os.path.dirname(primary_path)
        try:
            os.makedirs(db_dir, exist_ok=True)
            # Probe write access with a tiny marker file
            probe = os.path.join(db_dir, ".nexus_write_test")
            with open(probe, "w") as f:
                f.write("1")
            os.remove(probe)
            return primary_path
        except (OSError, PermissionError) as exc:
            fallback_dir = os.path.join(tempfile.gettempdir(), "nexus_memory_kernel")
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_path = os.path.join(fallback_dir, "synapse.db")
            logger.warning(
                "Cannot write to %s (%s). Falling back to %s",
                db_dir, exc, fallback_path,
            )
            return fallback_path

    def _init_db(self):
        """Ensure episodic tables exist in Synapse DB."""
        conn = None
        try:
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
            logger.info("[MEM_INIT]: DB schema ready at %s", self.db_path)
        except sqlite3.Error as exc:
            logger.error("[MEM_INIT]: Failed to initialise Synapse DB: %s", exc)
            raise
        finally:
            if conn:
                conn.close()

    # --- TIER 1: WORKING MEMORY (RAM) ---

    def ram_store(self, key: str, value: Any):
        """Stores a 'Mental Note' in working memory."""
        self.working_memory[key] = {
            "value": value,
            "timestamp": time.time(),
        }
        logger.info("[MEM_RAM]: Stored %s", key)

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

    def log_episode(
        self,
        session_id: str,
        title: str,
        summary: str,
        content: str,
        links: Optional[List[str]] = None,
    ):
        """Segments and records a new episode in the project narrative."""
        import hashlib
        import uuid

        # Generate unique episode_id with microsecond granularity and uuid for collision prevention
        timestamp_ms = int(time.time() * 1000)
        unique_suffix = uuid.uuid4().hex[:6]
        episode_id = f"EP_{timestamp_ms}_{session_id[:4]}_{unique_suffix}"
        links_str = json.dumps(links or [])
        c_hash = hashlib.md5(content.encode()).hexdigest()

        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute(
                "INSERT INTO episodic_memory VALUES (?, ?, ?, ?, ?, ?, ?)",
                (episode_id, time.time(), title, summary, links_str, c_hash, session_id),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("[MEM_EPISODE]: Archived Episode '%s' (ID: %s)", title, episode_id)

    def list_episodes(
        self, session_id: Optional[str] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Lists recent episodes for 'Mental Time Travel'."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            c = conn.cursor()
            if session_id:
                c.execute(
                    "SELECT * FROM episodic_memory WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (session_id, limit),
                )
            else:
                c.execute(
                    "SELECT * FROM episodic_memory ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            return [dict(r) for r in c.fetchall()]
        finally:
            conn.close()

    # --- TIER 3: COGNITIVE FACTS (MEM0/ZEP) ---

    def store_fact(
        self, entity: str, attribute: str, value: str, importance: int = 1
    ):
        """Stores a personalized fact with temporal awareness."""
        fact_id = f"F_{hash(entity + attribute + str(time.time())) % 1_000_000}"
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute(
                "INSERT INTO cognitive_facts "
                "(fact_id, entity, attribute, value, timestamp, importance) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fact_id, entity, attribute, value, time.time(), importance),
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("[MEM_FACT]: Learned %s.%s = %s", entity, attribute, value)

    def recall_facts(self, entity: str) -> List[Dict[str, Any]]:
        """Recalls all facts about an entity."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            c = conn.cursor()
            c.execute(
                "SELECT * FROM cognitive_facts WHERE entity = ? "
                "ORDER BY importance DESC, timestamp DESC",
                (entity,),
            )
            return [dict(r) for r in c.fetchall()]
        finally:
            conn.close()

    # --- [MENTAL_TIME_TRAVEL] ---

    def simulate_future(self, action: str, history_context: str) -> str:
        """[PROSPECTION]: Uses past episodes to simulate the outcome of an action."""
        # This is a heuristic/placeholder for the actual LLM-based simulation.
        # In practice, the loop will call this with retrieved episodic context.
        return (
            f"[SIMULATION]: Action '{action}' projected to succeed "
            "based on previous similar episodes."
        )

    def retrospective_review(self, current_task: str) -> str:
        """[RETROSPECTION]: Analyzes the current task against past episodes."""
        episodes = self.list_episodes(limit=3)
        if not episodes:
            return "[RETROSPECTION]: No past episodes to analyze."

        summary = "[RETROSPECTION_INSIGHTS]:\n"
        for ep in episodes:
            summary += f"- Past Episode '{ep['title']}': {ep['summary']}\n"
        return summary

    # --- UTILITY ---

    @classmethod
    def validate(cls) -> str:
        """
        Validate that the singleton (if instantiated) is healthy.

        Returns a human-readable status string.
        """
        instance = cls._instances.get(cls)
        if instance is None:
            return "[MEM_VALIDATE]: Not initialised yet."
        db_ok = os.path.isfile(instance.db_path) if os.path.exists(instance.db_path) else False
        ram_keys = list(instance.working_memory.keys())
        return (
            f"[MEM_VALIDATE]: db_path={instance.db_path} "
            f"db_exists={db_ok} "
            f"ram_keys={ram_keys}"
        )

    @classmethod
    def reset(cls):
        """
        Full singleton teardown for testing.

        Removes the cached instance so the next call to MemoryKernel() runs
        __init__ fresh.
        """
        with cls._init_lock():
            cls._reset_instance()
