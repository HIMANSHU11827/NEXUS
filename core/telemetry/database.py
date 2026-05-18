import sqlite3
import os
import json
import time
from typing import Dict, Any, List, Optional
from pathlib import Path

class NexusTelemetryDB:
    """
    Persistence layer for NEXUS telemetry and state.
    Tracks tool calls, model usage, costs, and success rates.
    """
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Place in .gemini/antigravity or workspace logs
            db_path = str(Path.home() / ".nexus" / "telemetry.db")
        
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT,
                    args TEXT,
                    result TEXT,
                    success INTEGER,
                    duration REAL,
                    timestamp REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    cost REAL,
                    timestamp REAL
                )
            """)
            conn.commit()

    def log_tool_call(self, name: str, args: Dict, result: Any, success: bool, duration: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tool_calls (tool_name, args, result, success, duration, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (name, json.dumps(args), str(result), 1 if success else 0, duration, time.time())
            )
            conn.commit()

    def log_model_usage(self, model: str, prompt_tokens: int, completion_tokens: int, cost: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO model_usage (model, prompt_tokens, completion_tokens, cost, timestamp) VALUES (?, ?, ?, ?, ?)",
                (model, prompt_tokens, completion_tokens, cost, time.time())
            )
            conn.commit()
            
    def get_stats(self) -> Dict[str, Any]:
        """Returns high-level statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(success) FROM tool_calls")
            total_tools, successful_tools = cursor.fetchone()
            
            cursor.execute("SELECT SUM(cost) FROM model_usage")
            total_cost = cursor.fetchone()[0] or 0.0
            
            return {
                "total_tool_calls": total_tools or 0,
                "success_rate": (successful_tools / total_tools * 100) if total_tools else 0,
                "total_cost_usd": total_cost
            }

    def get_recent_failures(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves the most recent tool failures."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tool_name, args, result, duration, timestamp FROM tool_calls WHERE success = 0 ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
