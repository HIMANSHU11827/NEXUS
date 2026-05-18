"""
NEXUS tool-learning store.
Tracks tool weights and reinforcement signals for adaptive routing experiments.
"""

import os
import json
import sqlite3
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
    # from core.neural.turbo_quant import TurboQuantEngine

logger = logging.getLogger(__name__)

class NexusNerveCenter:
    """
    Manages the 'Neural' state of the NEXUS source code.
    Weights are applied to tools, prompts, and reasoning paths.
    """

    def __init__(self, root_dir: str):
        self.root = os.path.abspath(root_dir)
        self.db_path = os.path.join(self.root, "core", "neural", "synapse.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # self.tq = None # Lazy load TurboQuant
        # self.tq = TurboQuantEngine(bits=4) # Initialize Turbo Quant Engine
        self.tq = None
        self._init_db()

    def _init_db(self):
        """Initialize the Synaptic Database."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Weights for tools Based on specific task categories
        c.execute('''CREATE TABLE IF NOT EXISTS tool_synapses 
                     (task_type TEXT, tool_name TEXT, weight REAL, hits INTEGER, LAST_USED REAL,
                      PRIMARY KEY (task_type, tool_name))''')
        # Cognitive weights for system prompts
        c.execute('''CREATE TABLE IF NOT EXISTS prompt_synapses
                     (prompt_id TEXT, weight REAL, success_rate REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS system_mutations
                     (timestamp REAL, file_path TEXT, change_type TEXT, 
                      rationale TEXT, fitness_score REAL, rollback_id TEXT)''')
        # --- v17 TURBO QUANT STORAGE (Compressed Synapses) ---
        c.execute('''CREATE TABLE IF NOT EXISTS compressed_synapses
                     (blob_id TEXT PRIMARY KEY, quantized_data TEXT, norm REAL)''')
        conn.commit()
        conn.close()

    def get_tool_activation(self, task_type: str, tool_name: str) -> float:
        """Returns the 'Activation Weight' for a specific tool in a given context."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT weight FROM tool_synapses WHERE task_type = ? AND tool_name = ?", 
                  (task_type, tool_name))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 1.0 # Default weight is 1.0

    def reinforce(self, task_type: str, tool_name: str, delta: float):
        """[BACKPROPAGATION]: Updates the synaptic weight based on success/failure."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO tool_synapses (task_type, tool_name, weight, hits, LAST_USED)
                     VALUES (?, ?, ?, 1, ?)
                     ON CONFLICT(task_type, tool_name) DO UPDATE SET
                     weight = weight + ?,
                     hits = hits + 1,
                     LAST_USED = ?''', (task_type, tool_name, 1.0 + delta, time.time(), delta, time.time()))
        conn.commit()
        conn.close()
        logger.info(f"[NERVE_CENTER]: Reinforced {tool_name} for {task_type} with delta {delta}")

    def get_optimal_path(self, task_type: str) -> List[str]:
        """Returns tools sorted by their neural activation for this task."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT tool_name FROM tool_synapses WHERE task_type = ? ORDER BY weight DESC", (task_type,))
        tools = [row[0] for row in c.fetchall()]
        conn.close()
        return tools

    def log_mutation(self, path: str, c_type: str, rationale: str, fitness: float = 1.0):
        """[SELF_CREATION_LOGGING]: Records an autonomous update to the organism's body."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO system_mutations VALUES (?, ?, ?, ?, ?, ?)",
                  (time.time(), path, c_type, rationale, fitness, "LIVE"))
        conn.commit()
        conn.close()
        logger.info(f"[NERVE_CENTER]: Logged Self-Creation Event for {path}")

    def mutate_code(self, module_path: str, proposed_logic: str, rationale: str):
        """[SURGICAL_EVOLUTION]: Direct rewrite of neural nodes (source code)."""
        full_path = os.path.join(self.root, module_path)
        if not os.path.exists(full_path):
            return False, f"Module {module_path} not found for mutation."
        
        try:
            # Create a backup before surgical intervention
            backup_path = f"{full_path}.{int(time.time())}.bak"
            import shutil
            shutil.copy2(full_path, backup_path)
            
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(proposed_logic)
            
            self.log_mutation(module_path, "SURGICAL_UPGRADE", rationale, fitness=1.2)
            return True, f"Mutation SUCCESS for {module_path}. Backup: {os.path.basename(backup_path)}"
        except Exception as e:
            return False, f"Mutation FAILED: {str(e)}"

    def sleep_cycle(self):
        """[NEURAL_SLEEP]: Prunes weak synapses and optimizes memory."""
        logger.info("[NERVE_CENTER]: Entering Deep Sleep Cycle for neural optimization...")
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 1. Prune weak synapses (weight < 0.5)
        c.execute("DELETE FROM tool_synapses WHERE weight < 0.5")
        
        # 2. Decay old synapses (apply 0.95x decay to everything but the top hitters)
        c.execute("UPDATE tool_synapses SET weight = weight * 0.95 WHERE hits < 10")
        
        # 3. Clean up old mutations (keep only last 50)
        c.execute("DELETE FROM system_mutations WHERE timestamp NOT IN (SELECT timestamp FROM system_mutations ORDER BY timestamp DESC LIMIT 50)")
        
        # 4. [TURBO_QUANT]: Synaptic Compaction
        # Compress all tool weights into a single high-density vector for backup
        c.execute("SELECT weight FROM tool_synapses ORDER BY task_type, tool_name")
        weights = [row[0] for row in c.fetchall()]
        if weights:
            from core.neural.turbo_quant import TurboQuantEngine
            if self.tq is None:
                self.tq = TurboQuantEngine(bits=4)
            q_pkg = self.tq.polar_quantize(weights)
            c.execute("INSERT OR REPLACE INTO compressed_synapses VALUES (?, ?, ?)",
                      ("MASTER_WEIGHTS_V1", json.dumps(q_pkg["q_data"]), q_pkg["norm"]))
            logger.info(f"[NERVE_CENTER]: TurboQuant Compaction SUCCESS. Normalized Energy: {q_pkg['norm']:.4f}")

        conn.commit()
        conn.close()
        logger.info("[NERVE_CENTER]: Neural Optimization Complete. System refreshed.")
